"""Which messages are shown: the default, level= and AA_LOG_LEVEL."""

import json
import logging

import pytest

from aa_log import configure_logging, get_logger


def shown(stream):
    return [json.loads(line)["message"] for line in stream.getvalue().splitlines()]


def log_each_level():
    log = get_logger("my_app")
    log.debug("debug")
    log.info("info")
    log.warning("warning")
    log.error("error")
    log.critical("critical")


def test_info_and_above_are_shown_when_nothing_is_set(piped):
    configure_logging()

    log_each_level()

    assert shown(piped) == ["info", "warning", "error", "critical"]


@pytest.mark.parametrize("level", [logging.ERROR, "ERROR", "error"])
def test_the_level_argument_is_used(piped, level):
    configure_logging(level=level)

    log_each_level()

    assert shown(piped) == ["error", "critical"]


def test_aa_log_level_overrides_the_level_argument(piped, monkeypatch):
    monkeypatch.setenv("AA_LOG_LEVEL", "debug")
    configure_logging(level="ERROR")

    log_each_level()

    assert shown(piped) == ["debug", "info", "warning", "error", "critical"]


@pytest.mark.parametrize(
    ("name", "first_shown"),
    [("WARN", "warning"), ("WARNING", "warning"), ("CRIT", "critical"), ("CRITICAL", "critical")],
)
def test_both_the_short_and_the_python_level_names_work(piped, monkeypatch, name, first_shown):
    monkeypatch.setenv("AA_LOG_LEVEL", name)
    configure_logging()

    log_each_level()

    assert shown(piped)[0] == first_shown


def test_setting_up_logging_leaves_loggers_named_after_the_library_at_the_app_level(piped):
    configure_logging(level="DEBUG")

    get_logger("aa_log.worker").debug("shown")

    assert shown(piped) == ["shown"]
