"""How a log record looks on the way out."""

import json
import logging
from datetime import datetime

_LABELS = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARN",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRIT",
}
_LEVEL_WIDTH = 5
_LOGGER_WIDTH = 24

_YELLOW = "\x1b[33m"
_RED = "\x1b[31m"
_RESET = "\x1b[0m"

_ESCAPED_LINE_BREAKS = str.maketrans({0x85: r"\u0085", 0x2028: r"\u2028", 0x2029: r"\u2029"})

STANDARD_FIELDS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def _label(record: logging.LogRecord) -> str:
    return _LABELS.get(record.levelno, record.levelname)


def extra(record: logging.LogRecord) -> dict[str, object]:
    return {key: value for key, value in vars(record).items() if key not in STANDARD_FIELDS}


def _text(value: object) -> str:
    """Turn a value into text, even one whose own ``__str__`` fails."""
    try:
        return str(value)
    except Exception:
        return f"<unprintable {type(value).__name__}>"


def _json_value(value: object) -> object:
    """Keep a value JSON can hold, and turn any other into text."""
    try:
        json.dumps(value, default=str, allow_nan=False)
    except Exception:
        return _text(value)
    return value


class _Formatter(logging.Formatter):
    def _details(self, record: logging.LogRecord) -> str | None:
        """Return the error details and stack of a record, if it has any."""
        parts = []
        if record.exc_text:
            parts.append(record.exc_text)
        elif record.exc_info:
            parts.append(self.formatException(record.exc_info))
        if record.stack_info:
            parts.append(self.formatStack(record.stack_info))
        return "\n".join(parts) or None


class TextFormatter(_Formatter):
    """Lined-up columns of time, level, logger name and message, for a person."""

    def __init__(self, *, color: bool) -> None:
        super().__init__()
        self._color = color

    def _level(self, record: logging.LogRecord) -> str:
        label = _label(record)
        padding = " " * (_LEVEL_WIDTH - len(label))
        if self._color and record.levelno >= logging.ERROR:
            return f"{_RED}{label}{_RESET}{padding}"
        if self._color and record.levelno >= logging.WARNING:
            return f"{_YELLOW}{label}{_RESET}{padding}"
        return f"{label}{padding}"

    def format(self, record: logging.LogRecord) -> str:
        pairs = [f"{key}={_text(value)}" for key, value in extra(record).items()]
        text = " ".join([record.getMessage(), *pairs])
        time = self.formatTime(record, "%H:%M:%S")
        line = f"{time}  {self._level(record)}  {record.name:<{_LOGGER_WIDTH}}  {text}"
        details = self._details(record)
        return f"{line}\n{details}" if details else line


class JsonFormatter(_Formatter):
    """One complete JSON object per record, on one line."""

    def format(self, record: logging.LogRecord) -> str:
        when = datetime.fromtimestamp(record.created).astimezone()
        payload: dict[str, object] = {
            "time": when.isoformat(timespec="milliseconds"),
            "level": _label(record).lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        details = self._details(record)
        if details:
            payload["exception"] = details
        for key, value in extra(record).items():
            payload.setdefault(key, _json_value(value))
        return json.dumps(payload, ensure_ascii=False, default=_text).translate(
            _ESCAPED_LINE_BREAKS
        )
