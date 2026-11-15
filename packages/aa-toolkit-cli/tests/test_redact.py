"""``aa redact``: cleaning a file or piped text with the redaction library."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_redact_prints_a_cleaned_copy_of_a_file_and_leaves_the_file_unchanged(
    aa, tmp_path: Path
) -> None:
    log = tmp_path / "app.log"
    original = b"user=jane@corp.com\n"
    log.write_bytes(original)

    result = aa("redact", "app.log")

    assert result.exit_code == 0
    assert result.stdout == "user=[EMAIL]\n"
    assert log.read_bytes() == original


GITHUB_TOKEN = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0" * 2


def test_redact_with_no_file_cleans_piped_text_with_the_library_defaults(aa) -> None:
    result = aa("redact", stdin=f"user=jane@corp.com token={GITHUB_TOKEN}\n")

    assert result.exit_code == 0
    assert result.stdout == "user=[EMAIL] token=[REDACTED]\n"


def private_key(*, end: bool = True) -> str:
    lines = [
        "-----BEGIN " + "PRIVATE KEY-----",
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj",
        "MzEfYyjiWA4R4/M2bS1GB4t7NXp98C3SC6dVMvDuictGeurT8jNbvJZHtCSuYEvu",
    ]
    if end:
        lines.append("-----END " + "PRIVATE KEY-----")
    return "\n".join(lines) + "\n"


def test_a_private_key_spanning_several_lines_has_none_of_its_lines_in_the_output(aa) -> None:
    result = aa("redact", stdin=f"before\n{private_key()}after\n")

    assert result.exit_code == 0
    assert result.stdout == "before\n[PRIVATE_KEY]\nafter\n"
    assert "MIIEvQIB" not in result.stdout
    assert "PRIVATE KEY-----" not in result.stdout


def test_a_private_key_with_no_end_line_has_none_of_its_lines_in_the_output(aa) -> None:
    result = aa("redact", stdin=f"before\n{private_key(end=False)}")

    assert result.exit_code == 0
    assert result.stdout == "before\n[PRIVATE_KEY]\n"
    assert "MIIEvQIB" not in result.stdout
    assert "PRIVATE KEY-----" not in result.stdout


def test_redact_as_a_real_process_flushes_each_line_before_stdin_closes() -> None:
    aa_bin = shutil.which("aa", path=str(Path(sys.executable).parent))
    assert aa_bin is not None
    process = subprocess.Popen(
        [aa_bin, "redact"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        process.stdin.write(b"user=jane@corp.com\n")
        process.stdin.flush()
        line = process.stdout.readline()
        assert line == b"user=[EMAIL]\n"
        process.stdin.close()
        assert process.wait(timeout=5) == 0
    finally:
        process.kill()
        process.wait()


def test_crlf_line_endings_a_bom_and_invalid_utf8_bytes_are_kept_outside_placeholders(aa) -> None:
    raw = b"\xef\xbb\xbfprefix \xff\xfe user=jane@corp.com\r\nsecond \x80 line\r\n"

    result = aa("redact", stdin=raw)

    assert result.exit_code == 0
    assert (
        result.stdout_bytes == b"\xef\xbb\xbfprefix \xff\xfe user=[EMAIL]\r\nsecond \x80 line\r\n"
    )


def test_a_line_longer_than_64_kb_comes_out_whole_without_truncated(aa) -> None:
    padding = "x" * 70_000
    line = f"{padding} user=jane@corp.com tail\n"

    result = aa("redact", stdin=line)

    assert result.exit_code == 0
    assert result.stdout == f"{padding} user=[EMAIL] tail\n"
    assert "[TRUNCATED]" not in result.stdout


def test_output_to_a_terminal_is_shown_as_text(aa, monkeypatch) -> None:
    from typer import testing

    monkeypatch.setattr(testing._NamedTextIOWrapper, "isatty", lambda self: self.name == "<stdout>")

    result = aa("redact", stdin=b"hi \xff user=jane@corp.com\n")

    assert result.exit_code == 0
    assert b"\xff" not in result.stdout_bytes
    assert result.stdout == "hi \ufffd user=[EMAIL]\n"


def test_with_turns_on_ip_address_and_phone_in_any_case_with_commas_or_repetition(aa) -> None:
    text = "from 203.0.113.7 call +1 555 123 4567\n"

    comma = aa("redact", "--with", "ip_address,PHONE", stdin=text)
    repeated = aa("redact", "--with", "IP_ADDRESS", "--with", "phone", stdin=text)

    assert comma.exit_code == 0
    assert comma.stdout == "from [IP_ADDRESS] call [PHONE]\n"
    assert repeated.exit_code == 0
    assert repeated.stdout == "from [IP_ADDRESS] call [PHONE]\n"


def test_without_leaves_named_kinds_visible_and_hides_the_rest(aa) -> None:
    text = f"card 4111111111111111 user=jane@corp.com gh={GITHUB_TOKEN}\n"

    one = aa("redact", "--without", "CARD", stdin=text)
    two_repeated = aa("redact", "--without", "card", "--without", "EMAIL", stdin=text)
    two_comma = aa("redact", "--without", "card,email", stdin=text)

    assert one.exit_code == 0
    assert one.stdout == "card 4111111111111111 user=[EMAIL] gh=[GITHUB_TOKEN]\n"
    assert two_repeated.exit_code == 0
    assert two_repeated.stdout == "card 4111111111111111 user=jane@corp.com gh=[GITHUB_TOKEN]\n"
    assert two_comma.exit_code == 0
    assert two_comma.stdout == "card 4111111111111111 user=jane@corp.com gh=[GITHUB_TOKEN]\n"


WITH_ACCEPTED = ("IP_ADDRESS", "PHONE")
WITHOUT_ACCEPTED = (
    "AWS_ACCESS_KEY",
    "GITHUB_TOKEN",
    "API_KEY",
    "SLACK_TOKEN",
    "JWT",
    "BEARER_TOKEN",
    "PRIVATE_KEY",
    "URL_PASSWORD",
    "EMAIL",
    "CARD",
)


@pytest.mark.parametrize(
    ("flag", "value", "accepted"),
    [
        ("--with", "EMAIL", WITH_ACCEPTED),
        ("--with", "BOGUS", WITH_ACCEPTED),
        ("--without", "IP_ADDRESS", WITHOUT_ACCEPTED),
        ("--without", "BOGUS", WITHOUT_ACCEPTED),
    ],
)
def test_an_unaccepted_kind_exits_2_with_a_usage_error_listing_the_accepted_kinds(
    aa, flag: str, value: str, accepted: tuple[str, ...]
) -> None:
    human = aa("redact", flag, value, stdin="text\n")
    as_json = aa("redact", flag, value, "--json", stdin="text\n")

    assert human.exit_code == 2
    assert as_json.exit_code == 2
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "usage"
    for kind in accepted:
        assert kind in human.stderr
        assert kind in error["message"]


def test_redact_help_lists_the_kinds_each_flag_takes(aa) -> None:
    result = aa("redact", "--help")

    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stdout)
    for kind in (*WITH_ACCEPTED, *WITHOUT_ACCEPTED):
        assert kind in plain


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (["--json", "redact"], None),
        (["redact", "--json"], None),
        (["redact"], {"AA_JSON": "1"}),
    ],
    ids=["flag-before", "flag-after", "env"],
)
def test_json_mode_prints_one_envelope_with_the_cleaned_text_and_replacement_chars(
    aa, args: list[str], env: dict[str, str] | None
) -> None:
    result = aa(*args, stdin=b"hi \xff user=jane@corp.com\r\n", env=env)

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "ok": True,
        "data": {"text": "hi \ufffd user=[EMAIL]\r\n"},
    }


def test_no_file_with_terminal_stdin_exits_2_with_a_hint_to_give_a_file_or_pipe_text(
    aa,
) -> None:
    human = aa("redact")
    as_json = aa("redact", "--json")

    assert human.exit_code == 2
    assert "file" in human.stderr.lower()
    assert "pipe" in human.stderr.lower()
    assert as_json.exit_code == 2
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "usage"
    assert "file" in error["message"].lower()
    assert "pipe" in error["message"].lower()


def test_a_missing_file_exits_1_with_file_not_found_naming_the_path(aa) -> None:
    human = aa("redact", "missing.log")
    as_json = aa("redact", "missing.log", "--json")

    assert human.exit_code == 1
    assert "missing.log" in human.stderr
    assert as_json.exit_code == 1
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "file_not_found"
    assert "missing.log" in error["message"]


def test_a_folder_exits_1_with_cannot_read(aa, tmp_path: Path) -> None:
    folder = tmp_path / "logs"
    folder.mkdir()

    human = aa("redact", "logs")
    as_json = aa("redact", "logs", "--json")

    assert human.exit_code == 1
    assert "logs" in human.stderr
    assert "folder" in human.stderr
    assert as_json.exit_code == 1
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "cannot_read"
    assert "logs" in error["message"]
    assert "folder" in error["message"]


def test_an_unreadable_file_exits_1_with_cannot_read_saying_why(
    aa, tmp_path: Path, monkeypatch
) -> None:
    log = tmp_path / "locked.log"
    log.write_text("user=jane@corp.com\n", encoding="utf-8")
    real_open = Path.open

    def deny(self: Path, *args, **kwargs):
        if self.name == "locked.log":
            raise PermissionError(13, "Permission denied", str(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny)

    result = aa("redact", "locked.log", "--json")

    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "cannot_read"
    assert "locked.log" in error["message"]
    assert "Permission denied" in error["message"]


def test_a_broken_pipe_while_writing_output_is_not_reported_as_cannot_read(
    aa, tmp_path: Path, monkeypatch
) -> None:
    import errno

    from aa_cli import redact as redact_mod

    log = tmp_path / "app.log"
    log.write_text("user=jane@corp.com\n", encoding="utf-8")

    def broken_write(_chunk: str) -> None:
        raise BrokenPipeError(errno.EPIPE, "Broken pipe")

    monkeypatch.setattr(redact_mod, "_write_chunk", broken_write)

    result = aa("redact", "app.log")

    assert "cannot read" not in result.stderr
    assert result.stderr == ""


def test_a_failing_detector_exits_3_with_unexpected_and_no_input_text_in_the_message(
    aa, monkeypatch
) -> None:
    from aa_redact import _detectors

    def broken(text: str):
        raise ValueError(f"boom while reading {text}")

    monkeypatch.setitem(_detectors.BUILT_IN, "EMAIL", broken)
    raw_line = "private-line-987654\n"

    human = aa("redact", "--verbose", stdin=raw_line)
    as_json = aa("redact", "--verbose", "--json", stdin=raw_line)

    assert human.exit_code == 3
    assert "private-line-987654" not in human.stderr
    assert "private-line-987654" not in human.stdout
    assert as_json.exit_code == 3
    assert "private-line-987654" not in as_json.stderr
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "unexpected"
    assert "private-line-987654" not in error["message"]


def test_ctrl_c_exits_130_with_aborted_and_keeps_lines_already_printed(
    aa, tmp_path: Path, monkeypatch
) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"first=jane@corp.com\nsecond=bob@corp.com\n")
    real_open = Path.open

    class InterruptedFile:
        def __init__(self, stream):
            self._stream = stream
            self._lines = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self._stream.close()

        def readline(self):
            self._lines += 1
            if self._lines > 1:
                raise KeyboardInterrupt
            return self._stream.readline()

    def open_interrupted(self: Path, *args, **kwargs):
        stream = real_open(self, *args, **kwargs)
        return InterruptedFile(stream) if self.name == "app.log" else stream

    monkeypatch.setattr(Path, "open", open_interrupted)

    result = aa("redact", "app.log")

    assert result.exit_code == 130
    assert result.stdout == "first=[EMAIL]\n"
    assert "Aborted" in result.stderr
