"""
媒体文件智能分类系统 - CLI 入口 (无 GUI 依赖)

用法:
    python cli.py scan --source "D:/DCIM" --db project.db
    python cli.py categories --archive "D:/Archive" --db project.db
    python cli.py categories --manual categories.txt --db project.db
    python cli.py classify --db project.db [--face]
    python cli.py export --db project.db --format json --output result.json
    python cli.py export --db project.db --format csv --output result.csv
    python cli.py export --db project.db --format ps --output archive.ps1 [--move]
    python cli.py stats --db project.db
"""
import argparse
import logging
import sys
from pathlib import Path

from core.config import AppConfig
from core.database import Database
from core.scanner import scan_source_files, group_by_time
from core.category_tree import scan_archive_tree, parse_manual_categories, PinyinIndex
from core.classifier import Classifier
from core.exporter import Exporter

logger = logging.getLogger(__name__)


def cmd_scan(args, config: AppConfig, db: Database):
    """扫描源文件并分组"""
    config.source_dirs = [args.source]

    def progress(done, total):
        print(f"\r  扫描中: {done}/{total}", end='', flush=True)

    print(f"扫描目录: {args.source}")
    files = scan_source_files(config, progress_callback=progress)
    print(f"\n  找到 {len(files)} 个媒体文件")

    groups = group_by_time(
        files,
        gap_seconds=config.group_gap_seconds,
        large_threshold=config.large_group_threshold
    )
    print(f"  分为 {len(groups)} 个组")

    # 存入数据库
    for group in groups:
        group.id = db.insert_group(group)
        for f in group.files:
            f.group_id = group.id
        db.insert_files_batch(group.files)

    print("  已保存到数据库")


def cmd_categories(args, config: AppConfig, db: Database):
    """加载类别"""
    if args.archive:
        config.archive_root = args.archive
        cats = scan_archive_tree(args.archive)
        print(f"从存档目录加载: {len(cats)} 个类别")
    elif args.manual:
        text = Path(args.manual).read_text(encoding='utf-8')
        cats = parse_manual_categories(text)
        print(f"从文件导入: {len(cats)} 个类别")
    else:
        print("错误: 需要 --archive 或 --manual")
        return

    for cat in cats:
        cat.id = db.upsert_category(cat)

    # 检查冲突
    index = PinyinIndex()
    index.build(cats)
    conflicts = index.conflicts
    if conflicts:
        print(f"\n⚠️  发现 {len(conflicts)} 个拼音冲突:")
        for key, conflict_cats in conflicts.items():
            paths = [c.path for c in conflict_cats]
            print(f"  '{key}' → {', '.join(paths)}")


def cmd_classify(args, config: AppConfig, db: Database):
    """自动分类"""
    cats = db.get_all_categories()
    if not cats:
        print("错误: 无类别数据，请先加载类别")
        return

    pinyin_index = PinyinIndex()
    pinyin_index.build(cats)

    face_engine = None
    if args.face:
        try:
            from core.face_engine import FaceEngine, is_face_available
            if is_face_available():
                face_engine = FaceEngine(backend=config.face_backend)
                face_engine.initialize()
                print("人脸模块已启用")

                # 加载人脸库
                face_cats = db.get_all_face_categories()
                if face_cats:
                    emb_data = {}
                    for cid in face_cats:
                        emb_data[cid] = db.get_face_embeddings_for_category(cid)
                    face_engine.load_known_faces(emb_data)
                    print(f"  加载 {len(face_cats)} 个类别的人脸特征")
                else:
                    print("  ⚠️ 无人脸库数据")
            else:
                print("人脸模块依赖不可用，跳过")
        except Exception as e:
            print(f"人脸模块初始化失败: {e}")

    config.face_enabled = face_engine is not None
    classifier = Classifier(config, db, pinyin_index, face_engine)

    # 加载所有待分类的组
    from core.models import MediaGroup
    group_rows = db.get_groups_by_status("pending", limit=999999)
    groups = []
    for row in group_rows:
        g = MediaGroup(
            id=row['id'],
            time_start=None, time_end=None,
            file_count=row['file_count'],
            detected_tag=row['detected_tag'],
            status=row['status']
        )
        g.files = db.get_files_for_group(g.id)
        groups.append(g)

    print(f"待分类: {len(groups)} 组")

    def progress(done, total):
        print(f"\r  分类中: {done}/{total}", end='', flush=True)

    stats = classifier.classify_all(groups, progress_callback=progress)
    print(f"\n\n分类结果:")
    for key, count in sorted(stats.items()):
        print(f"  {key}: {count}")


