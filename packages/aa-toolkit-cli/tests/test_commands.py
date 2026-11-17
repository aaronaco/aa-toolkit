"""``aa commands``: machine-readable and human description of aa commands."""

import json
import re
from pathlib import Path
from typing import Annotated, Any

import pytest
import typer

from aa_cli.cli import app
from aa_cli.output import ExitCode

STORED_COPY = Path(__file__).with_name("commands.json")


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (["--json", "commands"], None),
        (["commands", "--json"], None),
        (["commands"], {"AA_JSON": "1"}),
    ],
    ids=["flag-before", "flag-after", "env"],
)
def test_commands_in_json_mode_prints_one_envelope_with_exit_codes_global_options_and_commands(
    aa, args: list[str], env: dict[str, str] | None
) -> None:
    result = aa(*args, env=env)

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    assert set(envelope["data"]) == {"exit_codes", "global_options", "commands"}


def test_listed_exit_codes_match_the_codes_and_meanings_defined_in_code(aa) -> None:
    result = aa("commands", "--json")

    assert result.exit_code == 0, result.output
    exit_codes = json.loads(result.stdout)["data"]["exit_codes"]
    assert exit_codes == [
        {"code": 0, "meaning": "ok"},
        {"code": 1, "meaning": "problems found"},
        {"code": 2, "meaning": "usage error"},
        {"code": 3, "meaning": "unexpected error"},
        {"code": 130, "meaning": "stopped with Ctrl+C"},
    ]
    assert [(item["code"], item["meaning"]) for item in exit_codes] == [
        (int(code), code.meaning) for code in ExitCode
    ]


def test_global_options_lists_json_verbose_and_version_once(aa) -> None:
    result = aa("commands", "--json")

    assert result.exit_code == 0, result.output
    global_options = json.loads(result.stdout)["data"]["global_options"]
    assert [opt["flag"] for opt in global_options] == ["--json", "--verbose", "--version"]
    for opt in global_options:
        assert opt["type"] == "boolean"
        assert opt["default"] is False
        assert opt["choices"] is None
        assert opt["required"] is False
        assert opt["repeatable"] is False
        assert opt["help"]


def _command_by_name(data: dict[str, Any], name: str) -> dict[str, Any]:
    by_name = {cmd["name"]: cmd for cmd in data["commands"]}
    return by_name[name]


def _option_by_flag(cmd: dict[str, Any], flag: str) -> dict[str, Any]:
    by_flag = {opt["flag"]: opt for opt in cmd["options"]}
    return by_flag[flag]


def test_add_entry_describes_piece_argument_choices_only_and_write_effect(aa) -> None:
    result = aa("commands", "--json")

    assert result.exit_code == 0, result.output
    add_cmd = _command_by_name(json.loads(result.stdout)["data"], "add")
    assert add_cmd["summary"] == "Add a piece to the project in the current folder."
    assert add_cmd["effect"] == "write"
    assert [arg["name"] for arg in add_cmd["arguments"]] == ["PIECE"]
    piece_arg = add_cmd["arguments"][0]
    assert piece_arg["type"] == "string"
    assert piece_arg["choices"] == ["ci", "log"]
    assert piece_arg["required"] is True
    assert piece_arg["help"]
    [only_opt] = add_cmd["options"]
    assert only_opt["flag"] == "--only"
    assert only_opt["type"] == "array"
    assert only_opt["items"] == "string"
    assert only_opt["default"] is None
    assert only_opt["required"] is False
    assert only_opt["repeatable"] is True
    for part in ("tests", "zizmor", "audit", "dependabot"):
        assert part in only_opt["help"]


