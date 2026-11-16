"""Unexpected errors, driven through the hidden ``aa crash`` command."""

import json

import pytest


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (["--json", "crash"], None),
        (["crash", "--json"], None),
        (["crash"], {"AA_JSON": "1"}),
    ],
    ids=["flag-before", "flag-after", "env"],
)
def test_uncaught_exception_in_json_mode_is_an_unexpected_envelope(aa, args, env):
    result = aa(*args, env=env)

    assert result.exit_code == 3
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "unexpected"
    assert envelope["error"]["message"]
    assert "\n" not in envelope["error"]["message"]
    assert "Traceback" not in result.stderr


def test_uncaught_exception_in_human_mode_exits_3_without_a_traceback(aa):
    result = aa("crash")

    assert result.exit_code == 3
    assert result.stdout == ""
    assert result.stderr.strip()
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("args", [["--verbose", "crash"], ["crash", "--verbose", "--json"]])
def test_verbose_puts_the_traceback_on_stderr_only(aa, args):
    result = aa(*args)

    assert result.exit_code == 3
    assert "Traceback" in result.stderr
    assert "Traceback" not in result.stdout


# Crash reports


def only_report(crash_folder):
    reports = list(crash_folder.iterdir())
    assert len(reports) == 1
    return reports[0]


def test_crash_in_json_mode_names_the_saved_report_by_its_full_path_in_fix(aa, crash_folder):
    result = aa("crash", "--json")

    assert result.exit_code == 3
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "unexpected"
    assert error["message"] == "RuntimeError: aa crash was asked to fail"
    report = only_report(crash_folder)
    assert report.is_absolute()
    assert error["fix"] == f"Attach {report} to a bug report"
    assert "%" not in error["fix"]


def test_crash_in_human_mode_prints_a_fix_line_naming_the_report_and_no_traceback(aa, crash_folder):
    result = aa("crash")

    assert result.exit_code == 3
    assert result.stdout == ""
    report = only_report(crash_folder)
    assert f"Fix: Attach {report} to a bug report" in result.stderr.splitlines()
    assert "Traceback" not in result.stderr


def test_a_failing_init_reports_only_the_command_name_never_its_arguments(
    aa, crash_folder, monkeypatch
):
    def broken_step(*args, **kwargs):
        raise KeyError("name")

    monkeypatch.setattr("aa_cli.cli.create_project", broken_step)

    result = aa("--json", "init", "my-secret-app")

    assert result.exit_code == 3
    text = only_report(crash_folder).read_text(encoding="utf-8")
    assert "Command: aa init\n" in text
    assert "KeyError: 'name'" in text
    assert "my-secret-app" not in text


def test_a_github_token_in_the_message_is_hidden_in_the_report_and_the_envelope(
    aa, crash_folder, monkeypatch
):
    token = "ghp_" + "a1B2" * 9

    def broken_step(*args, **kwargs):
        raise RuntimeError(f"push refused for {token}")

    monkeypatch.setattr("aa_cli.cli.create_project", broken_step)

    result = aa("init", "demo", "--json")

    assert result.exit_code == 3
    error = json.loads(result.stdout)["error"]
    assert error["message"] == "RuntimeError: push refused for [GITHUB_TOKEN]"
    text = only_report(crash_folder).read_text(encoding="utf-8")
    assert "[GITHUB_TOKEN]" in text
    assert token not in text
    assert token not in result.stdout


def test_a_usage_error_saves_no_report(aa, crash_folder):
    result = aa("init", "--bogus", "--json")

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "usage"
    assert not crash_folder.exists()


def test_ctrl_c_saves_no_report(aa, crash_folder, monkeypatch):
    def press_ctrl_c(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("aa_cli.cli.create_project", press_ctrl_c)

    result = aa("init", "demo", "--json")

    assert result.exit_code == 130
    assert json.loads(result.stdout)["error"]["code"] == "aborted"
    assert not crash_folder.exists()


@pytest.mark.parametrize("args", [["crash", "--json"], ["crash"]], ids=["json", "human"])
def test_an_unwritable_crash_folder_gives_the_old_answer_with_no_fix_and_no_traceback(
    aa, local_app_data, args
):
    (local_app_data / "aa").write_text("a file where the folder should be", encoding="utf-8")

    result = aa(*args)

    assert result.exit_code == 3
    assert "Traceback" not in result.stdout + result.stderr
    if "--json" in args:
        assert json.loads(result.stdout) == {
            "ok": False,
            "error": {
                "code": "unexpected",
                "message": "RuntimeError: aa crash was asked to fail",
                "fix": None,
            },
        }
    else:
        assert result.stderr == "Error: RuntimeError: aa crash was asked to fail\n"


def test_a_redactor_that_raises_hides_the_message_and_still_saves_a_report(
    aa, crash_folder, monkeypatch
):
    def broken_redactor(*args, **kwargs):
        def redact(text):
            raise ValueError("detector broke")

        return redact

    monkeypatch.setattr("aa_cli.cli.build_redactor", broken_redactor)

    result = aa("crash", "--json")

    assert result.exit_code == 3
    error = json.loads(result.stdout)["error"]
    assert error["message"] == "[REDACTION FAILED]"
    report = only_report(crash_folder)
    assert "aa crash was asked to fail" not in report.read_text(encoding="utf-8")
    assert error["fix"] == f"Attach {report} to a bug report"


def test_a_redactor_that_cannot_be_built_hides_the_message_and_still_saves_a_report(
    aa, crash_folder, monkeypatch
):
    def unbuildable(*args, **kwargs):
        raise ValueError("bad kinds")

    monkeypatch.setattr("aa_cli.cli.build_redactor", unbuildable)

    result = aa("crash", "--json")

    assert result.exit_code == 3
    error = json.loads(result.stdout)["error"]
    assert error["message"] == "[REDACTION FAILED]"
    assert "aa crash was asked to fail" not in only_report(crash_folder).read_text(encoding="utf-8")
    assert "Traceback" not in result.stderr
