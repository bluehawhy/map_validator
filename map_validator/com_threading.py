"""Windows COM apartment lifetime for worker threads.

Each QThread that uses UI Automation must initialize COM on *that thread*.
The GUI entry point's sys.coinit_flags only chooses an apartment model;
it does not initialize every subsequently created worker thread.
"""
from __future__ import annotations

import ctypes
import sys
from contextlib import contextmanager
from collections.abc import Iterator


@contextmanager
def sta_com_apartment() -> Iterator[None]:
    """Initialize/uninitialize STA on the calling Windows thread.

    CoInitializeEx returns S_OK (0) or S_FALSE (1) on success, and both
    successful calls must be paired with CoUninitialize.
    """
    if sys.platform != "win32":
        yield
        return

    ole32 = ctypes.windll.ole32
    result = ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    if result not in (0, 1):
        raise OSError(
            "STA COM 초기화 실패 (HRESULT=0x%08X)" % (result & 0xFFFFFFFF)
        )
    try:
        yield
    finally:
        ole32.CoUninitialize()
