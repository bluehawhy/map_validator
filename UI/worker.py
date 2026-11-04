"""Background WGC capture and saved-photo review for four manual stages.

Never moves, activates, restores or resizes HD_3D Tool or NLadybugSv.
The user aims each stage before clicking its capture button.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from map_validator.app_logging import log_exception_at_source
from map_validator.com_threading import sta_com_apartment
from map_validator.stage_types import STAGES, STAGE_LABELS, validate_case_id
from map_validator.windows import capture_window, find_window

APP_LOG = logging.getLogger("map_validator.ui.worker")


class ControlWorker(QThread):
    progress = pyqtSignal(str)
    case_id_ready = pyqtSignal(str)
    result_ready = pyqtSignal(dict)
    hide_panel = pyqtSignal()
    show_panel = pyqtSignal()

    def __init__(
        self, config: dict, config_dir: Path, case_id: str,
        action: str, movement: str = "none", steps: int = 0, parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.config_dir = config_dir
        self.case_id = case_id
        self.action = action
        self._stop = threading.Event()

    def _progress(self, message: str) -> None:
        self.progress.emit(message)
        APP_LOG.info(message, stacklevel=2)

    def request_stop(self) -> None:
        self._stop.set()

    def acknowledge_hidden(self) -> None:
        """Compatibility for old UI signal wiring; no panel hiding is needed."""
        pass

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise InterruptedError("사용자가 작업 중지를 요청했습니다.")

    def _path(self, name: str) -> Path:
        path = Path(name).expanduser()
        return path if path.is_absolute() else self.config_dir / path

    def _resolve_case_id(self) -> str:
        if not self.case_id.strip():
            self._progress("검수 ID 확인 중")
            from map_validator.windows import read_selected_intersection_id

            title = self.config.get("windows", {}).get(
                "intersection_review_title", ""
            ).strip()
            if not title:
                raise ValueError(
                    "검수 ID가 없습니다. 교차로 선형 검수 창을 선택하세요."
                )
            self.case_id = read_selected_intersection_id(title)
            self.case_id_ready.emit(self.case_id)
        return validate_case_id(self.case_id)

    def run(self) -> None:
        try:
            with sta_com_apartment():
                self._run_job()
        except InterruptedError as exc:
            APP_LOG.info("작업 중단: %s", exc)
            self._progress("중지됨")
        except Exception as exc:
            log_exception_at_source(APP_LOG, "작업 오류", exc)
            self._progress("오류 발생")
        finally:
            self.show_panel.emit()

    def _run_job(self) -> None:
        self._check_stop()
        case_id = self._resolve_case_id()
        folder = self._path(
            self.config.get("output", {}).get("directory", "results")
        ) / case_id
        self._check_stop()

        if self.action.startswith("capture_"):
            stage = self.action[len("capture_"):]
            if stage not in STAGES:
                raise ValueError(f"지원하지 않는 촬영 단계: {stage}")
            self._progress(
                f"{STAGE_LABELS[stage]}: 사용자 지정 시점의 두 창 WGC 촬영 중"
            )
            windows = self.config["windows"]
            roadview = find_window(windows["roadview_title"])
            work = find_window(windows["work_title"])
            # Read-only captures. The work tool never receives WM_PRINT.
            roadview_image = capture_window(
                roadview, self.config.get("capture", {}).get("region")
            )
            self._check_stop()
            work_image = capture_window(work)
            self._check_stop()
            from map_validator.staged_capture import capture_stage

            result = capture_stage(
                folder, case_id, stage,
                windows["work_title"], windows["roadview_title"],
                work_image, roadview_image,
            )
            self._progress(
                f"{STAGE_LABELS[stage]} 촬영 저장 완료 (버전 {result['revision']})"
            )
            result["kind"] = "staged_capture"
            self.result_ready.emit(result)
            return

        if self.action == "analyze_staged":
            from map_validator.staged_compare import analyze_stages

            result = analyze_stages(
                folder=folder,
                case_id=case_id,
                model_name=self.config.get("analysis", {}).get(
                    "model_name", "nvidia/segformer-b0-finetuned-ade-512-512"
                ),
                progress=self._progress,
                check_stop=self._check_stop,
                stop_line_threshold=float(
                    self.config.get("analysis", {}).get("stop_line_roadview_threshold", .68)
                ),
            )
            self.result_ready.emit(result)
            return

        raise ValueError(f"지원하지 않는 작업입니다: {self.action}")
