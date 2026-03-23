"""
媒体文件智能分类系统 - 数据存储层

架构: 内存 SQLite 为主，磁盘文件为持久化后端

特点:
    - sqlite3 是 Python 标准库，无需安装任何额外依赖
    - 内存模式下所有操作零磁盘 I/O，十万级数据毫秒级响应
    - 定时自动保存 + 关闭前强制保存，防止意外丢失
    - 支持手动触发保存
"""
import sqlite3
import shutil
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from .models import CategoryNode, MediaFile, MediaGroup

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE NOT NULL,
        leaf_name TEXT NOT NULL,
        pinyin_full TEXT,
        pinyin_abbr TEXT,
        pinyin_variants TEXT,
        has_face_data INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_cat_pinyin_abbr ON categories(pinyin_abbr);
    CREATE INDEX IF NOT EXISTS idx_cat_pinyin_full ON categories(pinyin_full);

    CREATE TABLE IF NOT EXISTS pinyin_conflicts (
        abbr TEXT NOT NULL,
        category_id INTEGER NOT NULL REFERENCES categories(id),
        PRIMARY KEY (abbr, category_id)
    );

    CREATE TABLE IF NOT EXISTS media_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time_start TEXT, time_end TEXT,
        file_count INTEGER DEFAULT 0,
        detected_tag TEXT,
        category_id INTEGER REFERENCES categories(id),
        confidence REAL DEFAULT 0.0,
        classify_method TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        reviewed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_group_status ON media_groups(status);

    CREATE TABLE IF NOT EXISTS media_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE NOT NULL,
        filename TEXT NOT NULL,
        timestamp TEXT,
        timestamp_source TEXT DEFAULT '',
        file_tag TEXT,
        group_id INTEGER REFERENCES media_groups(id),
        has_face INTEGER,
        is_video INTEGER DEFAULT 0,
        file_category_id INTEGER REFERENCES categories(id) DEFAULT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_media_group ON media_files(group_id);
    CREATE INDEX IF NOT EXISTS idx_media_ts ON media_files(timestamp);

    CREATE TABLE IF NOT EXISTS face_embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER NOT NULL REFERENCES categories(id),
        source_file TEXT,
        embedding BLOB
    );
    CREATE INDEX IF NOT EXISTS idx_face_cat ON face_embeddings(category_id);
