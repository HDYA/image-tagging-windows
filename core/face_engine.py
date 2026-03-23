"""
媒体文件智能分类系统 - 人脸识别引擎 (可选模块)

需要额外安装:
    pip install insightface opencv-python-headless numpy
    pip install onnxruntime-directml    # Windows AMD GPU
    pip install onnxruntime             # CPU fallback
"""
import logging
import struct
from pathlib import Path
from typing import Optional

import numpy as np

from .models import ClassifyResult, CategoryNode

logger = logging.getLogger(__name__)

_FACE_AVAILABLE = None
_insightface = None
_cv2 = None


def is_face_available() -> bool:
    global _FACE_AVAILABLE, _insightface, _cv2
    if _FACE_AVAILABLE is not None:
        return _FACE_AVAILABLE
    try:
        import insightface as _if
        import cv2 as _c
        _insightface = _if
        _cv2 = _c
        _FACE_AVAILABLE = True
        logger.info("人脸识别模块可用")
    except ImportError as e:
        _FACE_AVAILABLE = False
        logger.info(f"人脸识别模块不可用: {e}")
    return _FACE_AVAILABLE


def embedding_to_bytes(emb: np.ndarray) -> bytes:
    return emb.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


class FaceEngine:
    def __init__(self, backend: str = "directml"):
        if not is_face_available():
            raise RuntimeError("人脸识别依赖未安装")
        self.backend = backend
        self.app = None
        self._known_faces: dict[int, list[np.ndarray]] = {}

    def initialize(self, progress_callback=None):
        providers = self._get_providers()
        logger.info(f"初始化人脸引擎, 后端: {self.backend}, providers: {providers}")
        self.app = _insightface.app.FaceAnalysis(name='buffalo_l', providers=providers)
        self.app.prepare(ctx_id=0, det_size=(640, 640))
        logger.info("人脸引擎初始化完成")

    def _get_providers(self) -> list[str]:
        if self.backend == "directml":
            return ['DmlExecutionProvider', 'CPUExecutionProvider']
        elif self.backend == "rocm":
            return ['ROCMExecutionProvider', 'CPUExecutionProvider']
        else:
            return ['CPUExecutionProvider']

    def extract_faces(self, image_path: str) -> list[np.ndarray]:
        if self.app is None:
            raise RuntimeError("引擎未初始化")
        img = _cv2.imread(image_path)
        if img is None:
            return []
        try:
            faces = self.app.get(img)
            return [face.embedding for face in faces]
        except Exception as e:
            logger.error(f"人脸提取失败 {image_path}: {e}")
            return []

    def extract_video_faces(self, video_path: str, max_frames: int = 5) -> list[np.ndarray]:
        if self.app is None:
            raise RuntimeError("引擎未初始化")
        cap = _cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []
        total_frames = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return []
        step = max(1, total_frames // max_frames)
        frame_indices = list(range(0, total_frames, step))[:max_frames]
        all_embeddings = []
        for idx in frame_indices:
            cap.set(_cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            try:
                faces = self.app.get(frame)
                all_embeddings.extend([f.embedding for f in faces])
            except Exception as e:
                logger.error(f"视频帧人脸提取失败 {video_path}@{idx}: {e}")
        cap.release()
        return all_embeddings

    def load_known_faces(self, category_embeddings: dict[int, list[bytes]]):
        self._known_faces.clear()
        for cat_id, emb_list in category_embeddings.items():
            self._known_faces[cat_id] = [bytes_to_embedding(e) for e in emb_list]
        logger.info(f"加载人脸库: {len(self._known_faces)} 个类别, "
                     f"{sum(len(v) for v in self._known_faces.values())} 个特征向量")

    def match_embeddings(self, query_embeddings: list[np.ndarray],
                          threshold: float = 0.45,
                          confirm_threshold: float = 0.55) -> Optional[tuple[int, float]]:
        if not query_embeddings or not self._known_faces:
            return None
        best_cat_id = None
        best_score = 0.0
        for cat_id, known_embs in self._known_faces.items():
            for q_emb in query_embeddings:
                for k_emb in known_embs:
                    score = cosine_similarity(q_emb, k_emb)
                    if score > best_score:
                        best_score = score
                        best_cat_id = cat_id
        if best_score >= threshold and best_cat_id is not None:
            return (best_cat_id, best_score)
        return None

    def classify_images(self, image_paths: list[str],
                         threshold: float = 0.45,
                         confirm_threshold: float = 0.55) -> Optional[tuple[int, float, str]]:
        all_embeddings = []
        for p in image_paths:
            ext = Path(p).suffix.lower()
            if ext in {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.m4v', '.3gp', '.webm'}:
                all_embeddings.extend(self.extract_video_faces(p))
            else:
                all_embeddings.extend(self.extract_faces(p))
        if not all_embeddings:
            return None
        result = self.match_embeddings(all_embeddings, threshold, confirm_threshold)
        if result is None:
            return None
        cat_id, score = result
        status = "auto" if score >= confirm_threshold else "confirm"
        return (cat_id, score, status)
