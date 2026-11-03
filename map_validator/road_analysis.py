"""Experimental local semantic segmentation for left/right side-road candidates.

A single road mask is not proof of intersection geometry. Outputs are review
candidates, NOT traffic-legal turn permissions or authoritative road presence.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass
class DirectionResult:
    left_score: float
    right_score: float
    left_candidate: bool
    right_candidate: bool
    road_area_ratio: float
    method: str = "segformer_roi_heuristic"

    def as_dict(self) -> dict:
        return {
            "left_score": round(self.left_score, 4),
            "right_score": round(self.right_score, 4),
            "left_candidate": self.left_candidate,
            "right_candidate": self.right_candidate,
            "road_area_ratio": round(self.road_area_ratio, 4),
            "method": self.method,
        }


class RoadSegmenter:
    def __init__(self, model_name: str):
        try:
            import torch
            from transformers import AutoImageProcessor, SegformerForSemanticSegmentation
        except ImportError as exc:
            raise RuntimeError(
                "AI dependencies missing: pip install -r requirements-ai.txt"
            ) from exc
        self.torch = torch
        self.processor = AutoImageProcessor.from_pretrained(model_name)
        self.model = SegformerForSemanticSegmentation.from_pretrained(model_name)
        self.model.eval()
        self.road_class_ids = [
            int(idx)
            for idx, label in self.model.config.id2label.items()
            if str(label).strip().casefold() == "road"
        ]
        if not self.road_class_ids:
            raise RuntimeError("Model has no exact 'road' class; review class mapping")

    def mask(self, bgr: np.ndarray) -> np.ndarray:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        inputs = self.processor(images=Image.fromarray(rgb), return_tensors="pt")
        with self.torch.inference_mode():
            outputs = self.model(**inputs)
        h, w = rgb.shape[:2]
        label_map = self.processor.post_process_semantic_segmentation(
            outputs, target_sizes=[(h, w)]
        )[0].cpu().numpy()
        return np.isin(label_map, self.road_class_ids).astype(np.uint8)


def analyze_road_mask(mask: np.ndarray, threshold: float = 0.19,
                      vertical_range: tuple[float, float] = (0.28, 0.60)) -> DirectionResult:
    """Estimate side road candidate from mid-distance road pixels.

    IMPORTANT: Wide main roads, parking lots, occlusion and perspective can
    cause both false positive and false negative. Human review is required.
    """
    if mask.ndim != 2:
        raise ValueError("Expected a 2D binary road mask")
    h, w = mask.shape
    if h < 64 or w < 64:
        raise ValueError("Image is too small for ROI analysis")
    y0 = int(h * vertical_range[0])
    y1 = int(h * vertical_range[1])
    if not 0 <= y0 < y1 <= h:
        raise ValueError("Invalid vertical_range")
    left = mask[y0:y1, int(w * 0.04):int(w * 0.34)]
    right = mask[y0:y1, int(w * 0.66):int(w * 0.96)]
    ls = float(np.mean(left)) if left.size else 0.0
    rs = float(np.mean(right)) if right.size else 0.0
    return DirectionResult(
        left_score=ls,
        right_score=rs,
        left_candidate=ls >= threshold,
        right_candidate=rs >= threshold,
        road_area_ratio=float(np.mean(mask)),
    )


def draw_review_overlay(bgr: np.ndarray, mask: np.ndarray, result: DirectionResult,
                        vertical_range=(0.28, 0.60)) -> np.ndarray:
    h, w = bgr.shape[:2]
    overlay = bgr.copy()
    overlay[mask.astype(bool)] = (0.58 * overlay[mask.astype(bool)] +
                                   0.42 * np.array([45, 210, 80])).astype(np.uint8)
    for name, x0, x1, score, candidate in (
        ("LEFT", 0.04, 0.34, result.left_score, result.left_candidate),
        ("RIGHT", 0.66, 0.96, result.right_score, result.right_candidate),
    ):
        p1 = (int(w * x0), int(h * vertical_range[0]))
        p2 = (int(w * x1), int(h * vertical_range[1]))
        color = (0, 165, 255) if candidate else (180, 180, 180)
        cv2.rectangle(overlay, p1, p2, color, 2)
        cv2.putText(overlay, f"{name} candidate={int(candidate)} score={score:.2f}",
                    (p1[0], max(20, p1[1] - 12)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.52, color, 2, cv2.LINE_AA)
    return overlay
