"""The readable style: lined-up columns for a person."""

import logging
import re
import time

import pytest

from aa_log import configure_logging, get_logger

YELLOW = "\x1b[33m"
RED = "\x1b[31m"
RESET = "\x1b[0m"


@pytest.fixture(autouse=True)
def _readable(monkeypatch):
    monkeypatch.setenv("AA_LOG_FORMAT", "text")


def test_a_line_shows_local_time_level_logger_and_message_in_that_order(piped, monkeypatch):
    # A fixed instant, read back through local time, so the test holds in any time zone.
    instant = 1_800_000_000.0
    monkeypatch.setattr(time, "time_ns", lambda: int(instant * 1e9))
    configure_logging()

    get_logger("my_app").info("started")

    expected = time.strftime("%H:%M:%S", time.localtime(instant))
    assert re.fullmatch(rf"{expected}\s+INFO\s+my_app\s+started\n", piped.getvalue())


def test_the_columns_line_up_across_levels_and_logger_names(piped):
    configure_logging(level=logging.DEBUG)

    get_logger("a").debug("one")
    get_logger("my_app.orders").error("two")
    get_logger("b.c").warning("three")

    lines = piped.getvalue().splitlines()
    assert len({line.index(word) for line, word in zip(lines, ("one", "two", "three"))}) == 1
    assert len({line.index(name) for line, name in zip(lines, ("a", "my_app", "b.c"))}) == 1


def test_the_level_labels_are_short_and_upper_case(piped):
    configure_logging(level=logging.DEBUG)
    log = get_logger("my_app")

    log.debug("m")
    log.info("m")
    log.warning("m")
    log.error("m")
    log.critical("m")

    labels = [line.split()[1] for line in piped.getvalue().splitlines()]
    assert labels == ["DEBUG", "INFO", "WARN", "ERROR", "CRIT"]


def test_a_terminal_shows_warn_yellow_error_and_crit_red_and_the_rest_plain(terminal):
    configure_logging(level=logging.DEBUG)
    log = get_logger("my_app")

    log.debug("m")
    log.info("m")
    log.warning("m")
    log.error("m")
    log.critical("m")

    debug, info, warn, error, crit = terminal.getvalue().splitlines()
    assert "\x1b" not in debug
    assert "\x1b" not in info
    assert f"{YELLOW}WARN{RESET}" in warn
    assert f"{RED}ERROR{RESET}" in error
    assert f"{RED}CRIT{RESET}" in crit


def test_the_columns_line_up_on_a_terminal_too(terminal):
    configure_logging()

    get_logger("my_app").info("one")
    get_logger("my_app").warning("two")

    plain = [re.sub(r"\x1b\[\d+m", "", line) for line in terminal.getvalue().splitlines()]
    assert plain[0].index("one") == plain[1].index("two")


def test_no_color_codes_when_the_readable_style_is_forced_off_a_terminal(piped):
    configure_logging()

    get_logger("my_app").error("bad")

    assert "\x1b" not in piped.getvalue()


def test_a_logger_name_wider_than_its_column_is_shown_in_full(piped):
    name = "my_app.a_package_with_a_long_name.a_module_with_a_long_name.and_more"
    configure_logging()

    get_logger(name).info("m")

    assert f" {name} " in piped.getvalue()


def test_extra_data_appears_after_the_message_as_key_value(piped):
    configure_logging()

    get_logger("my_app").info("fetched", extra={"url": "http://x", "code": 200})

    assert piped.getvalue().rstrip("\n").endswith("fetched url=http://x code=200")


def test_error_details_appear_below_the_line_that_reported_them(piped):
    configure_logging()

    try:
        raise ValueError("broken thing")
    except ValueError:
        get_logger("my_app").exception("it failed")

    first, *details = piped.getvalue().splitlines()
    assert first.endswith("it failed")
    assert details[0] == "Traceback (most recent call last):"
    assert details[-1] == "ValueError: broken thing"
