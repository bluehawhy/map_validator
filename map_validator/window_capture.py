"""Capture a native Windows window by HWND without stealing foreground focus.

PrintWindow asks the target program to render into an off-screen GDI bitmap.
GPU-rendered viewers may reject it or return a blank frame; fail explicitly
instead of silently capturing another application with a desktop screenshot.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

import cv2
import numpy as np

APP_LOG = logging.getLogger("map_validator.window_capture")

DIB_RGB_COLORS = 0
BI_RGB = 0
PW_RENDERFULLCONTENT = 0x00000002


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


def _capture_native_hwnd(hwnd: int, width: int, height: int, flags: int) -> np.ndarray | None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int

    desktop_dc = user32.GetDC(None)
    if not desktop_dc:
        raise OSError("Windows 데스크톱 DC를 가져오지 못했습니다.")
    memory_dc = None
    bitmap = None
    selected = None
    try:
        memory_dc = gdi32.CreateCompatibleDC(desktop_dc)
        if not memory_dc:
            raise OSError("캡처용 메모리 DC를 만들지 못했습니다.")
        bitmap = gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
        if not bitmap:
            raise OSError("캡처용 비트맵을 만들지 못했습니다.")
        selected = gdi32.SelectObject(memory_dc, bitmap)
        if not selected:
            raise OSError("캡처용 비트맵 선택 실패")

        rendered = bool(user32.PrintWindow(wintypes.HWND(hwnd), memory_dc, flags))
        gdi32.SelectObject(memory_dc, selected)
        selected = None
        if not rendered:
            return None

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # top-down, consistent with ROI coordinates
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB
        info.bmiHeader.biSizeImage = width * height * 4

        pixels = (ctypes.c_ubyte * (width * height * 4))()
        lines = gdi32.GetDIBits(
            desktop_dc,
            bitmap,
            0,
            height,
            ctypes.cast(pixels, ctypes.c_void_p),
            ctypes.byref(info),
            DIB_RGB_COLORS,
        )
        if lines != height:
            return None
        raw = np.ctypeslib.as_array(pixels).reshape(height, width, 4)
        return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR).copy()
    finally:
        if selected and memory_dc:
            gdi32.SelectObject(memory_dc, selected)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, desktop_dc)


def _blank_frame(frame: np.ndarray) -> bool:
    height, width = frame.shape[:2]
    center = frame[height // 8: height * 7 // 8, width // 8: width * 7 // 8]
    if center.size == 0:
        return True
    return bool(np.max(np.std(center, axis=(0, 1))) < 1.5)


def capture_window_background(window, region: list[int] | None = None) -> np.ndarray:
    """Capture HWND even if Chrome is on top; never activate the target window.

    Raises if the target is minimized, PrintWindow fails, or returns a likely
    blank frame. This prevents misleading screenshots and downstream analysis.
    """
    if sys.platform != "win32":
        raise RuntimeError("비활성 창 캡처는 Windows에서만 지원합니다.")

    hwnd = int(getattr(window, "_hWnd", 0) or 0)
    if not hwnd:
        raise ValueError("로드뷰 창 핸들(HWND)을 찾지 못했습니다.")
    if window.isMinimized:
        raise RuntimeError("로드뷰 창이 최소화되어 있습니다. 창을 복원·최대화해 주세요.")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise OSError("로드뷰 창 크기를 조회하지 못했습니다.")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0 or width > 16000 or height > 16000:
        raise ValueError(f"캡처할 수 없는 창 크기입니다: {width}x{height}")

    frame = None
    for flags in (PW_RENDERFULLCONTENT, 0):
        candidate = _capture_native_hwnd(hwnd, width, height, flags)
        if candidate is not None and not _blank_frame(candidate):
            frame = candidate
            break
        APP_LOG.warning(
            "PrintWindow 캡처 실패 또는 빈 화면: HWND=0x%X, flags=%d", hwnd, flags
        )
    if frame is None:
        raise RuntimeError(
            "로드뷰 창 자체 캡처 실패: PrintWindow가 빈 화면 또는 오류를 반환했습니다. "
            "NLadybugSv가 GPU 기반 백그라운드 캡처를 지원하지 않을 수 있습니다."
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
                "capture.region이 창 범위를 벗어났습니다: "
                f"region={region}, window={width}x{height}"
            )
        frame = frame[top:top + crop_height, left:left + crop_width].copy()
    APP_LOG.info("비활성 창 캡처 성공: HWND=0x%X, 크기=%dx%d", hwnd, frame.shape[1], frame.shape[0])
    return frame
