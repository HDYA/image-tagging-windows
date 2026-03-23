"""
媒体文件智能分类系统 - 文件扫描 + EXIF 读取 + 时间分组
"""
import os
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import AppConfig
from .models import MediaFile, MediaGroup

logger = logging.getLogger(__name__)

_EXIF_EXTENSIONS = {
    '.jpg', '.jpeg', '.tiff', '.tif', '.heic', '.heif',
    '.cr2', '.nef', '.arw', '.dng', '.raf'
}


def _ts_exif(filepath: str, filename: str, config: AppConfig) -> Optional[datetime]:
    ext = Path(filepath).suffix.lower()
    if ext not in _EXIF_EXTENSIONS:
        return None
    try:
        import exifread
        with open(filepath, 'rb') as f:
            tags = exifread.process_file(f, stop_tag='DateTimeOriginal', details=False)
        dt_tag = tags.get('EXIF DateTimeOriginal') or tags.get('Image DateTime')
        if dt_tag:
            return datetime.strptime(str(dt_tag), '%Y:%m:%d %H:%M:%S')
    except Exception:
        pass
    return None


def _ts_mtime(filepath: str, filename: str, config: AppConfig) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(os.stat(filepath).st_mtime)
    except Exception:
        return None


def _ts_ctime(filepath: str, filename: str, config: AppConfig) -> Optional[datetime]:
    try:
        stat = os.stat(filepath)
        if hasattr(stat, 'st_birthtime'):
            return datetime.fromtimestamp(stat.st_birthtime)
        return datetime.fromtimestamp(stat.st_ctime)
    except Exception:
        return None


def _ts_filename(filepath: str, filename: str, config: AppConfig) -> Optional[datetime]:
    stem = Path(filename).stem
    for pattern in config.filename_time_patterns:
        match = re.search(pattern, stem)
        if not match:
            match = re.search(pattern, filename)
        if not match:
            continue
        groups = match.groupdict()
        try:
            if 'unix_ms' in groups and groups['unix_ms']:
                return datetime.fromtimestamp(int(groups['unix_ms']) / 1000.0)
            if 'unix_s' in groups and groups['unix_s']:
                return datetime.fromtimestamp(int(groups['unix_s']))
            if 'year' in groups:
                return datetime(
                    year=int(groups['year']), month=int(groups.get('month', 1)),
                    day=int(groups.get('day', 1)), hour=int(groups.get('hour', 0)),
                    minute=int(groups.get('minute', 0)), second=int(groups.get('second', 0)))
        except (ValueError, OverflowError, OSError):
            continue
    return None


_TIMESTAMP_STRATEGIES: dict[str, callable] = {
    "exif": _ts_exif, "mtime": _ts_mtime, "ctime": _ts_ctime, "filename": _ts_filename,
}


def get_file_timestamp(filepath: str, filename: str,
                       config: AppConfig) -> tuple[Optional[datetime], str]:
    for source_name in config.timestamp_priority:
        strategy = _TIMESTAMP_STRATEGIES.get(source_name)
        if strategy is None:
            logger.warning(f"未知的时间戳来源: '{source_name}'")
            continue
        dt = strategy(filepath, filename, config)
        if dt is not None:
            return dt, source_name
    return None, ""


def _extract_tag(filename: str, patterns: list[str]) -> Optional[str]:
    stem = Path(filename).stem
    for pattern in patterns:
        match = re.search(pattern, stem)
        if match:
            tag = match.group(1).lower()
            if tag in {'img', 'vid', 'mov', 'dsc', 'pic', 'raw', 'edit',
                       'copy', 'original', 'modified', 'export', 'mmexport',
                       'screenshot', 'screen', 'photo', 'video', 'image',
                       'thumb', 'thumbnail', 'preview', 'crop', 'hdr',
                       'pano', 'burst', 'timer', 'portrait', 'night'}:
                continue
            return tag
    return None


def scan_source_files(config: AppConfig, progress_callback=None) -> list[MediaFile]:
    media_files: list[MediaFile] = []
    all_paths: list[str] = []
    for source_dir in config.source_dirs:
        root = Path(source_dir)
        if not root.exists():
            logger.warning(f"源目录不存在: {source_dir}")
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            for fname in filenames:
                ext = Path(fname).suffix.lower()
                if ext in config.media_extensions:
                    all_paths.append(os.path.join(dirpath, fname))

    total = len(all_paths)
    logger.info(f"找到 {total} 个媒体文件")
    logger.info(f"时间戳优先级: {config.timestamp_priority}")

    def process_one(filepath: str) -> MediaFile:
        fname = os.path.basename(filepath)
        ts, ts_source = get_file_timestamp(filepath, fname, config)
        tag = _extract_tag(fname, config.tag_patterns)
        ext = Path(filepath).suffix.lower()
        is_video = ext in config.video_extensions
        return MediaFile(path=filepath, filename=fname, timestamp=ts,
                         timestamp_source=ts_source, file_tag=tag, is_video=is_video)

    done = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process_one, p): p for p in all_paths}
        for future in as_completed(futures):
            try:
                mf = future.result()
                media_files.append(mf)
            except Exception as e:
                logger.error(f"处理文件失败 {futures[future]}: {e}")
            done += 1
            if progress_callback and done % 500 == 0:
                progress_callback(done, total)

    if progress_callback:
        progress_callback(total, total)

    media_files.sort(key=lambda f: f.timestamp or datetime.max)

    source_counts: dict[str, int] = {}
    for f in media_files:
        src = f.timestamp_source or "(无)"
        source_counts[src] = source_counts.get(src, 0) + 1
    logger.info(f"扫描完成: {len(media_files)} 个有效文件")
    logger.info(f"时间戳来源分布: {source_counts}")
    return media_files


def group_by_time(files: list[MediaFile], gap_seconds: float = 10.0,
                  large_threshold: int = 20) -> list[MediaGroup]:
    if not files:
        return []
    groups: list[MediaGroup] = []
    current_files = [files[0]]

    for f in files[1:]:
        prev = current_files[-1]
        if prev.timestamp and f.timestamp:
            delta = (f.timestamp - prev.timestamp).total_seconds()
            if delta <= gap_seconds:
                current_files.append(f)
                continue
        if not f.timestamp:
            if current_files:
                groups.append(_make_group(current_files, large_threshold))
            current_files = [f]
            continue
        groups.append(_make_group(current_files, large_threshold))
        current_files = [f]

    if current_files:
        groups.append(_make_group(current_files, large_threshold))

    logger.info(f"分组完成: {len(groups)} 个组")
    sizes = [g.file_count for g in groups]
    if sizes:
        avg = sum(sizes) / len(sizes)
        logger.info(f"  平均每组 {avg:.1f} 个文件, 最小 {min(sizes)}, 最大 {max(sizes)}")
    return groups


def _make_group(files: list[MediaFile], large_threshold: int) -> MediaGroup:
    tags = [f.file_tag for f in files if f.file_tag]
    detected_tag = tags[0] if tags else None
    if len(set(tags)) > 1:
        logger.warning(f"组内有多个不同标注: {set(tags)}")
    timestamps = [f.timestamp for f in files if f.timestamp]
    group = MediaGroup(
        files=files,
        time_start=min(timestamps) if timestamps else None,
        time_end=max(timestamps) if timestamps else None,
        file_count=len(files), detected_tag=detected_tag, status="pending")
    if len(files) > large_threshold:
        logger.warning(f"超大组: {len(files)} 个文件 ({group.time_span_str})")
    return group
