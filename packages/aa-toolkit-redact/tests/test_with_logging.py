"""A real Redactor passed to the log library, the way an app joins the two."""

import contextlib
import io
import json
import logging

import pytest

from aa_log import configure_logging, get_logger
from aa_redact import Redactor


@pytest.fixture
def stderr(monkeypatch):
    """A stream standing in for stderr, with logging set back to Python's defaults afterwards."""
    for variable in ("AA_LOG_LEVEL", "AA_LOG_FILE"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("AA_LOG_FORMAT", "json")
    root = logging.getLogger()
    before = root.handlers[:]
    yield io.StringIO()
    for handler in root.handlers[:]:
        if handler not in before:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(logging.WARNING)


def configure_redacted_logging(stderr):
    """Set up logging the way an app would, writing to `stderr` instead of the real one."""
    with contextlib.redirect_stderr(stderr):
        configure_logging(redact=Redactor())


def test_an_email_in_a_message_and_a_password_in_an_extra_are_hidden(stderr):
    configure_redacted_logging(stderr)

    get_logger("my_app").info(
        "signed up %s", "ann@example.com", extra={"password": "hunter2", "plan": "pro"}
    )

    line = json.loads(stderr.getvalue())
    assert (line["message"], line["password"], line["plan"]) == (
        "signed up [EMAIL]",
        "[REDACTED]",
        "pro",
    )
    assert "ann@example.com" not in stderr.getvalue()
    assert "hunter2" not in stderr.getvalue()


def test_an_email_in_a_traceback_is_hidden(stderr):
    configure_redacted_logging(stderr)

    try:
        raise ValueError("no account for ann@example.com")
    except ValueError:
        get_logger("my_app").exception("login failed")

    line = json.loads(stderr.getvalue())
    assert line["exception"].endswith("ValueError: no account for [EMAIL]")
    assert "ann@example.com" not in stderr.getvalue()
