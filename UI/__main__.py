"""Launch the control panel with an explicit STA COM apartment and app logs."""
import sys

if sys.platform == "win32":
    sys.coinit_flags = 2  # COINIT_APARTMENTTHREADED (STA)

# Configure logging (including Python warnings) before importing Qt/pywinauto.
from map_validator.app_logging import configure_app_logging, log_exception_at_source

APP_LOG = configure_app_logging()

from .app import main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log_exception_at_source(APP_LOG, "UI 실행 실패", exc)
        raise
