"""Turning logging on for an app."""

import contextlib
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from aa_log._format import JsonFormatter, TextFormatter
from aa_log._redact import FAILED, Redact, Redaction

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRIT": logging.CRITICAL,
    "CRITICAL": logging.CRITICAL,
}
_MAX_FILE_BYTES = 10 * 1024 * 1024
_OLD_FILES_KEPT = 3
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

_installed: list[logging.Handler] = []


def _env(name: str) -> str | None:
    """Return an environment variable, counting an empty one as not set."""
    return os.environ.get(name, "").strip() or None


def _parse_level(value: int | str) -> int | None:
    if isinstance(value, int):
        return value
    return _LEVELS.get(str(value).strip().upper())


def _choose_level(level: int | str, problems: list[str]) -> int:
    chosen = _parse_level(level)
    if chosen is None:
        problems.append(f"level={level!r} is not a log level, using INFO")
        chosen = logging.INFO
    value = _env("AA_LOG_LEVEL")
    if value is None:
        return chosen
    from_env = _parse_level(value)
    if from_env is None:
        name = logging.getLevelName(chosen)
        problems.append(f"AA_LOG_LEVEL is {value!r}, which is not a log level, using {name}")
        return chosen
    return from_env


def _is_terminal(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except AttributeError, ValueError:  # no stderr at all, or a closed one
        return False


def _enable_color(stream: TextIO) -> None:
    """Make a Windows console act on color codes instead of printing them as text."""
    if sys.platform != "win32":
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes

    try:
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
    except AttributeError, OSError, ValueError:  # a stream that only acts like a terminal
        return
    kernel32 = ctypes.windll.kernel32
    mode = wintypes.DWORD()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        kernel32.SetConsoleMode(handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING)


def _screen_formatter(stream: TextIO, problems: list[str]) -> logging.Formatter:
    terminal = _is_terminal(stream)
    automatic = "text" if terminal else "json"
    style = _env("AA_LOG_FORMAT") or automatic
    if style.lower() not in ("text", "json"):
        problems.append(f"AA_LOG_FORMAT is {style!r}, which is not text or json, using {automatic}")
        style = automatic
    if style.lower() == "json":
        return JsonFormatter()
    if terminal:
        _enable_color(stream)
    return TextFormatter(color=terminal)


def _file_handler(path: str | os.PathLike[str]) -> logging.Handler:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path,
        maxBytes=_MAX_FILE_BYTES,
        backupCount=_OLD_FILES_KEPT,
        encoding="utf-8",
        errors="backslashreplace",
    )
    handler.setFormatter(JsonFormatter())
    return handler


def _attach(handler: logging.Handler, redaction: Redaction | None) -> None:
    if redaction is not None:
        handler.addFilter(redaction)
    logging.getLogger().addHandler(handler)
    _installed.append(handler)


def get_logger(name: str) -> logging.Logger:
    """Return the standard Python logger for ``name``. Safe at the top of a file."""
    return logging.getLogger(name)


def configure_logging(
    level: int | str = logging.INFO,
    file: str | os.PathLike[str] | None = None,
    redact: Redact | None = None,
) -> None:
    """Set up logging for the whole app. Call it once when the app starts.

    ``AA_LOG_LEVEL`` and ``AA_LOG_FILE`` override the arguments, and ``AA_LOG_FORMAT``
    forces the screen style. ``redact`` cleans every line written by these handlers: it gets
    a dict of ``message``, ``exception``, ``stack`` and ``extra`` and returns the same shape.
    Calling it again replaces the earlier settings. A problem with any setting is reported
    as a warning and never stops the app.
    """
    root = logging.getLogger()
    problems: list[str] = []
    for handler in _installed:
        root.removeHandler(handler)
        try:
            handler.close()
        except (OSError, ValueError) as error:
            problems.append(f"could not close the earlier log file: {error}")
    _installed.clear()

    redaction = None if redact is None else Redaction(redact)

    screen = logging.StreamHandler(sys.stderr)
    screen.setFormatter(_screen_formatter(sys.stderr, problems))
    _attach(screen, redaction)
    path = _env("AA_LOG_FILE") or file
    if path is not None:
        try:
            _attach(_file_handler(path), redaction)
        except (OSError, TypeError, ValueError) as error:
            problems.append(f"could not open the log file {path}, logging to screen only: {error}")
    root.setLevel(_choose_level(level, problems))

    # Straight to the handlers, so the warnings still show when the app's level would hide them.
    setup_log = logging.getLogger("aa_log")

    def warning(problem: str) -> logging.LogRecord:
        message = " ".join(problem.splitlines())
        return setup_log.makeRecord(setup_log.name, logging.WARNING, __file__, 0, message, (), None)

    warnings = [warning(problem) for problem in problems]
    if redaction is not None and not callable(redact):
        uncallable = warning(
            f"redact= takes a function, and a {type(redact).__name__} can't be called,"
            f" so every log line shows {FAILED}"
        )
        warnings.insert(0, uncallable)
        redaction.let_through = [uncallable]
    try:
        with contextlib.suppress(ValueError):
            for record in warnings:
                setup_log.handle(record)
    finally:
        if redaction is not None:
            redaction.let_through = []
