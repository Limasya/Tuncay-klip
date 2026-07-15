"""
Structured logging configuration for the Klip pipeline.

Usage:
    from utils.logging_config import setup_logging
    setup_logging(level="INFO")

Features:
- JSON structured logs in production
- Colored console output in development
- Per-service log levels
- Request ID correlation
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path


LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Per-service log levels (quieter for noisy services)
SERVICE_LEVELS = {
    "event_bus": logging.WARNING,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "urllib3": logging.WARNING,
    "asyncio": logging.WARNING,
    "sqlalchemy.engine": logging.WARNING,
    "celery": logging.INFO,
    "orchestrator": logging.INFO,
    "event_detector": logging.INFO,
    "decision_engine": logging.INFO,
    "chat_analysis": logging.INFO,
    "audio_analysis": logging.INFO,
    "video_analysis": logging.INFO,
    "subtitle_service": logging.INFO,
    "video_editor_ms": logging.INFO,
    "thumbnail_ms": logging.INFO,
    "uploader_ms": logging.INFO,
    "pipeline_api": logging.INFO,
}


class StructuredFormatter(logging.Formatter):
    """
    Simple structured formatter that outputs key=value pairs.
    Easy to parse with log aggregators (ELK, Loki, CloudWatch).
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, self.datefmt)
        msg = record.getMessage()

        parts = [
            f"ts={timestamp}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"msg=\"{msg}\"",
        ]

        # Add exception info
        if record.exc_info and record.exc_info[0]:
            exc_type = record.exc_info[0].__name__
            exc_msg = str(record.exc_info[1])
            parts.append(f"exception=\"{exc_type}: {exc_msg}\"")

        return " ".join(parts)


class ColorFormatter(logging.Formatter):
    """Colored console output for development."""

    COLORS = {
        logging.DEBUG: "\033[36m",    # cyan
        logging.INFO: "\033[32m",     # green
        logging.WARNING: "\033[33m",  # yellow
        logging.ERROR: "\033[31m",    # red
        logging.CRITICAL: "\033[35m", # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        timestamp = self.formatTime(record, "%H:%M:%S")
        msg = record.getMessage()

        line = f"{color}{timestamp} [{record.levelname:<7}] {record.name}: {msg}{self.RESET}"

        if record.exc_info and record.exc_info[0]:
            line += f"\n  {record.exc_info[0].__name__}: {record.exc_info[1]}"

        return line


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: bool = True,
) -> logging.Logger:
    """
    Configure the root logger and per-service loggers.

    Args:
        level: Root log level (DEBUG, INFO, WARNING, ERROR)
        json_format: Use structured key=value format (for production)
        log_file: Also write to data/logs/app.log
    """
    root_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(root_level)

    # Clear existing handlers
    root.handlers.clear()

    # Console handler
    if json_format:
        console_fmt = StructuredFormatter()
    else:
        console_fmt = ColorFormatter()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_fmt)
    console_handler.setLevel(root_level)
    root.addHandler(console_handler)

    # File handler (always structured)
    if log_file:
        file_fmt = StructuredFormatter()
        file_handler = logging.FileHandler(
            str(LOG_DIR / "app.log"),
            encoding="utf-8",
        )
        file_handler.setFormatter(file_fmt)
        file_handler.setLevel(logging.INFO)
        root.addHandler(file_handler)

    # Per-service levels
    for logger_name, logger_level in SERVICE_LEVELS.items():
        logging.getLogger(logger_name).setLevel(logger_level)

    root.info("Logging configured: level=%s, json=%s, file=%s", level, json_format, log_file)
    return root