def test_init_entry_describes_name_argument_options_and_write_effect(aa) -> None:
    result = aa("commands", "--json")

    assert result.exit_code == 0, result.output
    init_cmd = _command_by_name(json.loads(result.stdout)["data"], "init")
    assert init_cmd["summary"] == "Create a project in a new or empty folder."
    assert init_cmd["effect"] == "write"
    assert [arg["name"] for arg in init_cmd["arguments"]] == ["NAME"]
    name_arg = init_cmd["arguments"][0]
    assert name_arg["type"] == "string"
    assert name_arg["required"] is True
    assert name_arg["help"]

    license_opt = _option_by_flag(init_cmd, "--license")
    assert license_opt["type"] == "string"
    assert license_opt["choices"] == ["MIT", "none"]
    assert license_opt["default"] == "MIT"
    assert license_opt["required"] is False
    assert license_opt["repeatable"] is False
    assert license_opt["help"]

    for flag in ("--cli", "--lib", "--github", "--public", "--dry-run"):
        opt = _option_by_flag(init_cmd, flag)
        assert opt["type"] == "boolean"
        assert opt["default"] is False
        assert opt["choices"] is None
        assert opt["required"] is False
        assert opt["repeatable"] is False


def test_redact_entry_describes_optional_file_repeatable_with_and_without_check_and_read_effect(
    aa,
) -> None:
    result = aa("commands", "--json")

    assert result.exit_code == 0, result.output
    redact_cmd = _command_by_name(json.loads(result.stdout)["data"], "redact")
    assert redact_cmd["summary"] == "Print a cleaned copy of a file or piped text."
    assert redact_cmd["effect"] == "read"
    assert [arg["name"] for arg in redact_cmd["arguments"]] == ["FILE"]
    file_arg = redact_cmd["arguments"][0]
    assert file_arg["type"] == "string"
    assert file_arg["required"] is False
    assert file_arg["help"]

    for flag in ("--with", "--without"):
        opt = _option_by_flag(redact_cmd, flag)
        assert opt["type"] == "array"
        assert opt["items"] == "string"
        assert opt["default"] is None
        assert opt["choices"] is None
        assert opt["required"] is False
        assert opt["repeatable"] is True
        assert opt["help"]

    check_opt = _option_by_flag(redact_cmd, "--check")
    assert check_opt["type"] == "boolean"
    assert check_opt["default"] is False
    assert check_opt["choices"] is None
    assert check_opt["required"] is False
    assert check_opt["repeatable"] is False
    assert check_opt["help"]


def test_prune_entry_describes_optional_branches_dry_run_and_write_effect(aa) -> None:
    result = aa("commands", "--json")

    assert result.exit_code == 0, result.output
    prune_cmd = _command_by_name(json.loads(result.stdout)["data"], "prune")
    assert prune_cmd["summary"] == "Remove Finished branches and their worktrees."
    assert prune_cmd["effect"] == "write"
    assert [arg["name"] for arg in prune_cmd["arguments"]] == ["BRANCH"]
    branch_arg = prune_cmd["arguments"][0]
    assert branch_arg["type"] == "array"
    assert branch_arg["items"] == "string"
    assert branch_arg["required"] is False
    assert branch_arg["help"]
    assert [opt["flag"] for opt in prune_cmd["options"]] == ["--dry-run"]
    dry_run = prune_cmd["options"][0]
    assert dry_run["type"] == "boolean"
    assert dry_run["default"] is False
    assert dry_run["help"]


def test_commands_entry_is_listed_with_read_effect(aa) -> None:
    result = aa("commands", "--json")

    assert result.exit_code == 0, result.output
    commands_cmd = _command_by_name(json.loads(result.stdout)["data"], "commands")
    assert commands_cmd["summary"] == "List every command, its arguments, flags and exit codes."
    assert commands_cmd["effect"] == "read"
    assert commands_cmd["arguments"] == []
    assert commands_cmd["options"] == []


