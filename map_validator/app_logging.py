"""Structured, file-backed application logging for map_validator.

All records share: LEVEL | local timestamp | source file:line | message.
Warnings are recorded, not ignored. No live data is sent to a server.
"""
from __future__ import annotations

import logging
import sys
import traceback
import warnings
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "map_validator.log"


class AppLogFormatter(logging.Formatter):
    """Keep both GUI and disk records compact, structured, and one-line."""

    def format(self, record: logging.LogRecord) -> str:
        local_time = datetime.fromtimestamp(record.created).astimezone()
        timestamp = local_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        source = Path(record.pathname)
        try:
            source_name = source.relative_to(ROOT).as_posix()
        except ValueError:
            # Preserve useful third-party package paths when available.
            parts = source.parts
            if "site-packages" in parts:
                source_name = "/".join(parts[parts.index("site-packages") + 1:])
            else:
                source_name = source.name
        message = record.getMessage().replace("\r", " ").replace("\n", " ↵ ")
        if record.exc_info:
            details = self.formatException(record.exc_info)
            message += " | traceback: " + details.replace("\r", "").replace("\n", " ↵ ")
        return f"{record.levelname} | {timestamp} | {source_name}:{record.lineno} | {message}"


def log_exception_at_source(logger: logging.Logger, context: str, exc: BaseException) -> None:
    """Use the traceback's actual failing file and line, not the UI catch block."""
    frames = traceback.extract_tb(exc.__traceback__)
    if frames:
        frame = frames[-1]
        pathname, lineno, func = frame.filename, frame.lineno, frame.name
    else:
        pathname, lineno, func = __file__, 0, "unknown"
    record = logger.makeRecord(
        logger.name,
        logging.ERROR,
        pathname,
        lineno,
        f"{context}: {exc}",
        (),
        (type(exc), exc, exc.__traceback__),
        func=func,
    )
    logger.handle(record)


def configure_app_logging() -> logging.Logger:
    """Configure rotating local logs and standard warnings once per process."""
    logger = logging.getLogger("map_validator")
    if getattr(logger, "_map_validator_configured", False):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = AppLogFormatter()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    original_showwarning = warnings.showwarning

    def show_warning(message, category, filename, lineno, file=None, line=None):
        if file is not None:
            # Respect callers that explicitly redirect their warning output.
            return original_showwarning(message, category, filename, lineno, file, line)
        record = logger.makeRecord(
            "map_validator.warnings",
            logging.WARNING,
            filename,
            lineno,
            f"{category.__name__}: {message}",
            (),
            None,
        )
        logger.handle(record)

    warnings.showwarning = show_warning
    logger._map_validator_configured = True
    logger.info("앱 로그 초기화 완료 (파일: %s)", LOG_FILE.name)
    return logger