"""


class Database:
    """混合存储数据库: 内存SQLite + 磁盘持久化"""

    def __init__(self, db_path: str, auto_save_interval: float = 60.0):
        self.db_path = db_path
        self.auto_save_interval = auto_save_interval
        self.mem: Optional[sqlite3.Connection] = None
        self._dirty = False
        self._save_lock = threading.Lock()
        self._auto_save_timer: Optional[threading.Timer] = None
        self._closed = False

    def open(self):
        self.mem = sqlite3.connect(":memory:", check_same_thread=False)
        self.mem.row_factory = sqlite3.Row
        self.mem.execute("PRAGMA journal_mode=OFF")
        self.mem.execute("PRAGMA synchronous=OFF")
        self.mem.execute("PRAGMA cache_size=-128000")
        self.mem.executescript(_SCHEMA_SQL)
        self.mem.commit()
        disk_path = Path(self.db_path)
        if disk_path.exists() and disk_path.stat().st_size > 0:
            self._load_from_disk()
            logger.info(f"从磁盘加载数据库: {self.db_path}")
        else:
            logger.info(f"新建内存数据库 (持久化路径: {self.db_path})")
        self._dirty = False
        self._closed = False
        if self.auto_save_interval > 0:
            self._schedule_auto_save()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._auto_save_timer:
            self._auto_save_timer.cancel()
            self._auto_save_timer = None
        if self._dirty:
            self.save_to_disk()
            logger.info("关闭前已保存到磁盘")
        if self.mem:
            self.mem.close()
            self.mem = None

    def save_to_disk(self):
        if not self.mem or self._closed:
            return
        with self._save_lock:
            try:
                t0 = time.monotonic()
                tmp_path = self.db_path + ".tmp"
                disk = sqlite3.connect(tmp_path)
                self.mem.backup(disk)
                disk.close()
                final_path = Path(self.db_path)
                tmp = Path(tmp_path)
                if final_path.exists():
                    tmp.replace(final_path)
                else:
                    tmp.rename(final_path)
                elapsed = (time.monotonic() - t0) * 1000
                self._dirty = False
                logger.debug(f"保存到磁盘完成: {elapsed:.1f}ms")
            except Exception as e:
                logger.error(f"保存到磁盘失败: {e}")
                try:
                    Path(self.db_path + ".tmp").unlink(missing_ok=True)
                except Exception:
                    pass

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def _mark_dirty(self):
        self._dirty = True

    def _load_from_disk(self):
        disk = sqlite3.connect(self.db_path)
        disk.backup(self.mem)
        disk.close()

    def _schedule_auto_save(self):
        if self._closed or self.auto_save_interval <= 0:
            return
        def _do_auto_save():
            if self._closed:
                return
            if self._dirty:
                self.save_to_disk()
                logger.debug("自动保存完成")
            self._schedule_auto_save()
        self._auto_save_timer = threading.Timer(self.auto_save_interval, _do_auto_save)
        self._auto_save_timer.daemon = True
        self._auto_save_timer.start()

    def upsert_category(self, cat: CategoryNode) -> int:
        cur = self.mem.execute("""
            INSERT INTO categories (path, leaf_name, pinyin_full, pinyin_abbr, pinyin_variants, has_face_data)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                leaf_name=excluded.leaf_name, pinyin_full=excluded.pinyin_full,
                pinyin_abbr=excluded.pinyin_abbr, pinyin_variants=excluded.pinyin_variants,
                has_face_data=excluded.has_face_data
        """, (cat.path, cat.leaf_name, cat.pinyin_full, cat.pinyin_abbr,
              ','.join(cat.pinyin_variants), int(cat.has_face_data)))
        self.mem.commit()
        self._mark_dirty()
        if cur.lastrowid:
            return cur.lastrowid
        row = self.mem.execute("SELECT id FROM categories WHERE path=?", (cat.path,)).fetchone()
        return row['id']

    def get_all_categories(self) -> list[CategoryNode]:
        rows = self.mem.execute("SELECT * FROM categories ORDER BY path").fetchall()
        result = []
        for r in rows:
            cat = CategoryNode(
                id=r['id'], path=r['path'], leaf_name=r['leaf_name'],
                pinyin_full=r['pinyin_full'] or '', pinyin_abbr=r['pinyin_abbr'] or '',
                pinyin_variants=(r['pinyin_variants'] or '').split(','),
                has_face_data=bool(r['has_face_data']))
            cat.pinyin_variants = [v for v in cat.pinyin_variants if v]
            result.append(cat)
        return result

    def get_category_by_id(self, cat_id: int) -> Optional[CategoryNode]:
        r = self.mem.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
        if not r:
            return None
        cat = CategoryNode(
            id=r['id'], path=r['path'], leaf_name=r['leaf_name'],
            pinyin_full=r['pinyin_full'] or '', pinyin_abbr=r['pinyin_abbr'] or '',
            pinyin_variants=(r['pinyin_variants'] or '').split(','),
            has_face_data=bool(r['has_face_data']))
        cat.pinyin_variants = [v for v in cat.pinyin_variants if v]
        return cat

    def set_pinyin_conflicts(self, abbr: str, cat_ids: list[int]):
        self.mem.execute("DELETE FROM pinyin_conflicts WHERE abbr=?", (abbr,))
        for cid in cat_ids:
            self.mem.execute("INSERT OR IGNORE INTO pinyin_conflicts (abbr, category_id) VALUES (?, ?)", (abbr, cid))
        self.mem.commit()
        self._mark_dirty()

    def get_conflicts_for_abbr(self, abbr: str) -> list[int]:
        rows = self.mem.execute("SELECT category_id FROM pinyin_conflicts WHERE abbr=?", (abbr,)).fetchall()
        return [r['category_id'] for r in rows]

    def insert_group(self, group: MediaGroup) -> int:
        cur = self.mem.execute("""
            INSERT INTO media_groups (time_start, time_end, file_count, detected_tag,
                category_id, confidence, classify_method, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (group.time_start.isoformat() if group.time_start else None,
              group.time_end.isoformat() if group.time_end else None,
              group.file_count, group.detected_tag, group.category_id,
              group.confidence, group.classify_method, group.status))
        self.mem.commit()
        self._mark_dirty()
        return cur.lastrowid

    def update_group_classification(self, group_id: int, category_id: Optional[int],
                                     confidence: float, method: str, status: str):
        self.mem.execute("""
            UPDATE media_groups SET category_id=?, confidence=?, classify_method=?, status=?, reviewed_at=?
            WHERE id=?
        """, (category_id, confidence, method, status, datetime.now().isoformat(), group_id))
        self.mem.commit()
        self._mark_dirty()

    def get_groups_by_status(self, status: str, limit: int = 100, offset: int = 0) -> list[dict]:
        rows = self.mem.execute("""
            SELECT g.*, c.path as category_path FROM media_groups g
            LEFT JOIN categories c ON g.category_id = c.id
            WHERE g.status = ? ORDER BY g.time_start LIMIT ? OFFSET ?
        """, (status, limit, offset)).fetchall()
        return [dict(r) for r in rows]

    def get_all_groups(self, limit: int = 100, offset: int = 0) -> list[dict]:
        rows = self.mem.execute("""
            SELECT g.*, c.path as category_path FROM media_groups g
            LEFT JOIN categories c ON g.category_id = c.id
            ORDER BY g.time_start LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
        return [dict(r) for r in rows]

    def load_all_groups_as_models(self) -> list[MediaGroup]:
        rows = self.mem.execute("""
            SELECT g.*, c.path as category_path FROM media_groups g
            LEFT JOIN categories c ON g.category_id = c.id
            ORDER BY g.time_start
        """).fetchall()
        groups = []
        for r in rows:
            ts = datetime.fromisoformat(r['time_start']) if r['time_start'] else None
            te = datetime.fromisoformat(r['time_end']) if r['time_end'] else None
            g = MediaGroup(
                id=r['id'], time_start=ts, time_end=te,
                file_count=r['file_count'], detected_tag=r['detected_tag'],
                category_id=r['category_id'], category_path=r['category_path'],
                confidence=r['confidence'] or 0.0, classify_method=r['classify_method'] or '',
                status=r['status'] or 'pending')
            groups.append(g)
        return groups

    def get_group_count_by_status(self) -> dict[str, int]:
        rows = self.mem.execute("SELECT status, COUNT(*) as cnt FROM media_groups GROUP BY status").fetchall()
        return {r['status']: r['cnt'] for r in rows}

    def get_total_group_count(self) -> int:
        row = self.mem.execute("SELECT COUNT(*) as cnt FROM media_groups").fetchone()
        return row['cnt']

    def insert_files_batch(self, files: list[MediaFile]):
        data = [
            (f.path, f.filename, f.timestamp.isoformat() if f.timestamp else None,
             f.timestamp_source, f.file_tag, f.group_id, None, int(f.is_video))
            for f in files
        ]
        self.mem.executemany("""
            INSERT OR IGNORE INTO media_files
                (path, filename, timestamp, timestamp_source, file_tag, group_id, has_face, is_video)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, data)
        self.mem.commit()
        self._mark_dirty()

    def get_files_for_group(self, group_id: int) -> list[MediaFile]:
        rows = self.mem.execute("""
            SELECT f.*, c.path as file_category_path FROM media_files f
            LEFT JOIN categories c ON f.file_category_id = c.id
            WHERE f.group_id=? ORDER BY f.timestamp
        """, (group_id,)).fetchall()
        result = []
        for r in rows:
            ts = datetime.fromisoformat(r['timestamp']) if r['timestamp'] else None
            mf = MediaFile(
                id=r['id'], path=r['path'], filename=r['filename'],
                timestamp=ts, timestamp_source=r['timestamp_source'] or '',
                file_tag=r['file_tag'], group_id=r['group_id'],
                has_face=bool(r['has_face']) if r['has_face'] is not None else None,
                is_video=bool(r['is_video']),
                file_category_id=r['file_category_id'],
                file_category_path=r['file_category_path'])
            result.append(mf)
        return result

    def update_file_category(self, file_id: int, category_id: Optional[int]):
        self.mem.execute("UPDATE media_files SET file_category_id=? WHERE id=?", (category_id, file_id))
        self.mem.commit()
        self._mark_dirty()

    def clear_file_category(self, file_id: int):
        self.update_file_category(file_id, None)

    def batch_update_file_categories(self, updates: list[tuple[int, Optional[int]]]):
        self.mem.executemany("UPDATE media_files SET file_category_id=? WHERE id=?",
            [(cat_id, fid) for fid, cat_id in updates])
        self.mem.commit()
        self._mark_dirty()

    def insert_face_embedding(self, category_id: int, source_file: str, embedding: bytes):
        self.mem.execute("INSERT INTO face_embeddings (category_id, source_file, embedding) VALUES (?, ?, ?)",
            (category_id, source_file, embedding))
        self.mem.commit()
        self._mark_dirty()

    def get_face_embeddings_for_category(self, category_id: int) -> list[bytes]:
        rows = self.mem.execute("SELECT embedding FROM face_embeddings WHERE category_id=?", (category_id,)).fetchall()
        return [r['embedding'] for r in rows]

    def get_all_face_categories(self) -> list[int]:
        rows = self.mem.execute("SELECT DISTINCT category_id FROM face_embeddings").fetchall()
        return [r['category_id'] for r in rows]

    def clear_all_data(self):
        self.mem.executescript("""
            DELETE FROM face_embeddings; DELETE FROM media_files;
            DELETE FROM media_groups; DELETE FROM pinyin_conflicts; DELETE FROM categories;
        """)
        self.mem.commit()
        self._mark_dirty()

    def clear_groups_and_files(self):
        """仅清除分组和文件数据，保留类别"""
        self.mem.executescript("""
            DELETE FROM media_files; DELETE FROM media_groups;
            DELETE FROM sqlite_sequence WHERE name IN ('media_files', 'media_groups');
        """)
        self.mem.commit()
        self._mark_dirty()

    def delete_group(self, group_id: int):
        self.mem.execute("DELETE FROM media_files WHERE group_id=?", (group_id,))
        self.mem.execute("DELETE FROM media_groups WHERE id=?", (group_id,))
        self.mem.commit()
        self._mark_dirty()

    def get_export_data(self) -> list[dict]:
        rows = self.mem.execute("""
            SELECT f.id as file_id, f.path as file_path, f.filename, f.timestamp,
                f.file_category_id, g.id as group_id, g.category_id as group_category_id,
                g.confidence, g.classify_method, g.status,
                COALESCE(fc.path, gc.path) as effective_category,
                CASE WHEN f.file_category_id IS NOT NULL THEN 'file_override'
                    ELSE g.classify_method END as effective_method,
                CASE WHEN f.file_category_id IS NOT NULL THEN 1.0
                    ELSE g.confidence END as effective_confidence
            FROM media_files f JOIN media_groups g ON f.group_id = g.id
            LEFT JOIN categories fc ON f.file_category_id = fc.id
            LEFT JOIN categories gc ON g.category_id = gc.id
            WHERE g.status IN ('auto', 'confirmed') OR f.file_category_id IS NOT NULL
            ORDER BY g.id, f.timestamp
        """).fetchall()
        return [dict(r) for r in rows if r['effective_category']]
