"""How a log record looks on the way out."""

import json
import logging

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

_STANDARD_FIELDS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def _label(record: logging.LogRecord) -> str:
    return _LABELS.get(record.levelno, record.levelname)


def _extra(record: logging.LogRecord) -> dict[str, object]:
    return {key: value for key, value in vars(record).items() if key not in _STANDARD_FIELDS}


class _Formatter(logging.Formatter):
    def _details(self, record: logging.LogRecord) -> str | None:
        """Return the error details and stack of a record, if it has any."""
        parts = []
        if record.exc_info:
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
        pairs = [f"{key}={value}" for key, value in _extra(record).items()]
        text = " ".join([record.getMessage(), *pairs])
        time = self.formatTime(record, "%H:%M:%S")
        line = f"{time}  {self._level(record)}  {record.name:<{_LOGGER_WIDTH}}  {text}"
        details = self._details(record)
        return f"{line}\n{details}" if details else line


class JsonFormatter(_Formatter):
    """One complete JSON object per record, on one line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": _label(record).lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)
