"""The JSON style: one complete object per line, for programs."""

import json
from datetime import datetime

from aa_log import configure_logging, get_logger


def lines(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_a_message_is_one_json_object_with_time_level_logger_and_message(piped):
    configure_logging()

    get_logger("my_app").info("started")

    assert len(piped.getvalue().splitlines()) == 1
    line = lines(piped)[0]
    assert (line["level"], line["logger"], line["message"]) == ("info", "my_app", "started")
    assert set(line) == {"time", "level", "logger", "message"}


def test_the_time_is_iso_8601_with_a_utc_offset(piped):
    configure_logging()

    get_logger("my_app").info("started")

    assert datetime.fromisoformat(lines(piped)[0]["time"]).utcoffset() is not None


def test_the_level_is_the_label_in_lower_case(piped):
    configure_logging()
    log = get_logger("my_app")

    log.warning("m")
    log.critical("m")

    assert [line["level"] for line in lines(piped)] == ["warn", "crit"]


def test_a_newline_in_a_message_stays_on_one_line(piped):
    configure_logging()

    get_logger("my_app").info("one\ntwo")

    assert [line["message"] for line in lines(piped)] == ["one\ntwo"]


def test_each_extra_value_is_a_top_level_field(piped):
    configure_logging()

    get_logger("my_app").info("fetched", extra={"url": "http://x", "code": 200})

    line = lines(piped)[0]
    assert (line["url"], line["code"]) == ("http://x", 200)


def test_error_details_are_under_exception_in_that_same_line(piped):
    configure_logging()

    try:
        raise ValueError("broken thing")
    except ValueError:
        get_logger("my_app").exception("it failed")

    assert len(piped.getvalue().splitlines()) == 1
    line = lines(piped)[0]
    assert line["exception"].startswith("Traceback (most recent call last):")
    assert line["exception"].endswith("ValueError: broken thing")


def test_extra_cannot_replace_the_standard_fields(piped):
    configure_logging()

    get_logger("my_app").info("m", extra={"time": "t", "level": "l", "logger": "x", "other": 1})

    line = lines(piped)[0]
    assert (line["level"], line["logger"], line["other"]) == ("info", "my_app", 1)
    assert datetime.fromisoformat(line["time"]).utcoffset() is not None


def test_extra_cannot_replace_the_error_details(piped):
    configure_logging()

    try:
        raise ValueError("real")
    except ValueError:
        get_logger("my_app").exception("m", extra={"exception": "fake"})

    assert lines(piped)[0]["exception"].endswith("ValueError: real")


def test_an_extra_value_json_cannot_hold_is_written_as_text(piped):
    configure_logging()

    get_logger("my_app").info("m", extra={"thing": {1}, "fine": 1})

    line = lines(piped)[0]
    assert (line["thing"], line["fine"]) == ("{1}", 1)


def test_extra_values_json_rejects_while_encoding_are_written_as_text(piped):
    circular = []
    circular.append(circular)
    configure_logging()

    get_logger("my_app").info(
        "m", extra={"circular": circular, "tuple_key": {(1, 2): "x"}, "nan": float("nan")}
    )

    line = lines(piped)[0]
    assert (line["circular"], line["tuple_key"], line["nan"]) == (
        "[[...]]",
        "{(1, 2): 'x'}",
        "nan",
    )


def test_a_value_that_cannot_even_be_turned_into_text_does_not_lose_the_line(piped):
    class Broken:
        def __str__(self):
            raise RuntimeError("no text for you")

    configure_logging()

    get_logger("my_app").info("still here", extra={"broken": Broken()})

    line = lines(piped)[0]
    assert line["message"] == "still here"
    assert isinstance(line["broken"], str)
