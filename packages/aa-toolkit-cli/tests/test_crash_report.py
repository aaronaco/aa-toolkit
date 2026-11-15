"""The Crash report module on its own, with cleaning functions that do nothing or misbehave."""

import platform
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from aa_cli.crash import REDACTION_FAILED, REVIEW_LINE, crash_folder, save_report

NOW = datetime(2026, 11, 16, 14, 12, 5)


def unchanged(text: str) -> str:
    return text


def failing(exc: BaseException) -> BaseException:
    """Return ``exc`` after raising it, so it carries a real traceback."""
    try:
        raise exc
    except BaseException as caught:
        return caught


def save(folder: Path, exc: BaseException, redact=unchanged, now: datetime = NOW, **fields) -> Path:
    message = f"{type(exc).__name__}: {exc}"
    defaults = {"app": "aa", "version": "0.1.0", "command": "init", "message": message}
    return save_report(exc, folder=folder, redact=redact, now=now, **{**defaults, **fields})


def test_a_report_starts_with_the_review_line_and_holds_versions_command_and_traceback(tmp_path):
    try:
        try:
            raise ValueError("first problem")
        except ValueError as exc:
            raise KeyError("name") from exc
    except KeyError as exc:
        path = save(tmp_path, exc)

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "# aa crash report"
    assert lines[1] == REVIEW_LINE
    assert (
        f"aa 0.1.0 · Python {platform.python_version()} · "
        f"{platform.system()} {platform.version()}" in lines
    )
    assert "Command: aa init" in lines
    traceback_block = text.split("```\n")[1]
    assert traceback_block.startswith("Traceback (most recent call last):")
    assert "ValueError: first problem" in traceback_block
    assert "direct cause" in traceback_block
    assert "KeyError: 'name'" in traceback_block
    assert text.rstrip().endswith("```")


def test_a_report_is_named_by_local_date_and_time_in_the_folder(tmp_path):
    path = save(tmp_path / "aa" / "crash", failing(RuntimeError("boom")))

    assert path == tmp_path / "aa" / "crash" / "2026-11-16-141205.md"
    assert path.is_file()


@pytest.mark.parametrize(
    "spell",
    [str, str.upper, str.lower, lambda home: home.replace("\\", "/")],
    ids=["as-is", "upper", "lower", "forward-slashes"],
)
def test_a_cleaning_function_that_changes_nothing_still_hides_home_and_computer(tmp_path, spell):
    home = spell(str(Path.home()))
    computer = platform.node()
    exc = failing(RuntimeError(f"cannot open {home}\\.aa\\cache on {computer.lower()}"))

    text = save(tmp_path, exc).read_text(encoding="utf-8")

    assert "cannot open [HOME]\\.aa\\cache on [COMPUTER]" in text
    assert home not in text
    assert computer.lower() not in text.lower()


def test_home_is_hidden_as_a_whole_path_and_not_inside_a_longer_folder_name(tmp_path):
    home = str(Path.home())
    exc = failing(RuntimeError(f"{home}2\\notes"))

    text = save(tmp_path, exc).read_text(encoding="utf-8")

    assert f"{home}2\\notes" in text


@pytest.mark.parametrize(
    "redact",
    [lambda text: 1 / 0, lambda text: None, lambda text: b"bytes"],
    ids=["raises", "returns-none", "returns-bytes"],
)
def test_a_broken_cleaning_function_writes_redaction_failed_and_never_the_raw_text(
    tmp_path, redact
):
    exc = failing(RuntimeError("secret-value-123"))

    text = save(tmp_path, exc, redact=redact).read_text(encoding="utf-8")

    assert "secret-value-123" not in text
    assert text.count(REDACTION_FAILED) == 2  # the message and the traceback, each on its own


def test_only_the_message_and_the_traceback_go_through_the_cleaning_function(tmp_path):
    seen: list[str] = []

    def record(text: str) -> str:
        seen.append(text)
        return "CLEANED"

    exc = failing(RuntimeError("boom"))

    text = save(tmp_path, exc, redact=record).read_text(encoding="utf-8")

    assert len(seen) == 2
    assert seen[0] == "RuntimeError: boom"
    assert seen[1].startswith("Traceback (most recent call last):")
    assert "Error: CLEANED" in text
    assert "```\nCLEANED\n```" in text
    assert "aa 0.1.0" in text
    assert "Command: aa init" in text


def test_no_command_names_just_the_app(tmp_path):
    text = save(tmp_path, failing(RuntimeError("boom")), command=None).read_text(encoding="utf-8")

    assert "Command: aa\n" in text


def test_two_crashes_in_the_same_second_keep_both_reports(tmp_path):
    first = save(tmp_path, failing(RuntimeError("first")))
    second = save(tmp_path, failing(RuntimeError("second")))

    assert first != second
    assert "RuntimeError: first" in first.read_text(encoding="utf-8")
    assert "RuntimeError: second" in second.read_text(encoding="utf-8")


def test_an_eleventh_report_leaves_only_the_newest_ten(tmp_path):
    saved = [
        save(tmp_path, failing(RuntimeError(f"crash {n}")), now=NOW + timedelta(seconds=n))
        for n in range(11)
    ]

    remaining = sorted(tmp_path.iterdir())
    assert remaining == sorted(saved[1:])
    assert not saved[0].exists()


def test_keeping_the_newest_ten_orders_same_second_reports_by_when_they_were_saved(tmp_path):
    saved = [save(tmp_path, failing(RuntimeError(f"crash {n}"))) for n in range(11)]

    assert sorted(tmp_path.iterdir()) == sorted(saved[1:])


def test_keeping_the_newest_ten_leaves_other_files_in_the_folder_alone(tmp_path):
    other = tmp_path / "notes.md"
    other.write_text("mine", encoding="utf-8")

    for n in range(11):
        save(tmp_path, failing(RuntimeError("boom")), now=NOW + timedelta(seconds=n))

    assert other.read_text(encoding="utf-8") == "mine"
    assert len(list(tmp_path.glob("2026-*.md"))) == 10


def test_the_crash_folder_is_under_localappdata():
    folder = crash_folder("aa", {"LOCALAPPDATA": "C:\\Users\\me\\AppData\\Local"})

    assert folder == Path("C:\\Users\\me\\AppData\\Local") / "aa" / "crash"


@pytest.mark.parametrize("environ", [{}, {"LOCALAPPDATA": ""}, {"LOCALAPPDATA": "relative"}])
def test_without_a_usable_localappdata_the_crash_folder_is_under_the_home_folder(environ):
    folder = crash_folder("aa", environ)

    assert folder == Path.home() / "AppData" / "Local" / "aa" / "crash"
