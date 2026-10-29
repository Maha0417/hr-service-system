import logging
import os
from pathlib import Path
from typing import Optional, Union

_LOGGER_MARKER = "_hr_service_system_handler"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_LOG_FILE = _PROJECT_ROOT / "output" / "logs" / "hr_service_system.log"

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: Optional[Union[str, int]] = None,
    log_to_file: bool = True,
) -> None:
    """Configure console logging and optionally a persistent log file.

    Repeated calls update the existing handlers instead of duplicating them.
    The log level can be supplied directly or through the LOG_LEVEL
    environment variable. INFO is the default.
    """
    configured_level = level or os.getenv("LOG_LEVEL", "INFO")

    if isinstance(configured_level, str):
        numeric_level = getattr(
            logging, configured_level.upper(), logging.INFO
        )
    else:
        numeric_level = configured_level

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    formatter = logging.Formatter(
        fmt=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
    )

    existing_handlers = [
        handler
        for handler in root_logger.handlers
        if getattr(handler, _LOGGER_MARKER, False)
    ]

    if not any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in existing_handlers
    ):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        setattr(console_handler, _LOGGER_MARKER, True)
        root_logger.addHandler(console_handler)

    if log_to_file and not any(
        isinstance(handler, logging.FileHandler)
        for handler in existing_handlers
    ):
        _DEFAULT_LOG_FILE.parent.mkdir(
            parents=True, exist_ok=True
        )
        file_handler = logging.FileHandler(
            _DEFAULT_LOG_FILE,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        setattr(file_handler, _LOGGER_MARKER, True)
        root_logger.addHandler(file_handler)

    for handler in existing_handlers:
        handler.setLevel(numeric_level)
        handler.setFormatter(formatter)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger for an application module."""
    return logging.getLogger(name)
