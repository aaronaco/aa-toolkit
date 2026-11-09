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


def _label(record: logging.LogRecord) -> str:
    return _LABELS.get(record.levelno, record.levelname)


class JsonFormatter(logging.Formatter):
    """One complete JSON object per record, on one line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": _label(record).lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)
