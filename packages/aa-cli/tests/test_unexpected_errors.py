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
