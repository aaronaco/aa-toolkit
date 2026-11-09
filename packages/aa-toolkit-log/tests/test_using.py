"""An app calling configure_logging and logging from its files."""

import json
import logging
import subprocess
import sys

from aa_log import configure_logging, get_logger


def lines(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_a_message_goes_to_stderr_with_its_logger_name_and_stdout_stays_empty(piped, capsys):
    configure_logging()

    get_logger("my_app.orders").info("order placed")

    assert [(line["logger"], line["message"]) for line in lines(piped)] == [
        ("my_app.orders", "order placed")
    ]
    assert capsys.readouterr().out == ""


def test_get_logger_returns_a_standard_python_logger():
    assert isinstance(get_logger("my_app"), logging.Logger)


def test_a_file_that_only_calls_get_logger_does_not_turn_logging_on():
    # In a new process, because pytest attaches handlers of its own to the root logger.
    program = (
        "from aa_log import get_logger\n"
        "log = get_logger('my_app')\n"
        "log.info('hidden')\n"
        "log.warning('python default')\n"
    )

    done = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True)

    assert done.stderr == "python default\n"
    assert done.stdout == ""


def test_calling_configure_logging_twice_shows_each_message_once(piped):
    configure_logging()
    configure_logging()

    get_logger("my_app").info("once")

    assert [line["message"] for line in lines(piped)] == ["once"]


def test_a_handler_attached_by_something_else_stays_attached(piped):
    seen = []

    class Other(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    other = Other()
    logging.getLogger().addHandler(other)

    configure_logging()
    configure_logging()
    get_logger("my_app").info("both see this")

    assert seen == ["both see this"]
    assert [line["message"] for line in lines(piped)] == ["both see this"]


def test_an_installed_package_logging_through_python_appears_in_the_same_format(piped):
    configure_logging()

    logging.getLogger("some_package.client").warning("retrying")

    assert [(line["logger"], line["level"], line["message"]) for line in lines(piped)] == [
        ("some_package.client", "warn", "retrying")
    ]