def cmd_export(args, config: AppConfig, db: Database):
    """导出结果"""
    config.archive_root = args.archive_root or config.archive_root
    exporter = Exporter(db, config.archive_root)

    fmt = args.format.lower()
    output = args.output

    if fmt == "json":
        count = exporter.export_json(output)
    elif fmt == "csv":
        count = exporter.export_csv(output)
    elif fmt in ("ps", "powershell", "ps1"):
        count = exporter.export_powershell(output, move=args.move)
    elif fmt in ("bat", "batch", "cmd"):
        count = exporter.export_batch(output, move=args.move)
    else:
        print(f"不支持的格式: {fmt}")
        return

    print(f"导出完成: {count} 个文件 → {output}")


def cmd_stats(args, config: AppConfig, db: Database):
    """显示统计"""
    counts = db.get_group_count_by_status()
    total = db.get_total_group_count()

    print(f"\n项目统计 ({config.db_path})")
    print(f"{'=' * 40}")
    print(f"  总分组数: {total}")
    for status, count in sorted(counts.items()):
        pct = count / total * 100 if total else 0
        bar = '█' * int(pct / 2) + '░' * (50 - int(pct / 2))
        print(f"  {status:12s}: {count:6d}  ({pct:5.1f}%)  {bar}")


def main():
    parser = argparse.ArgumentParser(
        description='媒体文件智能分类系统 - CLI')
    parser.add_argument('--db', default='classifier.db',
                        help='数据库路径')
    parser.add_argument('--config', help='配置文件路径')

    subparsers = parser.add_subparsers(dest='command')

    # scan
    p_scan = subparsers.add_parser('scan', help='扫描源文件')
    p_scan.add_argument('--source', required=True, help='源文件目录')

    # categories
    p_cat = subparsers.add_parser('categories', help='加载类别')
    p_cat.add_argument('--archive', help='存档根目录')
    p_cat.add_argument('--manual', help='手动类别列表文件')

    # classify
    p_cls = subparsers.add_parser('classify', help='自动分类')
    p_cls.add_argument('--face', action='store_true', help='启用人脸识别')

    # export
    p_exp = subparsers.add_parser('export', help='导出结果')
    p_exp.add_argument('--format', required=True,
                       choices=['json', 'csv', 'ps', 'bat'],
                       help='导出格式')
    p_exp.add_argument('--output', required=True, help='输出文件路径')
    p_exp.add_argument('--archive-root', help='存档根目录 (构建目标路径)')
    p_exp.add_argument('--move', action='store_true',
                       help='生成移动脚本而非复制')

    # stats
    p_stats = subparsers.add_parser('stats', help='显示统计')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    config = AppConfig()
    if args.config:
        config = AppConfig.load(args.config)
    config.db_path = args.db

    db = Database(args.db)
    db.open()

    try:
        if args.command == 'scan':
            cmd_scan(args, config, db)
        elif args.command == 'categories':
            cmd_categories(args, config, db)
        elif args.command == 'classify':
            cmd_classify(args, config, db)
        elif args.command == 'export':
            cmd_export(args, config, db)
        elif args.command == 'stats':
            cmd_stats(args, config, db)
    finally:
        db.close()


if __name__ == '__main__':
    main()
