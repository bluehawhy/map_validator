"""Shared non-activating WGC capture for HD_3D Tool and NLadybugSv.

Never use PrintWindow or change a target window's position, size, visibility,
focus, or zoom. PrintWindow was observed to blank the live HD_3D Tool viewport.
"""
from __future__ import annotations

import logging
import sys
import threading
import time

import numpy as np

APP_LOG = logging.getLogger("map_validator.wgc_capture")
FRAME_TIMEOUT_SECONDS = 6.0
STOP_TIMEOUT_SECONDS = 2.0


def capture_window_wgc(
    window, region: list[int] | None = None,
) -> np.ndarray:
    """Read a native window's BGR pixels by HWND, optionally crop a window ROI.

    Never activate, move, restore, resize, or send WM_PRINT to the target.
    If a valid image cannot be obtained, fail without a capture fallback.
    """
    if sys.platform != "win32":
        raise RuntimeError("WGC 창 캡처는 Windows에서만 지원합니다.")

    hwnd = int(getattr(window, "_hWnd", 0) or 0)
    if not hwnd:
        raise RuntimeError("대상 창 핸들(HWND)을 찾지 못했습니다.")
    if window.isMinimized:
        raise RuntimeError(
            "대상 창이 최소화되어 있습니다. 자동 복원하지 않으므로 "
            "직접 창을 복원한 후 캡처하세요."
        )

    try:
        from windows_capture import WindowsCapture
    except ImportError as exc:
        raise RuntimeError(
            "WGC 캡처용 windows-capture 라이브러리가 없습니다. "
            "'python -m pip install -r requirements-ui.txt' 실행 후 다시 시도하세요."
        ) from exc

    received = threading.Event()
    state: dict[str, object] = {}
    capture = WindowsCapture(
        window_hwnd=hwnd,
        cursor_capture=False,
        draw_border=False,
    )

    @capture.event
    def on_frame_arrived(frame, capture_control) -> None:
        try:
            # The library's BGRA buffer is owned by the native frame; copy
            # before returning from this callback so it remains valid.
            pixels = frame.frame_buffer
            if pixels.ndim != 3 or pixels.shape[2] < 3:
                raise ValueError("WGC 프레임의 채널 수가 올바르지 않습니다.")
            state["image"] = np.ascontiguousarray(pixels[:, :, :3]).copy()
        except Exception as exc:
            state["error"] = exc
        finally:
            capture_control.stop()
            received.set()

    @capture.event
    def on_closed() -> None:
        received.set()

    controller = None
    try:
        controller = capture.start_free_threaded()
        if not received.wait(FRAME_TIMEOUT_SECONDS):
            raise TimeoutError(
                "창의 WGC 첫 프레임 수신 시간이 초과되었습니다. "
                "창이 최소화되어 있거나 캡처가 제한될 수 있습니다."
            )
    finally:
        if controller is not None:
            controller.stop()
            deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
            while not controller.is_finished() and time.monotonic() < deadline:
                time.sleep(0.02)
            if controller.is_finished():
                # Propagate errors from the native capture thread.
                controller.wait()
            else:
                APP_LOG.warning("WGC 캡처 스레드 종료 지연")

    if "error" in state:
        raise RuntimeError("WGC 프레임 변환 실패") from state["error"]
    image = state.get("image")
    if not isinstance(image, np.ndarray):
        raise RuntimeError(
            "WGC 창 캡처에서 유효한 프레임을 받지 못했습니다. "
            "PrintWindow로 재시도하지 않습니다."
        )
    if image.size == 0:
        raise RuntimeError("WGC 캡처 이미지가 비어 있습니다.")

    height, width = image.shape[:2]
    center = image[height // 8: height * 7 // 8, width // 8: width * 7 // 8]
    if center.size == 0 or float(np.max(np.std(center, axis=(0, 1)))) < 1.5:
        raise RuntimeError(
            "WGC 캡처 결과가 단색(흰색/검은색)입니다. "
            "실제 프로그램 화면을 확인해 주세요."
        )

    if region is not None:
        if len(region) != 4:
            raise ValueError("capture.region must be [left, top, width, height]")
        left, top, crop_width, crop_height = (int(value) for value in region)
        if (
            left < 0 or top < 0 or crop_width <= 0 or crop_height <= 0
            or left + crop_width > width or top + crop_height > height
        ):
            raise ValueError(
                "capture.region이 WGC 창 범위를 벗어났습니다: "
                f"region={region}, window={width}x{height}"
            )
        image = image[top:top + crop_height, left:left + crop_width].copy()
    APP_LOG.info(
        "WGC 비활성 창 캡처 성공: HWND=0x%X, 크기=%dx%d",
        hwnd, image.shape[1], image.shape[0],
    )
    return image
