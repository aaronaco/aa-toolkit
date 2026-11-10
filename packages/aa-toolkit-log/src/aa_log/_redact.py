"""Cleaning each log record with the app's own function before it's formatted (ADR 0005)."""

import copy
import logging
from collections.abc import Callable

from aa_log._format import extra

Redact = Callable[[dict[str, object]], object]

_TRACEBACKS = logging.Formatter()


def _exception(record: logging.LogRecord) -> str | None:
    if record.exc_text:
        return record.exc_text
    if record.exc_info:
        return _TRACEBACKS.formatException(record.exc_info)
    return None


class Redaction(logging.Filter):
    """A handler filter that passes on a redacted copy of each record."""

    def __init__(self, redact: Redact) -> None:
        super().__init__()
        self._redact = redact

    def filter(self, record: logging.LogRecord) -> logging.LogRecord:
        extras = extra(record)
        fields = self._redact(
            {
                "message": record.getMessage(),
                "exception": _exception(record),
                "stack": record.stack_info,
                "extra": extras,
            }
        )
        clean = copy.copy(record)
        for key in extras:
            delattr(clean, key)
        clean.msg = fields["message"]
        clean.args = ()
        clean.exc_info = None
        clean.exc_text = fields["exception"]
        clean.stack_info = fields["stack"]
        vars(clean).update(fields["extra"])
        return clean
