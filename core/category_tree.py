"""
媒体文件智能分类系统 - 类别树 + 拼音索引
"""
import logging
import os
from pathlib import Path
from itertools import product
from typing import Optional

from .models import CategoryNode

logger = logging.getLogger(__name__)

try:
    from pypinyin import pinyin, Style, lazy_pinyin
    HAS_PYPINYIN = True
except ImportError:
    HAS_PYPINYIN = False
    logger.warning("pypinyin 未安装，拼音自动转换不可用")


def _chinese_to_pinyin_full(text: str) -> str:
    if not HAS_PYPINYIN:
        return ""
    return ''.join(lazy_pinyin(text))


def _chinese_to_pinyin_abbr(text: str) -> str:
    if not HAS_PYPINYIN:
        return ""
    initials = pinyin(text, style=Style.FIRST_LETTER)
    return ''.join([p[0] for p in initials])


def _chinese_to_pinyin_variants(text: str) -> list[str]:
    if not HAS_PYPINYIN:
        return []
    all_initials = pinyin(text, style=Style.FIRST_LETTER, heteronym=True)
    if not all_initials:
        return []
    combos = list(product(*all_initials))
    variants = list(set(''.join(c) for c in combos))
    full_variants = []
    all_full = pinyin(text, style=Style.NORMAL, heteronym=True)
    if all_full:
        full_combos = list(product(*all_full))
        full_variants = list(set(''.join(c) for c in full_combos))
        if len(full_variants) > 50:
            full_variants = full_variants[:50]
    return variants + full_variants


def scan_archive_tree(archive_root: str) -> list[CategoryNode]:
    root = Path(archive_root)
    if not root.exists():
        logger.error(f"存档根目录不存在: {archive_root}")
        return []
    categories: list[CategoryNode] = []
    for dirpath, dirnames, filenames in os.walk(root):
        if not dirnames:
            rel_path = os.path.relpath(dirpath, root).replace('\\', '/')
            leaf_name = os.path.basename(dirpath)
            cat = CategoryNode(
                path=rel_path, leaf_name=leaf_name,
                pinyin_full=_chinese_to_pinyin_full(leaf_name),
                pinyin_abbr=_chinese_to_pinyin_abbr(leaf_name),
                pinyin_variants=_chinese_to_pinyin_variants(leaf_name))
            categories.append(cat)
    logger.info(f"扫描存档目录: 找到 {len(categories)} 个类别")
    return categories


def parse_manual_categories(text: str) -> list[CategoryNode]:
    categories: list[CategoryNode] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        cat_path = parts[0].strip().replace('\\', '/')
        leaf_name = cat_path.rsplit('/', 1)[-1] if '/' in cat_path else cat_path
        if len(parts) >= 3:
            py_full = parts[1].strip().lower()
            py_abbr = parts[2].strip().lower()
        elif len(parts) == 2:
            py_full = parts[1].strip().lower()
            py_abbr = _chinese_to_pinyin_abbr(leaf_name)
        else:
            py_full = _chinese_to_pinyin_full(leaf_name)
            py_abbr = _chinese_to_pinyin_abbr(leaf_name)
        variants = _chinese_to_pinyin_variants(leaf_name)
        cat = CategoryNode(path=cat_path, leaf_name=leaf_name,
                           pinyin_full=py_full, pinyin_abbr=py_abbr,
                           pinyin_variants=variants)
        categories.append(cat)
    logger.info(f"解析手动类别列表: {len(categories)} 个类别")
    return categories


class PinyinIndex:
    """拼音→类别 反向索引"""

    def __init__(self):
        self._exact: dict[str, list[CategoryNode]] = {}
        self._conflicts: dict[str, list[CategoryNode]] = {}

    def build(self, categories: list[CategoryNode]):
        self._exact.clear()
        self._conflicts.clear()
        for cat in categories:
            keys = set()
            if cat.pinyin_full:
                keys.add(cat.pinyin_full)
            if cat.pinyin_abbr:
                keys.add(cat.pinyin_abbr)
            for v in cat.pinyin_variants:
                if v:
                    keys.add(v)
            for key in keys:
                if key not in self._exact:
                    self._exact[key] = []
                self._exact[key].append(cat)
        for key, cats in self._exact.items():
            if len(cats) > 1:
                self._conflicts[key] = cats
        if self._conflicts:
            logger.warning(f"发现 {len(self._conflicts)} 个拼音冲突:")
            for key, cats in self._conflicts.items():
                paths = [c.path for c in cats]
                logger.warning(f"  '{key}' -> {paths}")

    def lookup(self, tag: str) -> tuple[list[CategoryNode], bool]:
        tag = tag.lower().strip()
        candidates = self._exact.get(tag, [])
        if len(candidates) == 1:
            return candidates, False
        elif len(candidates) > 1:
            return candidates, True
        else:
            return [], False

    def fuzzy_lookup(self, tag: str, max_distance: int = 1) -> list[CategoryNode]:
        tag = tag.lower().strip()
        results = []
        seen_paths = set()
        for key, cats in self._exact.items():
            if _edit_distance(tag, key) <= max_distance:
                for c in cats:
                    if c.path not in seen_paths:
                        results.append(c)
                        seen_paths.add(c.path)
        return results

    @property
    def conflicts(self) -> dict[str, list[CategoryNode]]:
        return self._conflicts

    @property
    def total_keys(self) -> int:
        return len(self._exact)


def _edit_distance(s1: str, s2: str) -> int:
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        new_distances = [i2 + 1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                new_distances.append(distances[i1])
            else:
                new_distances.append(1 + min((distances[i1], distances[i1 + 1], new_distances[-1])))
        distances = new_distances
    return distances[-1]
