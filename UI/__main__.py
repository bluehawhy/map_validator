"""Launch the Qt control panel with an explicit main-thread COM apartment.

Windows GUI event loops use STA. Set the mode *before* importing PyQt6 or
pywinauto so pywinauto won't try MTA and then fall back to STA.
"""
import sys

if sys.platform == "win32":
    sys.coinit_flags = 2  # COINIT_APARTMENTTHREADED (STA)

from .app import main


if __name__ == "__main__":
    raise SystemExit(main())