@pytest.mark.parametrize(
    ("name", "summary"),
    [
        ("secret set", "Save a Secret in the Secret store."),
        ("secret delete", "Delete a Secret from the Secret store."),
    ],
)
def test_secret_entries_are_listed_by_full_name_with_name_app_and_write_effect(
    aa, name: str, summary: str
) -> None:
    result = aa("commands", "--json")

    assert result.exit_code == 0, result.output
    cmd = _command_by_name(json.loads(result.stdout)["data"], name)
    assert cmd["summary"] == summary
    assert cmd["effect"] == "write"
    assert [arg["name"] for arg in cmd["arguments"]] == ["NAME"]
    name_arg = cmd["arguments"][0]
    assert name_arg["type"] == "string"
    assert name_arg["required"] is True
    assert name_arg["help"]
    assert [opt["flag"] for opt in cmd["options"]] == ["--app"]
    app_opt = cmd["options"][0]
    assert app_opt["type"] == "string"
    assert app_opt["default"] is None
    assert app_opt["choices"] is None
    assert app_opt["required"] is False
    assert app_opt["repeatable"] is False
    assert app_opt["help"]


def test_the_secret_group_is_not_listed_on_its_own(aa) -> None:
    result = aa("commands", "--json")

    assert result.exit_code == 0, result.output
    names = [cmd["name"] for cmd in json.loads(result.stdout)["data"]["commands"]]
    assert "secret" not in names


def test_a_command_with_no_declared_effect_fails_by_its_full_name(monkeypatch) -> None:
    from aa_cli import cli
    from aa_cli.commands import describe_cli

    effects = {k: v for k, v in cli.COMMAND_EFFECTS.items() if k != "secret delete"}

    with pytest.raises(KeyError, match="secret delete"):
        describe_cli(app, effects)


def test_crash_never_appears_and_no_command_repeats_global_flags(aa) -> None:
    json_result = aa("commands", "--json")
    human_result = aa("commands")

    assert json_result.exit_code == 0, json_result.output
    assert human_result.exit_code == 0, human_result.output
    assert "crash" not in json_result.stdout
    assert "crash" not in human_result.stdout

    data = json.loads(json_result.stdout)["data"]
    global_flags = {opt["flag"] for opt in data["global_options"]}
    assert global_flags == {"--json", "--verbose", "--version"}
    for cmd in data["commands"]:
        command_flags = {opt["flag"] for opt in cmd["options"]}
        assert command_flags.isdisjoint(global_flags), cmd["name"]


def test_commands_in_human_mode_prints_each_visible_command_with_its_summary(aa) -> None:
    result = aa("commands")

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert [re.split(r"\s{2,}", line, maxsplit=1) for line in result.stdout.splitlines()] == [
        ["add", "Add a piece to the project in the current folder."],
        ["init", "Create a project in a new or empty folder."],
        ["redact", "Print a cleaned copy of a file or piped text."],
        ["prune", "Remove Finished branches and their worktrees."],
        ["commands", "List every command, its arguments, flags and exit codes."],
        ["secret set", "Save a Secret in the Secret store."],
        ["secret delete", "Delete a Secret from the Secret store."],
    ]


def test_commands_json_matches_the_stored_copy(aa) -> None:
    result = aa("commands", "--json")

    assert result.exit_code == 0, result.output
    stored = json.loads(STORED_COPY.read_text(encoding="utf-8"))
    assert json.loads(result.stdout) == stored


def test_changing_a_commands_arguments_or_flags_without_updating_the_stored_copy_fails(
    aa, monkeypatch
) -> None:
    def init(
        ctx: typer.Context,
        name: Annotated[str, typer.Argument(help="The project name, also the folder it goes in.")],
        extra: Annotated[bool, typer.Option("--extra", help="An added flag.")] = False,
    ) -> None:
        """Create a project in a new or empty folder."""

    init_info = next(
        cmd for cmd in app.registered_commands if getattr(cmd.callback, "__name__", None) == "init"
    )
    monkeypatch.setattr(init_info, "callback", init)

    result = aa("commands", "--json")

    assert result.exit_code == 0, result.output
    stored = json.loads(STORED_COPY.read_text(encoding="utf-8"))
    with pytest.raises(AssertionError):
        assert json.loads(result.stdout) == stored
