import json

import pytest


def test_unknown_flag_in_human_mode_prints_usage_to_stderr_and_exits_2(aa):
    result = aa("--bogus")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--bogus" in result.stderr
    assert "Usage:" in result.stderr


def test_doctor_is_an_unknown_command(aa):
    result = aa("doctor")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "No such command 'doctor'" in result.stderr


def test_doctor_in_json_mode_is_a_usage_envelope(aa):
    result = aa("doctor", "--json")

    assert result.exit_code == 2
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "usage"
    assert "doctor" in error["message"]


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (["--json", "--bogus"], None),
        (["--bogus"], {"AA_JSON": "1"}),
    ],
    ids=["flag", "env"],
)
def test_unknown_flag_in_json_mode_is_a_usage_envelope(aa, args, env):
    result = aa(*args, env=env)

    assert result.exit_code == 2
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "usage"
    assert "--bogus" in envelope["error"]["message"]
    assert "fix" in envelope["error"]
