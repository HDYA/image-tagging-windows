"""
媒体文件智能分类系统 - 导出模块

导出粒度: 以文件为单位
每个文件的最终分类 = 文件级覆盖 > 组级分类

支持: JSON / CSV / PowerShell / Batch
"""
import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .database import Database

logger = logging.getLogger(__name__)


class Exporter:
    def __init__(self, db: Database, archive_root: str):
        self.db = db
        self.archive_root = archive_root

    def _build_target_path(self, category_path: str, filename: str) -> str:
        if not self.archive_root or not category_path:
            return ""
        return os.path.join(self.archive_root, category_path, filename)

    def _get_export_rows(self) -> list[dict]:
        return self.db.get_export_data()

    def export_json(self, output_path: str) -> int:
        rows = self._get_export_rows()
        files_out = []
        for row in rows:
            cat = row['effective_category'] or ''
            target = self._build_target_path(cat, row['filename'])
            files_out.append({
                'file_id': row['file_id'], 'group_id': row['group_id'],
                'source': row['file_path'], 'target': target,
                'filename': row['filename'], 'category': cat,
                'method': row['effective_method'],
                'confidence': row['effective_confidence'],
                'is_override': row['file_category_id'] is not None,
                'timestamp': row['timestamp'] or ''})
        export_data = {
            'export_time': datetime.now().isoformat(),
            'archive_root': self.archive_root,
            'total_files': len(files_out),
            'override_count': sum(1 for f in files_out if f['is_override']),
            'files': files_out}
        Path(output_path).write_text(
            json.dumps(export_data, ensure_ascii=False, indent=2), encoding='utf-8')
        logger.info(f"导出 JSON: {len(files_out)} 个文件")
        return len(files_out)

    def export_csv(self, output_path: str) -> int:
        rows = self._get_export_rows()
        with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['file_id', 'group_id', 'category', 'source_path',
                             'target_path', 'filename', 'method', 'confidence',
                             'is_override', 'timestamp'])
            for row in rows:
                cat = row['effective_category'] or ''
                target = self._build_target_path(cat, row['filename'])
                writer.writerow([
                    row['file_id'], row['group_id'], cat, row['file_path'],
                    target, row['filename'], row['effective_method'],
                    f"{row['effective_confidence']:.2f}",
                    'Y' if row['file_category_id'] is not None else '',
                    row['timestamp'] or ''])
        logger.info(f"导出 CSV: {len(rows)} 行")
        return len(rows)

    def export_powershell(self, output_path: str, move: bool = False) -> int:
        rows = self._get_export_rows()
        op = "Move-Item" if move else "Copy-Item"
        op_name = "移动" if move else "复制"
        lines = [
            '# 媒体文件归档脚本 (PowerShell)',
            f'# 生成时间: {datetime.now().isoformat()}',
            f'# 操作: {op_name}文件, 文件总数: {len(rows)}',
            '', '$dryRun = $true', '$successCount = 0', '$errorCount = 0', '']
        for row in rows:
            cat = row['effective_category'] or ''
            target = self._build_target_path(cat, row['filename'])
            if not target:
                continue
            source = row['file_path'].replace('/', '\\')
            target = target.replace('/', '\\')
            target_dir = os.path.dirname(target).replace('/', '\\')
            override_mark = " [覆盖]" if row['file_category_id'] is not None else ""
            lines.extend([
                f'# 文件 {row["file_id"]} | 组 {row["group_id"]} | '
                f'{row["effective_method"]} | {row["effective_confidence"]:.0%}{override_mark}',
                f'$src = "{source}"', f'$dst = "{target}"', f'$dstDir = "{target_dir}"',
                'if ($dryRun) { Write-Host "[DRY] $src -> $dst" }',
                'else { try { if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Path $dstDir -Force | Out-Null }',
                f'    {op} -Path $src -Destination $dst -Force; $successCount++',
                '} catch { Write-Warning "失败: $src -> $_"; $errorCount++ } }', ''])
        lines.extend([
            'if (-not $dryRun) {',
            f'    Write-Host "`n完成: $successCount 个文件{op_name}成功, $errorCount 个失败"',
            '} else {', f'    Write-Host "`n[DRY RUN] 共 {len(rows)} 个文件待{op_name}"', '}'])
        Path(output_path).write_text('\n'.join(lines), encoding='utf-8-sig')
        logger.info(f"导出 PowerShell: {len(rows)} 个操作")
        return len(rows)

    def export_batch(self, output_path: str, move: bool = False) -> int:
        rows = self._get_export_rows()
        op = "move" if move else "copy"
        op_name = "移动" if move else "复制"
        lines = ['@echo off', 'chcp 65001 >nul',
                 f'REM 媒体文件归档脚本 - {op_name}, 总数: {len(rows)}',
                 '', 'set "DRYRUN=1"', 'set /a SUCCESS=0', 'set /a ERRORS=0', '']
        for row in rows:
            cat = row['effective_category'] or ''
            target = self._build_target_path(cat, row['filename'])
            if not target:
                continue
            source = row['file_path'].replace('/', '\\')
            target = target.replace('/', '\\')
            target_dir = os.path.dirname(target).replace('/', '\\')
            lines.extend([
                f'REM 文件 {row["file_id"]} 组 {row["group_id"]}',
                f'if "%DRYRUN%"=="1" ( echo [DRY] {source} -^> {target} ) else (',
                f'    if not exist "{target_dir}" mkdir "{target_dir}"',
                f'    {op} "{source}" "{target}"',
                f'    if errorlevel 1 (set /a ERRORS+=1) else (set /a SUCCESS+=1)', ')', ''])
        lines.extend([
            'if "%DRYRUN%"=="1" (',
            f'    echo [DRY RUN] 共 {len(rows)} 个文件待{op_name}',
            f') else ( echo 完成: %SUCCESS% 个文件{op_name}成功, %ERRORS% 个失败 )',
            'pause'])
        Path(output_path).write_text('\n'.join(lines), encoding='utf-8-sig')
        logger.info(f"导出 Batch: {len(rows)} 个操作")
        return len(rows)
