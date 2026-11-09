"""Problems while setting up logging: reported on stderr, and never a crash."""

import json
import sys

import pytest

from aa_log import configure_logging, get_logger


def lines(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def warnings(stream):
    return [line["message"] for line in lines(stream) if line["level"] == "warn"]


def test_a_bad_aa_log_level_warns_and_uses_the_default(piped, monkeypatch):
    monkeypatch.setenv("AA_LOG_LEVEL", "loud")
    configure_logging()

    get_logger("my_app").debug("hidden")
    get_logger("my_app").info("shown")

    assert len(warnings(piped)) == 1
    assert "AA_LOG_LEVEL" in warnings(piped)[0]
    assert "loud" in warnings(piped)[0]
    assert [line["message"] for line in lines(piped)][1:] == ["shown"]


def test_a_bad_aa_log_level_falls_back_to_the_level_the_app_picked(piped, monkeypatch):
    monkeypatch.setenv("AA_LOG_LEVEL", "loud")
    configure_logging(level="ERROR")

    get_logger("my_app").info("hidden")
    get_logger("my_app").error("shown")

    assert [line["message"] for line in lines(piped)][1:] == ["shown"]


def test_a_bad_level_argument_warns_and_uses_info(piped):
    configure_logging(level="loud")

    get_logger("my_app").debug("hidden")
    get_logger("my_app").info("shown")

    assert "loud" in warnings(piped)[0]
    assert [line["message"] for line in lines(piped)][1:] == ["shown"]


def test_a_bad_aa_log_format_warns_and_keeps_the_automatic_choice(piped, monkeypatch):
    monkeypatch.setenv("AA_LOG_FORMAT", "yaml")
    configure_logging()

    get_logger("my_app").info("shown")

    assert len(warnings(piped)) == 1
    assert "AA_LOG_FORMAT" in warnings(piped)[0]
    assert "yaml" in warnings(piped)[0]
    assert lines(piped)[1]["message"] == "shown"


def test_a_bad_aa_log_format_on_a_terminal_keeps_the_readable_style(terminal, monkeypatch):
    monkeypatch.setenv("AA_LOG_FORMAT", "yaml")
    configure_logging()

    get_logger("my_app").info("shown")

    assert "AA_LOG_FORMAT" in terminal.getvalue()
    assert "shown" in terminal.getvalue()
    assert not terminal.getvalue().startswith("{")


def test_the_warning_shows_even_when_the_level_would_hide_warnings(piped, monkeypatch):
    monkeypatch.setenv("AA_LOG_FORMAT", "yaml")
    configure_logging(level="CRITICAL")

    assert len(warnings(piped)) == 1


@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_level_variable_counts_as_not_set(piped, monkeypatch, empty):
    monkeypatch.setenv("AA_LOG_LEVEL", empty)
    configure_logging(level="ERROR")

    get_logger("my_app").info("hidden")
    get_logger("my_app").error("shown")

    assert [line["message"] for line in lines(piped)] == ["shown"]


@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_format_variable_counts_as_not_set(piped, monkeypatch, empty):
    monkeypatch.setenv("AA_LOG_FORMAT", empty)
    configure_logging()

    get_logger("my_app").info("shown")

    assert [line["message"] for line in lines(piped)] == ["shown"]


@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_file_variable_counts_as_not_set(piped, tmp_path, monkeypatch, empty):
    path = tmp_path / "code.log"
    monkeypatch.setenv("AA_LOG_FILE", empty)
    configure_logging(file=path)

    get_logger("my_app").info("saved")

    assert json.loads(path.read_text(encoding="utf-8"))["message"] == "saved"


def test_a_log_file_that_cannot_be_opened_warns_and_logs_stay_on_screen(piped, tmp_path):
    folder = tmp_path / "a_folder"
    folder.mkdir()
    configure_logging(file=folder)

    get_logger("my_app").info("shown")

    assert len(warnings(piped)) == 1
    assert str(folder) in warnings(piped)[0]
    assert lines(piped)[1]["message"] == "shown"


def test_a_log_file_whose_folder_cannot_be_created_warns_and_logs_stay_on_screen(piped, tmp_path):
    blocker = tmp_path / "a_file"
    blocker.write_text("")
    configure_logging(file=blocker / "app.log")

    get_logger("my_app").info("shown")

    assert len(warnings(piped)) == 1
    assert lines(piped)[1]["message"] == "shown"


@pytest.mark.parametrize("bad_path", ["bad\0name.log", 123])
def test_a_log_file_path_that_is_not_a_path_warns_and_logs_stay_on_screen(piped, bad_path):
    configure_logging(file=bad_path)

    get_logger("my_app").info("shown")

    assert len(warnings(piped)) == 1
    assert lines(piped)[1]["message"] == "shown"


def test_an_app_with_no_stderr_keeps_running(monkeypatch):
    # A Windows app started without a console has sys.stderr set to None.
    monkeypatch.setattr(sys, "stderr", None)

    configure_logging()
    get_logger("my_app").info("nowhere to go")


def test_a_closed_stderr_keeps_the_app_running(piped):
    piped.close()

    configure_logging()


def test_a_closed_stderr_with_a_problem_to_report_keeps_the_app_running(piped, monkeypatch):
    monkeypatch.setenv("AA_LOG_FORMAT", "yaml")
    piped.close()

    configure_logging()


def test_a_terminal_stream_without_a_file_number_keeps_the_app_running(monkeypatch):
    class Bare:
        def isatty(self):
            return True

        def write(self, text):
            pass

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stderr", Bare())

    configure_logging()


def test_a_line_break_in_a_bad_log_file_path_cannot_add_a_line_to_the_logs(
    piped, tmp_path, monkeypatch
):
    blocker = tmp_path / "a_file"
    blocker.write_text("")
    monkeypatch.setenv("AA_LOG_FORMAT", "text")
    monkeypatch.setenv("AA_LOG_FILE", str(blocker / "x\nERROR  forged" / "app.log"))

    configure_logging()

    assert len(piped.getvalue().splitlines()) == 1
