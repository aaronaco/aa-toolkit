"""Choosing between the readable style and JSON."""

import json

import pytest

from aa_log import configure_logging, get_logger


def is_json(stream):
    return isinstance(json.loads(stream.getvalue().splitlines()[0]), dict)


def is_readable(stream):
    return "hello" in stream.getvalue() and not stream.getvalue().startswith("{")


def log_one():
    get_logger("my_app").info("hello")


def test_the_readable_style_is_used_when_stderr_is_a_terminal(terminal):
    configure_logging()
    log_one()

    assert is_readable(terminal)


def test_json_is_used_when_stderr_is_not_a_terminal(piped):
    configure_logging()
    log_one()

    assert is_json(piped)


@pytest.mark.parametrize("value", ["text", "TEXT"])
def test_aa_log_format_forces_the_readable_style_when_stderr_is_not_a_terminal(
    piped, monkeypatch, value
):
    monkeypatch.setenv("AA_LOG_FORMAT", value)
    configure_logging()
    log_one()

    assert is_readable(piped)


def test_aa_log_format_forces_json_when_stderr_is_a_terminal(terminal, monkeypatch):
    monkeypatch.setenv("AA_LOG_FORMAT", "json")
    configure_logging()
    log_one()

    assert is_json(terminal)
