"""Cleaning each log record with the app's own function before it's formatted (ADR 0005)."""

import copy
import logging
from collections.abc import Callable, Mapping

from aa_log._format import STANDARD_FIELDS, extra

Redact = Callable[[dict[str, object]], object]

FAILED = "[REDACTION FAILED]"
_FIELDS = frozenset({"message", "exception", "stack", "extra"})
_TRACEBACKS = logging.Formatter()


class _WrongShape(Exception):
    """The redact function returned something other than the mapping it was given."""


def _exception(record: logging.LogRecord) -> str | None:
    if record.exc_info:
        return _TRACEBACKS.formatException(record.exc_info)
    return record.exc_text


def _text_or_none(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise _WrongShape


def _detached(value: object, copies: dict[int, object]) -> object:
    """Copy the dicts, lists, sets and tuples in a value, and keep every other object as it is.

    `copies` maps each container already copied to its copy, so shared and circular parts
    stay that way.
    """
    if id(value) in copies:
        return copies[id(value)]
    if isinstance(value, dict):
        copied_dict = copies[id(value)] = copy.copy(value)
        for key, item in value.items():
            copied_dict[key] = _detached(item, copies)
        return copied_dict
    if isinstance(value, list):
        copied_list = copies[id(value)] = copy.copy(value)
        copied_list[:] = [_detached(item, copies) for item in value]
        return copied_list
    if isinstance(value, set):
        copied_set = copies[id(value)] = copy.copy(value)
        return copied_set
    if isinstance(value, tuple):
        items = [_detached(item, copies) for item in value]
        if all(new is old for new, old in zip(items, value, strict=True)):
            return value
        return tuple.__new__(type(value), items)
    return value


def _checked(result: object) -> tuple[str, str | None, str | None, dict[str, object]]:
    """Return the fields of a redact result, or raise when it isn't the shape it was given."""
    if not isinstance(result, Mapping) or set(result) != _FIELDS:
        raise _WrongShape
    message, extras = result["message"], result["extra"]
    if not isinstance(message, str) or not isinstance(extras, Mapping):
        raise _WrongShape
    cleaned_extras: dict[str, object] = {}
    for key, value in extras.items():
        if not isinstance(key, str) or key in STANDARD_FIELDS:
            raise _WrongShape
        cleaned_extras[key] = value
    return (
        message,
        _text_or_none(result["exception"]),
        _text_or_none(result["stack"]),
        cleaned_extras,
    )


def _failed(record: logging.LogRecord) -> logging.LogRecord:
    """A record with only the time, level and logger of `record`, and FAILED as its message."""
    failed = logging.makeLogRecord(
        {"name": record.name, "levelno": record.levelno, "levelname": record.levelname}
    )
    failed.created, failed.msecs = record.created, record.msecs
    failed.relativeCreated = record.relativeCreated
    failed.msg = FAILED
    return failed


class Redaction(logging.Filter):
    """A handler filter that passes on a redacted copy of each record, and never raises."""

    def __init__(self, redact: Redact) -> None:
        super().__init__()
        self._redact = redact
        self.let_through: list[logging.LogRecord] = []

    def filter(self, record: logging.LogRecord) -> logging.LogRecord | bool:
        if any(record is allowed for allowed in self.let_through):
            return True
        try:
            return self._clean(record)
        except Exception:
            try:
                return _failed(record)
            except Exception:
                return False

    def _clean(self, record: logging.LogRecord) -> logging.LogRecord:
        raw_extras = extra(record)
        message, exception, stack, cleaned_extras = _checked(
            self._redact(
                {
                    "message": record.getMessage(),
                    "exception": _exception(record),
                    "stack": record.stack_info,
                    "extra": _detached(raw_extras, {}),
                }
            )
        )
        clean = copy.copy(record)
        for key in raw_extras:
            delattr(clean, key)
        clean.msg = clean.message = message
        clean.args = ()
        clean.exc_info = None
        clean.exc_text = exception
        clean.stack_info = stack
        vars(clean).update(cleaned_extras)
        return clean
