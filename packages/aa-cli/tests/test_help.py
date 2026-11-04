import json
import re

import pytest
from typer import rich_utils

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@pytest.fixture(params=[False, True], ids=["plain-terminal", "color-forced"])
def color_forced(request, monkeypatch):
    """Run each help test as in a plain terminal and as with FORCE_COLOR or on GitHub Actions.

    Typer reads those variables once at import, so the switch is set on its module.
    """
    monkeypatch.setattr(rich_utils, "FORCE_TERMINAL", True if request.param else None)
    return request.param


def test_help_lists_the_global_flags(aa, color_forced):
    result = aa("--help")

    assert result.exit_code == 0
    text = ANSI_ESCAPE.sub("", result.stdout)
    for flag in ("--json", "--verbose", "--version"):
        assert flag in text


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (["--json", "--help"], None),
        (["--help"], {"AA_JSON": "1"}),
    ],
    ids=["flag", "env"],
)
def test_help_in_json_mode_is_one_envelope_of_plain_text(aa, color_forced, args, env):
    result = aa(*args, env=env)

    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    help_text = envelope["data"]["help"]
    assert "\x1b" not in help_text
    for flag in ("--json", "--verbose", "--version"):
        assert flag in help_text
