import contextlib
import io
import logging
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
def piped() -> io.StringIO:
    """Run the test with a stderr that isn't a terminal."""
    return io.StringIO()


@pytest.fixture
def terminal() -> Terminal:
    """Run the test with a stderr that acts like a terminal."""
    return Terminal()


@pytest.hookimpl(wrapper=True)
def pytest_pyfunc_call(pyfuncitem):
    """Swap stderr here, because pytest puts its own back when the test body starts."""
    streams = [pyfuncitem.funcargs[n] for n in ("piped", "terminal") if n in pyfuncitem.funcargs]
    if not streams:
        return (yield)
    with contextlib.redirect_stderr(streams[0]):
        return (yield)


@pytest.fixture
def package_dir() -> Path:
    """The aa-toolkit-log package folder in this checkout."""
    return PACKAGE_DIR
