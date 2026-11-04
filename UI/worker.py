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
from map_validator.app_logging import log_exception_at_source
from map_validator.com_threading import sta_com_apartment
from map_validator.capture_naming import capture_file_name

import logging

APP_LOG = logging.getLogger("map_validator.ui.worker")

from map_validator.road_analysis import (
    RoadSegmenter,
    analyze_road_mask,
    draw_review_overlay,
)
from map_validator.windows import (
    capture_window,
    find_window,
    move_roadview,
    scroll_to_bottom,
)


class ControlWorker(QThread):
    progress = pyqtSignal(str)
    case_id_ready = pyqtSignal(str)
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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.config_dir = config_dir
        self.case_id = case_id
        self.action = action  # capture | analyze
        self.movement = movement
        self.steps = steps
        self._stop = threading.Event()
        self._hidden = threading.Event()

    def _progress(self, description: str) -> None:
        self.progress.emit(description)
        APP_LOG.info(description, stacklevel=2)

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

    def run(self) -> None:
        try:
            with sta_com_apartment():
                self._run_job()
        except Exception as exc:
            log_exception_at_source(APP_LOG, "작업 스레드 초기화 실패", exc)
            self._progress("오류 발생")
            self.show_panel.emit()

    def _run_job(self) -> None:
        try:
            if not self.case_id.strip():
                # UIA/Win32 inspection is always performed on the worker
                # thread; an empty capture ID must never block the GUI.
                self._progress("선택 교차로 검수 ID 확인 중")
                self._check_stop()
                from map_validator.windows import read_selected_intersection_id

                review_title = self.config.get("windows", {}).get(
                    "intersection_review_title", ""
                ).strip()
                if not review_title:
                    raise ValueError("config.yaml에 입력 교차로 타이틀을 설정하세요.")
                try:
                    self.case_id = read_selected_intersection_id(review_title)
                except Exception as exc:
                    raise RuntimeError(
                        "검수 ID를 읽지 못했습니다. 교차로 선형 검수에서 "
                        "Polygon 또는 Link를 선택한 뒤 다시 시도하세요."
                    ) from exc
                self._check_stop()
                self.case_id_ready.emit(self.case_id)
                APP_LOG.info("선택 교차로 검수 ID: %s", self.case_id)

            if not re.fullmatch(r"[A-Za-z0-9 _-]+", self.case_id):
                raise ValueError("작업 ID는 영문/숫자/공백/-/_만 사용할 수 있습니다.")
            if self.action not in {"capture", "analyze"}:
                raise ValueError("지원하지 않는 작업입니다.")
            if self.movement not in {"none", "forward", "backward"}:
                raise ValueError("지원하지 않는 로드뷰 이동입니다.")
            self._check_stop()

            if self.action == "analyze":
                # Only read previously captured photos. Never launch WGC,
                # activate work apps, scroll the roadview, or take new images.
                from map_validator.saved_analysis import analyze_saved_images

                folder = (
                    self._path(self.config.get("output", {}).get("directory", "results"))
                    / self.case_id
                )
                result = analyze_saved_images(
                    output=folder,
                    case_id=self.case_id,
                    roadview_title=self.config["windows"]["roadview_title"],
                    work_title=self.config["windows"]["work_title"],
                    analysis_settings=self.config.get("analysis", {}),
                    progress=self._progress,
                    check_stop=self._check_stop,
                )
                self.result_ready.emit(result)
                return

            if self.action == "capture":
                # Snapshot is strictly read-only: no opening the view, zoom,
                # scroll, W/S input, foreground activation, or geometry change.
                self._progress("순수 스크린샷: 두 창을 현재 상태 그대로 캡처")
                roadview = find_window(self.config["windows"]["roadview_title"])
            else:
                prep = self.config.get("preparation", {})
                self._progress("분석 화면 준비 중 (입력도구 Zoom 조작 없음)")
                roadview = find_window(self.config["windows"]["roadview_title"])
                if bool(prep.get("roadview_scroll_to_bottom", True)):
                    self._hide_before_desktop_action()
                    try:
                        scroll_to_bottom(roadview)
                        APP_LOG.info("로드뷰를 맨 아래로 이동했습니다.")
                    finally:
                        self.show_panel.emit()

            work = find_window(self.config["windows"]["work_title"])
            cap = self.config.get("capture", {})
            movement_cfg = self.config["movement"]
            max_steps = int(movement_cfg.get("max_steps", 5))
            if not (0 <= self.steps <= max_steps):
                raise ValueError(f"이동 횟수는 0~{max_steps}여야 합니다.")
            # '캡처만' never performs movement, regardless of UI selection.
            count = 0 if self.action == "capture" else (
                self.steps if self.movement != "none" else 0
            )
            output = self._path(self.config.get("output", {}).get("directory", "results")) / self.case_id
            output.mkdir(parents=True, exist_ok=True)
            ai_cfg = self.config.get("analysis", {})
            segmenter = None
            if self.action == "analyze":
                self._progress("AI 모델 준비 중")
                APP_LOG.info("AI 모델 최초 실행은 다운로드가 필요할 수 있습니다.")
                segmenter = RoadSegmenter(
                    ai_cfg.get("model_name", "nvidia/segformer-b0-finetuned-ade-512-512")
                )
            frames = []
            for idx in range(count + 1):
                self._check_stop()
                self._progress(f"로드뷰 캡처 {idx + 1}/{count + 1}")
                if idx > 0:
                    # W/S input still needs the foreground window. Only the
                    # screenshot itself is fully non-activating.
                    self._hide_before_desktop_action()
                    try:
                        key = (movement_cfg["forward_key"] if self.movement == "forward"
                               else movement_cfg["backward_key"])
                        move_roadview(
                            roadview, key, float(movement_cfg.get("hold_seconds", 0.5))
                        )
                        time.sleep(float(cap.get("settle_seconds", 1.5)))
                    finally:
                        self.show_panel.emit()
                frame = capture_window(roadview, cap.get("region"))
                roadview_name = capture_file_name(
                    self.case_id, self.config["windows"]["roadview_title"],
                    idx, count + 1,
                )
                roadview_path = output / roadview_name
                if not cv2.imwrite(str(roadview_path), frame):
                    raise RuntimeError(f"로드뷰 스크린샷 저장 실패: {roadview_path}")

                # Both windows use the same non-activating WGC backend.
                work_frame = capture_window(work)
                work_name = capture_file_name(
                    self.case_id, self.config["windows"]["work_title"],
                    idx, count + 1,
                )
                work_path = output / work_name
                if not cv2.imwrite(str(work_path), work_frame):
                    raise RuntimeError(f"입력도구 스크린샷 저장 실패: {work_path}")

                entry = {
                    "frame": idx,
                    "image": roadview_path.name,
                    "roadview_image": roadview_path.name,
                    "work_image": work_path.name,
                    "left_candidate": None,
                    "right_candidate": None,
                }
                if segmenter is not None:
                    self._progress(f"AI 분석 {idx + 1}/{count + 1}")
                    self._check_stop()
                    mask = segmenter.mask(frame)
                    vertical_range = tuple(ai_cfg.get("vertical_range", [0.28, 0.60]))
                    direction = analyze_road_mask(
                        mask,
                        float(ai_cfg.get("side_road_score_threshold", 0.19)),
                        vertical_range,
                    )
                    overlay = draw_review_overlay(frame, mask, direction, vertical_range)
                    overlay_path = output / roadview_name.replace(".png", "_overlay.png")
                    if not cv2.imwrite(str(overlay_path), overlay):
                        raise RuntimeError(f"분석 이미지 저장 실패: {overlay_path}")
                    entry.update(direction.as_dict())
                    entry["overlay"] = overlay_path.name
                frames.append(entry)
                APP_LOG.info(
                    "%d번째 화면 저장: %s, %s",
                    idx + 1, roadview_path.name, work_path.name,
                )

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
            self._progress("검수 자료 저장 완료")
            self.result_ready.emit({
                "left": report["left_road"],
                "right": report["right_road"],
                "folder": str(output),
                "frames": len(frames),
            })
        except InterruptedError as exc:
            APP_LOG.warning("작업 중단: %s", exc)
            self._progress("중지됨")
        except Exception as exc:
            log_exception_at_source(APP_LOG, "작업 오류", exc)
            self._progress("오류 발생")
        finally:
            self.show_panel.emit()
