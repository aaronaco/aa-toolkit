"""Turning logging on for an app."""

import logging
import os
import sys

from aa_log._format import JsonFormatter, TextFormatter

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRIT": logging.CRITICAL,
    "CRITICAL": logging.CRITICAL,
}

_installed: list[logging.Handler] = []


def _env(name: str) -> str | None:
    """Return an environment variable, counting an empty one as not set."""
    return os.environ.get(name, "").strip() or None


def _parse_level(value: int | str) -> int:
    return value if isinstance(value, int) else _LEVELS[value.strip().upper()]


def _screen_formatter(terminal: bool) -> logging.Formatter:
    style = _env("AA_LOG_FORMAT")
    if style is None:
        style = "text" if terminal else "json"
    return TextFormatter(color=terminal) if style.lower() == "text" else JsonFormatter()


def get_logger(name: str) -> logging.Logger:
    """Return the standard Python logger for ``name``. Safe at the top of a file."""
    return logging.getLogger(name)


def configure_logging(level: int | str = logging.INFO) -> None:
    """Set up logging for the whole app. Call it once when the app starts."""
    root = logging.getLogger()
    for handler in _installed:
        root.removeHandler(handler)
        handler.close()
    _installed.clear()

    screen = logging.StreamHandler(sys.stderr)
    screen.setFormatter(_screen_formatter(sys.stderr.isatty()))
    root.addHandler(screen)
    _installed.append(screen)
    root.setLevel(_parse_level(_env("AA_LOG_LEVEL") or level))
