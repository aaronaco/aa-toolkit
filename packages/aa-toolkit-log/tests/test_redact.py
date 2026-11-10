"""The redact option: every log line is cleaned by the app's own function before it's written."""

import json
import logging
import re
import subprocess
import sys
from datetime import datetime

import pytest

from aa_log import configure_logging, get_logger


def lines(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def upper(fields):
    """A stand-in for a real redaction function, whose cleaning is easy to see."""
    return {
        "message": fields["message"].upper(),
        "exception": fields["exception"] and fields["exception"].upper(),
        "stack": fields["stack"] and fields["stack"].upper(),
        "extra": {key: str(value).upper() for key, value in fields["extra"].items()},
    }


def test_the_function_sees_the_complete_message_and_its_result_is_written(piped):
    seen = []

    def redact(fields):
        seen.append(fields["message"])
        return upper(fields)

    configure_logging(redact=redact)

    get_logger("my_app").info("user %s paid %d", "ann", 5)

    assert seen == ["user ann paid 5"]
    assert lines(piped)[0]["message"] == "USER ANN PAID 5"


def log_an_error():
    try:
        raise ValueError("token abc123")
    except ValueError:
        get_logger("my_app").exception("it failed")


def test_a_cleaned_traceback_is_written_in_the_json_style(piped):
    configure_logging(redact=upper)

    log_an_error()

    exception = lines(piped)[0]["exception"]
    assert exception.startswith("TRACEBACK (MOST RECENT CALL LAST):")
    assert exception.endswith("VALUEERROR: TOKEN ABC123")
    assert "abc123" not in piped.getvalue()


def test_a_cleaned_traceback_is_written_in_the_readable_style(piped, monkeypatch):
    monkeypatch.setenv("AA_LOG_FORMAT", "text")
    configure_logging(redact=upper)

    log_an_error()

    first, *details = piped.getvalue().splitlines()
    assert first.endswith("IT FAILED")
    assert details[0] == "TRACEBACK (MOST RECENT CALL LAST):"
    assert details[-1] == "VALUEERROR: TOKEN ABC123"
    assert "abc123" not in piped.getvalue()


def test_cleaned_stack_information_is_written(piped):
    configure_logging(redact=upper)

    get_logger("my_app").info("here", stack_info=True)

    stack = lines(piped)[0]["exception"]
    assert stack.startswith("STACK (MOST RECENT CALL LAST):")
    assert "test_cleaned_stack_information_is_written" not in piped.getvalue()


def test_cleaned_extras_are_written_in_both_styles(piped, monkeypatch):
    configure_logging(redact=upper)
    get_logger("my_app").info("m", extra={"user": "ann", "code": 200})
    monkeypatch.setenv("AA_LOG_FORMAT", "text")
    configure_logging(redact=upper)
    get_logger("my_app").info("m", extra={"user": "ann", "code": 200})

    json_line, text_line = piped.getvalue().splitlines()
    assert (json.loads(json_line)["user"], json.loads(json_line)["code"]) == ("ANN", "200")
    assert text_line.endswith("M user=ANN code=200")
    assert "ann" not in piped.getvalue()


def test_the_function_gets_the_extras_nested_under_extra(piped):
    seen = []

    def redact(fields):
        seen.append(fields)
        return fields

    configure_logging(redact=redact)

    get_logger("my_app").info("m", extra={"user": "ann", "tags": ["a", "b"]})

    assert seen == [
        {
            "message": "m",
            "exception": None,
            "stack": None,
            "extra": {"user": "ann", "tags": ["a", "b"]},
        }
    ]


def test_a_line_from_a_packages_own_logger_is_cleaned_too(piped):
    configure_logging(redact=upper)

    logging.getLogger("some_package.client").warning("retrying %s", "secret-url")

    assert lines(piped)[0]["message"] == "RETRYING SECRET-URL"


def test_the_screen_and_the_file_hold_the_same_cleaned_values(piped, tmp_path):
    path = tmp_path / "app.log"
    configure_logging(file=path, redact=upper)

    log_an_error()
    get_logger("my_app").info("paid %s", "ann", extra={"card": "visa"})

    screen = lines(piped)
    saved = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [{k: v for k, v in line.items() if k != "time"} for line in screen] == [
        {k: v for k, v in line.items() if k != "time"} for line in saved
    ]
    assert screen[1]["message"] == "PAID ANN"
    assert "ann" not in path.read_text(encoding="utf-8")


NOISY = '"quoted"\n\\ and  '


def quoting(fields):
    """A function that leaves characters JSON has to escape, in every field."""
    noisy = NOISY
    return {
        "message": fields["message"] + noisy,
        "exception": fields["exception"] and noisy,
        "stack": fields["stack"] and noisy,
        "extra": {key: noisy for key in fields["extra"]},
    }


def test_every_json_line_still_parses_after_redaction(piped):
    configure_logging(redact=quoting)

    get_logger("my_app").info("m", extra={"a": 1})
    log_an_error()

    assert len(piped.getvalue().splitlines()) == 2
    assert all(line["message"].endswith(NOISY) for line in lines(piped))
    extra_line, error_line = lines(piped)
    assert (extra_line["a"], error_line["exception"]) == (NOISY, NOISY)


def test_the_readable_columns_still_line_up_after_redaction(piped, monkeypatch):
    monkeypatch.setenv("AA_LOG_FORMAT", "text")
    configure_logging(level=logging.DEBUG, redact=upper)

    get_logger("a").debug("one")
    get_logger("my_app.orders").error("two")

    first, second = piped.getvalue().splitlines()
    assert first.index("ONE") == second.index("TWO")
    assert first.index(" a ") + 1 == second.index("my_app.orders")


def test_without_redact_nothing_is_cleaned(piped):
    configure_logging()

    get_logger("my_app").info("user %s", "ann", extra={"card": "visa"})

    line = lines(piped)[0]
    assert (line["message"], line["card"]) == ("user ann", "visa")


def test_a_second_call_replaces_the_earlier_redact(piped):
    configure_logging(redact=upper)
    configure_logging(redact=lambda fields: {**fields, "message": "second"})

    get_logger("my_app").info("m")

    assert lines(piped)[0]["message"] == "second"


def test_a_second_call_without_redact_turns_it_off(piped):
    configure_logging(redact=upper)
    configure_logging()

    get_logger("my_app").info("m")

    assert lines(piped)[0]["message"] == "m"


def test_the_record_other_handlers_get_is_left_alone(piped):
    seen = []

    class Keep(logging.Handler):
        def emit(self, record):
            seen.append((record.getMessage(), record.card))

    logging.getLogger().addHandler(Keep())
    configure_logging(redact=upper)

    get_logger("my_app").info("user %s", "ann", extra={"card": "visa"})

    assert seen == [("user ann", "visa")]
    assert lines(piped)[0]["message"] == "USER ANN"


def raises(fields):
    raise RuntimeError("cannot redact " + fields["message"])


def wrong_shapes():
    good = {"message": "m", "exception": None, "stack": None, "extra": {}}
    return [
        "just text",
        None,
        {"message": "m"},
        {**good, "more": 1},
        {**good, "message": 1},
        {**good, "exception": 1},
        {**good, "stack": ["s"]},
        {**good, "extra": ["user"]},
        {**good, "extra": {1: "user"}},
        {**good, "extra": {"msg": "forged"}},
    ]


@pytest.mark.parametrize(
    "redact",
    [raises, *(lambda fields, shape=shape: shape for shape in wrong_shapes())],
    ids=["raises", *(f"shape{n}" for n in range(len(wrong_shapes())))],
)
def test_a_failed_redaction_writes_only_time_level_logger_and_redaction_failed(piped, redact):
    configure_logging(redact=redact)

    try:
        raise ValueError("token abc123")
    except ValueError:
        get_logger("my_app").exception("user %s", "ann", extra={"card": "visa"}, stack_info=True)
    get_logger("my_app").info("still running")

    failed = lines(piped)[0]
    assert set(failed) == {"time", "level", "logger", "message"}
    assert (failed["level"], failed["logger"], failed["message"]) == (
        "error",
        "my_app",
        "[REDACTION FAILED]",
    )
    assert datetime.fromisoformat(failed["time"]).utcoffset() is not None
    for raw in ("ann", "visa", "abc123", "Traceback", "Stack"):
        assert raw not in piped.getvalue()
    assert len(lines(piped)) == 2


def test_a_failed_redaction_in_the_readable_style_keeps_the_columns(piped, monkeypatch):
    def fails_on_ann(fields):
        return raises(fields) if "ann" in fields["message"] else fields

    monkeypatch.setenv("AA_LOG_FORMAT", "text")
    configure_logging(redact=fails_on_ann)

    get_logger("my_app").info("ok")
    try:
        raise ValueError("token abc123")
    except ValueError:
        get_logger("my_app").exception("user %s", "ann", extra={"card": "visa"})

    ok, failed = piped.getvalue().splitlines()
    assert re.fullmatch(r"\d\d:\d\d:\d\d  ERROR  my_app +\[REDACTION FAILED\]", failed)
    assert ok.index("ok") == failed.index("[REDACTION FAILED]")


BAD_FORMAT_APP = """
import sys
from aa_log import configure_logging, get_logger

configure_logging(redact=lambda fields: fields)
get_logger("my_app").info("count %d", "secret-value")
print("still running", file=sys.stderr)
"""


def test_values_that_do_not_fit_the_message_appear_nowhere(monkeypatch):
    monkeypatch.setenv("AA_LOG_FORMAT", "json")

    done = subprocess.run(
        [sys.executable, "-c", BAD_FORMAT_APP], capture_output=True, text=True, timeout=60
    )

    assert done.returncode == 0
    failed, still_running = done.stderr.splitlines()
    assert json.loads(failed)["message"] == "[REDACTION FAILED]"
    assert still_running == "still running"
    assert "secret-value" not in done.stdout + done.stderr


@pytest.mark.parametrize("redact", ["not a function", 42])
def test_a_redact_that_cannot_be_called_warns_and_every_line_fails(piped, redact):
    configure_logging(redact=redact)

    get_logger("my_app").info("user %s", "ann")

    warning, line = lines(piped)
    assert warning["level"] == "warn"
    assert "redact=" in warning["message"]
    assert type(redact).__name__ in warning["message"]
    assert str(redact) not in warning["message"]
    assert line["message"] == "[REDACTION FAILED]"
    assert "ann" not in piped.getvalue()


@pytest.mark.parametrize("value", ["off", "0", "false", "on"])
def test_no_environment_variable_turns_redaction_on_or_off(piped, monkeypatch, value):
    for name in ("AA_LOG_REDACT", "AA_REDACT"):
        monkeypatch.setenv(name, value)
    configure_logging(redact=upper)
    get_logger("my_app").info("cleaned")
    configure_logging()
    get_logger("my_app").info("raw")

    assert [line["message"] for line in lines(piped)] == ["CLEANED", "raw"]


@pytest.mark.parametrize("redact", ["not a function"])
def test_only_the_redact_warning_gets_past_a_redact_that_cannot_be_called(
    piped, monkeypatch, redact
):
    monkeypatch.setenv("AA_LOG_LEVEL", "secret-level")
    configure_logging(redact=redact)

    messages = [line["message"] for line in lines(piped)]

    assert len(messages) == 2
    assert [message for message in messages if "redact=" in message] != []
    assert "[REDACTION FAILED]" in messages
    assert "secret-level" not in piped.getvalue()
