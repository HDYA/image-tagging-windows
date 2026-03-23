"""
媒体文件智能分类系统 - 三级分类调度器
"""
import logging
from typing import Optional

from .config import AppConfig
from .models import MediaGroup, ClassifyResult, CategoryNode
from .category_tree import PinyinIndex
from .database import Database

logger = logging.getLogger(__name__)


class Classifier:
    """
    三级分类调度器

    优先级:
        1. 文件名拼音标注匹配
        2. 人脸识别匹配 (可选)
        3. 标记为未分类，等待人工
    """

    def __init__(self, config: AppConfig, db: Database, pinyin_index: PinyinIndex,
                 face_engine=None):
        self.config = config
        self.db = db
        self.pinyin_index = pinyin_index
        self.face_engine = face_engine  # Optional[FaceEngine]

    def classify_group(self, group: MediaGroup) -> ClassifyResult:
        """对一个分组执行分类"""

        # 阶段 1: 拼音标注匹配
        result = self._classify_by_tag(group)
        if result.status in ("auto", "conflict"):
            return result

        # 阶段 2: 人脸识别 (如果启用)
        if self.face_engine is not None and self.config.face_enabled:
            face_result = self._classify_by_face(group)
            if face_result.status in ("auto", "confirm"):
                return face_result

        # 阶段 3: 未分类
        return ClassifyResult(status="pending", method="none")

    def classify_all(self, groups: list[MediaGroup],
                     progress_callback=None) -> dict[str, int]:
        """
        批量分类所有分组

        Returns:
            统计: {"auto": n, "conflict": n, "confirm": n, "pending": n}
        """
        stats = {"auto": 0, "conflict": 0, "confirm": 0, "pending": 0}

        for i, group in enumerate(groups):
            result = self.classify_group(group)

            # 更新分组状态
            group.classify_method = result.method
            group.confidence = result.confidence
            group.status = result.status
            group.conflict_candidates = result.candidates

            if result.category:
                group.category_id = result.category.id
                group.category_path = result.category.path

            # 写入数据库
            self.db.update_group_classification(
                group_id=group.id,
                category_id=group.category_id,
                confidence=group.confidence,
                method=group.classify_method,
                status=group.status
            )

            stats[result.status] = stats.get(result.status, 0) + 1

            if progress_callback and (i + 1) % 100 == 0:
                progress_callback(i + 1, len(groups))

        if progress_callback:
            progress_callback(len(groups), len(groups))

        logger.info(f"分类完成: {stats}")
        return stats

    def _classify_by_tag(self, group: MediaGroup) -> ClassifyResult:
        """拼音标注匹配"""
        if not group.detected_tag:
            return ClassifyResult(status="no_tag", method="pinyin")

        tag = group.detected_tag

        # 精确匹配
        candidates, is_conflict = self.pinyin_index.lookup(tag)

        if len(candidates) == 1 and not is_conflict:
            return ClassifyResult(
                category=candidates[0],
                confidence=0.95,
                status="auto",
                method="pinyin_exact",
                raw_tag=tag
            )

        if is_conflict:
            return ClassifyResult(
                candidates=candidates,
                confidence=0.5,
                status="conflict",
                method="pinyin_ambiguous",
                raw_tag=tag
            )

        # 模糊匹配
        fuzzy = self.pinyin_index.fuzzy_lookup(tag, max_distance=1)
        if fuzzy:
            if len(fuzzy) == 1:
                return ClassifyResult(
                    category=fuzzy[0],
                    candidates=fuzzy,
                    confidence=0.75,
                    status="confirm",
                    method="pinyin_fuzzy",
                    raw_tag=tag
                )
            else:
                return ClassifyResult(
                    candidates=fuzzy,
                    confidence=0.5,
                    status="conflict",
                    method="pinyin_fuzzy",
                    raw_tag=tag
                )

        return ClassifyResult(
            status="pending",
            method="pinyin",
            raw_tag=tag
        )

    def _classify_by_face(self, group: MediaGroup) -> ClassifyResult:
        """人脸识别匹配"""
        if self.face_engine is None:
            return ClassifyResult(status="no_face", method="face")

        image_paths = [f.path for f in group.files]

        result = self.face_engine.classify_images(
            image_paths,
            threshold=self.config.face_threshold,
            confirm_threshold=self.config.face_confirm_threshold
        )

        if result is None:
            return ClassifyResult(status="no_face", method="face")

        cat_id, score, status = result
        cat = self.db.get_category_by_id(cat_id)
        if cat is None:
            return ClassifyResult(status="no_face", method="face")

        return ClassifyResult(
            category=cat,
            confidence=score,
            status=status,
            method="face"
        )
