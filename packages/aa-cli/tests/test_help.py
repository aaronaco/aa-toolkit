import json

import pytest


def test_help_lists_the_global_flags(aa):
    result = aa("--help")

    assert result.exit_code == 0
    for flag in ("--json", "--verbose", "--version"):
        assert flag in result.stdout


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (["--json", "--help"], None),
        (["--help"], {"AA_JSON": "1"}),
    ],
    ids=["flag", "env"],
)
def test_help_in_json_mode_is_one_envelope(aa, args, env):
    result = aa(*args, env=env)

    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    for flag in ("--json", "--verbose", "--version"):
        assert flag in envelope["data"]["help"]
