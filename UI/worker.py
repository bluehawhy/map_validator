"""Background Windows automation and roadview capture for the control panel.

This module deliberately never writes back into the work application.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
from PyQt6.QtCore import QThread, pyqtSignal

from map_validator.road_analysis import (
    RoadSegmenter,
    analyze_road_mask,
    draw_review_overlay,
)
from map_validator.windows import (
    capture_window,
    click_template_in_window,
    find_window,
    move_roadview,
)


class ControlWorker(QThread):
    message = pyqtSignal(str)
    progress = pyqtSignal(str)
    result_ready = pyqtSignal(dict)
    hide_panel = pyqtSignal()
    show_panel = pyqtSignal()

    def __init__(
        self,
        config: dict,
        config_dir: Path,
        case_id: str,
        action: str,
        movement: str,
        steps: int,
        open_first: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.config_dir = config_dir
        self.case_id = case_id
        self.action = action  # open | capture | analyze
        self.movement = movement
        self.steps = steps
        self.open_first = open_first
        self._stop = threading.Event()
        self._hidden = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def acknowledge_hidden(self) -> None:
        self._hidden.set()

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise InterruptedError("사용자가 작업 중지를 요청했습니다.")

    def _hide_before_desktop_action(self) -> None:
        """Qt owns the panel; wait for UI thread to hide it before screen capture."""
        self._check_stop()
        self._hidden.clear()
        self.hide_panel.emit()
        if not self._hidden.wait(timeout=6):
            raise RuntimeError("UI 숨김 확인 실패: 안전을 위해 PC 조작을 중지합니다.")
        time.sleep(0.2)
        self._check_stop()

    def _path(self, name: str) -> Path:
        p = Path(name)
        return p if p.is_absolute() else self.config_dir / p

    def _open_roadview(self) -> None:
        self.progress.emit("업무 프로그램에서 로드뷰 열기")
        work = find_window(self.config["windows"]["work_title"])
        template_path = self._path(self.config["windows"]["open_button_image"])
        self._hide_before_desktop_action()
        try:
            if not click_template_in_window(work, str(template_path)):
                raise RuntimeError("로드뷰 버튼 이미지가 발견되지 않아 클릭하지 않았습니다.")
        finally:
            self.show_panel.emit()
        self.message.emit("로드뷰 버튼 클릭 완료")
        time.sleep(float(self.config.get("capture", {}).get("settle_seconds", 1.5)))

    def run(self) -> None:
        try:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", self.case_id):
                raise ValueError("작업 ID는 영문/숫자/-/_만 사용할 수 있습니다.")
            if self.action not in {"open", "capture", "analyze"}:
                raise ValueError("지원하지 않는 작업입니다.")
            if self.movement not in {"none", "forward", "backward"}:
                raise ValueError("지원하지 않는 로드뷰 이동입니다.")
            if self.action == "open":
                self._open_roadview()
                self.result_ready.emit({"message": "로드뷰 버튼을 클릭했습니다."})
                return

            if self.open_first:
                self._open_roadview()
            self._check_stop()
            roadview = find_window(self.config["windows"]["roadview_title"])

            cap = self.config.get("capture", {})
            movement_cfg = self.config["movement"]
            max_steps = int(movement_cfg.get("max_steps", 5))
            if not (0 <= self.steps <= max_steps):
                raise ValueError(f"이동 횟수는 0~{max_steps}여야 합니다.")
            count = self.steps if self.movement != "none" else 0
            output = self._path(self.config.get("output", {}).get("directory", "results")) / self.case_id
            output.mkdir(parents=True, exist_ok=True)
            ai_cfg = self.config.get("analysis", {})
            segmenter = None
            if self.action == "analyze":
                self.progress.emit("AI 모델 준비 중")
                self.message.emit("AI 모델 최초 실행은 다운로드가 필요할 수 있습니다.")
                segmenter = RoadSegmenter(
                    ai_cfg.get("model_name", "nvidia/segformer-b0-finetuned-ade-512-512")
                )
            frames = []
            for idx in range(count + 1):
                self._check_stop()
                self.progress.emit(f"로드뷰 캡처 {idx + 1}/{count + 1}")
                self._hide_before_desktop_action()
                try:
                    if idx > 0:
                        key = (movement_cfg["forward_key"] if self.movement == "forward"
                               else movement_cfg["backward_key"])
                        move_roadview(
                            roadview, key, float(movement_cfg.get("hold_seconds", 0.5))
                        )
                        time.sleep(float(cap.get("settle_seconds", 1.5)))
                    frame = capture_window(roadview, cap.get("region"))
                finally:
                    self.show_panel.emit()
                image_path = output / f"frame_{idx:02d}.png"
                if not cv2.imwrite(str(image_path), frame):
                    raise RuntimeError(f"스크린샷 저장 실패: {image_path}")
                entry = {
                    "frame": idx,
                    "image": image_path.name,
                    "left_candidate": None,
                    "right_candidate": None,
                }
                if segmenter is not None:
                    self.progress.emit(f"AI 분석 {idx + 1}/{count + 1}")
                    self._check_stop()
                    mask = segmenter.mask(frame)
                    vertical_range = tuple(ai_cfg.get("vertical_range", [0.28, 0.60]))
                    direction = analyze_road_mask(
                        mask,
                        float(ai_cfg.get("side_road_score_threshold", 0.19)),
                        vertical_range,
                    )
                    overlay = draw_review_overlay(frame, mask, direction, vertical_range)
                    overlay_path = output / f"frame_{idx:02d}_overlay.png"
                    if not cv2.imwrite(str(overlay_path), overlay):
                        raise RuntimeError(f"분석 이미지 저장 실패: {overlay_path}")
                    entry.update(direction.as_dict())
                    entry["overlay"] = overlay_path.name
                frames.append(entry)
                self.message.emit(f"{idx + 1}번째 화면 저장: {image_path.name}")

            def summary(direction: str) -> str:
                if segmenter is None:
                    return "not_analyzed"
                return ("possible" if any(bool(f[direction]) for f in frames)
                        else "not_detected_review_required")

            report = {
                "case_id": self.case_id,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "movement": self.movement,
                "frames": frames,
                "left_road": summary("left_candidate"),
                "right_road": summary("right_candidate"),
                "final_decision": "requires_human_review",
                "warning": (
                    "ROI road segmentation detects candidates only; "
                    "it cannot prove the presence of a turnable side road."
                ),
            }
            (output / "result.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.progress.emit("검수 자료 저장 완료")
            self.result_ready.emit({
                "left": report["left_road"],
                "right": report["right_road"],
                "folder": str(output),
                "frames": len(frames),
            })
        except InterruptedError as exc:
            self.message.emit(str(exc))
            self.progress.emit("중지됨")
        except Exception as exc:
            self.message.emit(f"오류: {exc}")
            self.progress.emit("오류 발생")
        finally:
            self.show_panel.emit()
