"""
媒体文件智能分类系统 - 配置模块
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json


# 所有支持的时间戳来源标识
# 排序时按此列表中的顺序依次尝试，取第一个成功的
VALID_TIMESTAMP_SOURCES = [
    "exif",          # EXIF DateTimeOriginal / DateTime (仅图片)
    "mtime",         # 文件最后修改时间 (os.stat st_mtime)
    "ctime",         # 文件创建时间 (Windows: 创建时间; Linux: inode change time)
    "filename",      # 从文件名中解析时间戳 (如 IMG_20240315_143022)
]


@dataclass
class AppConfig:
    """应用全局配置"""

    # 源文件目录（待分类）
    source_dirs: list[str] = field(default_factory=list)

    # 存档根目录（已有分类结构）
    archive_root: str = ""

    # 手工输入的类别列表文件路径（离线模式）
    manual_category_file: str = ""

    # 分组时间阈值（秒）
    group_gap_seconds: float = 10.0

    # 超大组告警阈值
    large_group_threshold: int = 20

    # ---- 时间戳排序优先级 ----
    # 有序列表，按顺序依次尝试，取第一个成功获取到的时间戳
    # 可选值: "exif", "mtime", "ctime", "filename"
    # 默认: EXIF → 文件修改时间 → 文件创建时间 → 文件名解析
    timestamp_priority: list[str] = field(default_factory=lambda: [
        "exif", "mtime", "ctime", "filename"
    ])

    # 文件名时间戳解析模式 (正则表达式列表, 按顺序尝试)
    # 每个正则必须包含命名组: year, month, day, hour, minute, second
    # 或直接一个组捕获 YYYYMMDDHHmmss / YYYYMMDD_HHmmss 格式的连续数字串
    filename_time_patterns: list[str] = field(default_factory=lambda: [
        # IMG_20240315_143022_xxx.jpg  /  VID_20240315_143022.mp4
        r'(?P<year>20\d{2})(?P<month>[01]\d)(?P<day>[0-3]\d)[_\-]?(?P<hour>[0-2]\d)(?P<minute>[0-5]\d)(?P<second>[0-5]\d)',
        # 2024-03-15_14-30-22.jpg
        r'(?P<year>20\d{2})[_\-](?P<month>[01]\d)[_\-](?P<day>[0-3]\d)[_\-](?P<hour>[0-2]\d)[_\-](?P<minute>[0-5]\d)[_\-](?P<second>[0-5]\d)',
        # mmexport1710489022123.jpg (毫秒时间戳)
        r'(?:mmexport|wx_camera_)(?P<unix_ms>\d{13})',
        # Screenshot_1710489022.png (秒时间戳)
        r'(?:Screenshot|screen)[_\-](?P<unix_s>\d{10})',
    ])

    # 是否启用人脸模块
    face_enabled: bool = False

    # 人脸推理后端: "directml" | "rocm" | "cpu"
    face_backend: str = "directml"

    # 人脸匹配阈值
    face_threshold: float = 0.45
    face_confirm_threshold: float = 0.55

    # 人脸库：从存档每个类别最多采样多少张
    face_sample_per_category: int = 20

    # 数据库路径
    db_path: str = "classifier.db"

    # 自动保存间隔 (秒)，0 = 禁用自动保存 (仅手动 Ctrl+S 和关闭时保存)
    auto_save_interval: float = 60.0

    # 文件名标注提取正则（可自定义）
    tag_patterns: list[str] = field(default_factory=lambda: [
        r'[_\-]([a-zA-Z]{2,})(?:\.\w+)?$',       # 尾部下划线/横杠后跟字母
        r'[_\-]([a-zA-Z]{2,})[_\-]\d+(?:\.\w+)?$' # 字母段在数字之前
    ])

    # 支持的媒体扩展名
    image_extensions: set[str] = field(default_factory=lambda: {
        '.jpg', '.jpeg', '.png', '.heic', '.heif',
        '.webp', '.bmp', '.tiff', '.tif', '.raw',
        '.cr2', '.nef', '.arw', '.dng', '.raf'
    })

    video_extensions: set[str] = field(default_factory=lambda: {
        '.mp4', '.mov', '.avi', '.mkv', '.wmv',
        '.flv', '.m4v', '.3gp', '.webm'
    })

    @property
    def media_extensions(self) -> set[str]:
        return self.image_extensions | self.video_extensions

    def validate(self) -> list[str]:
        """校验配置合法性，返回错误信息列表（空=合法）"""
        errors = []
        if not self.timestamp_priority:
            errors.append("timestamp_priority 不能为空")
        for src in self.timestamp_priority:
            if src not in VALID_TIMESTAMP_SOURCES:
                errors.append(
                    f"timestamp_priority 包含无效来源 '{src}'，"
                    f"可选: {VALID_TIMESTAMP_SOURCES}")
        if self.group_gap_seconds <= 0:
            errors.append("group_gap_seconds 必须 > 0")
        if self.face_threshold < 0 or self.face_threshold > 1:
            errors.append("face_threshold 必须在 0~1 之间")
        return errors

    def save(self, path: str):
        data = {
            'source_dirs': self.source_dirs,
            'archive_root': self.archive_root,
            'manual_category_file': self.manual_category_file,
            'group_gap_seconds': self.group_gap_seconds,
            'large_group_threshold': self.large_group_threshold,
            'timestamp_priority': self.timestamp_priority,
            'filename_time_patterns': self.filename_time_patterns,
            'face_enabled': self.face_enabled,
            'face_backend': self.face_backend,
            'face_threshold': self.face_threshold,
            'face_confirm_threshold': self.face_confirm_threshold,
            'face_sample_per_category': self.face_sample_per_category,
            'db_path': self.db_path,
            'auto_save_interval': self.auto_save_interval,
            'tag_patterns': self.tag_patterns,
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    @classmethod
    def load(cls, path: str) -> 'AppConfig':
        text = Path(path).read_text(encoding='utf-8')
        data = json.loads(text)
        cfg = cls()
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        # 确保 set 类型字段正确还原 (JSON 中为 list)
        if isinstance(cfg.image_extensions, list):
            cfg.image_extensions = set(cfg.image_extensions)
        if isinstance(cfg.video_extensions, list):
            cfg.video_extensions = set(cfg.video_extensions)
        errors = cfg.validate()
        if errors:
            raise ValueError(f"配置校验失败: {'; '.join(errors)}")
        return cfg
