"""
媒体文件智能分类系统 - 数据模型
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class CategoryNode:
    """分类类别节点"""
    id: int = 0
    path: str = ""                    # "家电/厨具/张小泉"
    leaf_name: str = ""               # "张小泉"
    pinyin_full: str = ""             # "zhangxiaoquan"
    pinyin_abbr: str = ""             # "zxq"
    pinyin_variants: list[str] = field(default_factory=list)  # 多音字变体
    has_face_data: bool = False

    @property
    def depth(self) -> int:
        return self.path.count('/') + 1 if self.path else 0


@dataclass
class MediaFile:
    """单个媒体文件"""
    id: int = 0
    path: str = ""                    # 完整路径
    filename: str = ""                # 文件名
    timestamp: Optional[datetime] = None
    timestamp_source: str = ""        # 时间戳来源: "exif"|"mtime"|"ctime"|"filename"|""
    file_tag: Optional[str] = None    # 从文件名提取的英文标注
    group_id: int = 0
    has_face: Optional[bool] = None
    is_video: bool = False

    # ---- 文件级分类覆盖 ----
    # 如果不为 None，则此文件的分类以此为准，忽略组级分类
    file_category_id: Optional[int] = None
    file_category_path: Optional[str] = None   # 冗余，方便显示

    @property
    def extension(self) -> str:
        return Path(self.path).suffix.lower()

    @property
    def has_override(self) -> bool:
        """此文件是否有单独的分类覆盖"""
        return self.file_category_id is not None


@dataclass
class MediaGroup:
    """媒体文件分组"""
    id: int = 0
    files: list[MediaFile] = field(default_factory=list)
    time_start: Optional[datetime] = None
    time_end: Optional[datetime] = None
    file_count: int = 0
    detected_tag: Optional[str] = None       # 组内检测到的标注
    category_id: Optional[int] = None
    category_path: Optional[str] = None      # 冗余，方便显示
    confidence: float = 0.0
    classify_method: str = ""                # "pinyin_exact"|"pinyin_fuzzy"|"face"|"manual"
    status: str = "pending"                  # "pending"|"auto"|"conflict"|"confirmed"|"skipped"
    conflict_candidates: list[CategoryNode] = field(default_factory=list)
    reviewed_at: Optional[datetime] = None

    @property
    def time_span_str(self) -> str:
        if self.time_start:
            return self.time_start.strftime("%Y-%m-%d %H:%M:%S")
        return "未知时间"


@dataclass
class ClassifyResult:
    """分类结果"""
    category: Optional[CategoryNode] = None
    candidates: list[CategoryNode] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "pending"        # "auto"|"conflict"|"no_tag"|"unknown_tag"|"no_face"|"face_no_match"
    method: str = ""               # "pinyin_exact"|"pinyin_fuzzy"|"face"|"manual"
    raw_tag: Optional[str] = None


@dataclass
class ExportEntry:
    """导出条目"""
    group_id: int = 0
    category_path: str = ""
    source_path: str = ""
    target_path: str = ""
    method: str = ""
    confidence: float = 0.0
    status: str = ""
    timestamp: str = ""
