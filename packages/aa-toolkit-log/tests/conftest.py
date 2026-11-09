import io
import logging
import sys
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]


class Terminal(io.StringIO):
    """A stderr that acts like a terminal."""

    def isatty(self) -> bool:
        return True


def _reset_logging() -> None:
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if not type(handler).__module__.startswith("_pytest"):
            root.removeHandler(handler)
            handler.close()
    root.setLevel(logging.WARNING)


@pytest.fixture(autouse=True)
def _clean_logging(monkeypatch):
    """Start each test with logging reset and none of the developer's own settings."""
    for variable in ("AA_LOG_LEVEL", "AA_LOG_FORMAT", "AA_LOG_FILE"):
        monkeypatch.delenv(variable, raising=False)
    _reset_logging()
    yield
    _reset_logging()


@pytest.fixture
def piped(monkeypatch) -> io.StringIO:
    """Swap stderr for a stream that isn't a terminal."""
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    return stream


@pytest.fixture
def terminal(monkeypatch) -> Terminal:
    """Swap stderr for a stream that acts like a terminal."""
    stream = Terminal()
    monkeypatch.setattr(sys, "stderr", stream)
    return stream


@pytest.fixture
def package_dir() -> Path:
    """The aa-toolkit-log package folder in this checkout."""
    return PACKAGE_DIR
