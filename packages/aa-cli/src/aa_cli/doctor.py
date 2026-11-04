"""Checks: conditions ``aa doctor`` verifies about the machine and the project."""

import logging
import shutil
import sys
import tomllib
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from aa_cli.git import machine_config
from aa_cli.process import run

log = logging.getLogger("aa")


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INFO = "info"


class Scope(StrEnum):
    MACHINE = "machine"
    PROJECT = "project"


@dataclass(frozen=True)
class Check:
    id: str
    scope: Scope
    status: Status
    message: str
    fix: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def machine_checks() -> list[Check]:
    """Every machine check, in order. All of them run, even after a failure."""
    return preflight_checks(github=True)


def preflight_checks(github: bool) -> list[Check]:
    """The machine checks ``aa init`` needs to pass: uv, git and the git identity.

    With ``github``, also gh and the gh sign-in.
    """
    uv = _on_path("uv")
    git = _on_path("git")
    git_identity = _needs(git, "git_identity") or _git_identity()
    if not github:
        return [uv, git, git_identity]
    gh = _on_path("gh")
    gh_auth = _needs(gh, "gh_auth") or _gh_auth()
    return [uv, git, git_identity, gh, gh_auth]


def _needs(dependency: Check, check_id: str) -> Check | None:
    """A failure pointing at ``dependency`` when it failed, else None so the check runs."""
    if dependency.status is not Status.FAIL:
        return None
    message = f"needs the {dependency.id} check, which failed"
    return Check(check_id, dependency.scope, Status.FAIL, message, dependency.fix)


def project_checks(start: Path) -> list[Check]:
    """The project's checks, or a single "not a project" result outside one."""
    if find_project(start) is None:
        return [Check("project", Scope.PROJECT, Status.INFO, "not a project")]
    return []


def find_project(start: Path) -> Path | None:
    """The folder of the nearest pyproject above ``start``, if it has ``[tool.aa]``."""
    for folder in (start, *start.parents):
        pyproject = folder / "pyproject.toml"
        if pyproject.is_file():
            try:
                config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                log.debug("Cannot read %s: %s", pyproject, exc)
                return None
            tool = config.get("tool")
            return folder if isinstance(tool, dict) and "aa" in tool else None
    return None


_MARKS = {Status.PASS: "[ok]  ", Status.FAIL: "[fail]", Status.INFO: "[info]"}
_HEADINGS = {Scope.MACHINE: "Machine", Scope.PROJECT: "Project"}


def render(checks: list[Check]) -> str:
    """One line per check under its scope's heading, with the fix under a failure."""
    lines: list[str] = []
    for scope, heading in _HEADINGS.items():
        scoped = [check for check in checks if check.scope is scope]
        if not scoped:
            continue
        lines.append(heading)
        for check in scoped:
            lines.append(f"  {_MARKS[check.status]} {check.id}: {check.message}")
            if check.status is Status.FAIL and check.fix:
                lines.append(f"         fix: {check.fix}")
    return "\n".join(lines)


# The command that installs each tool, per platform.
_INSTALL = {
    "uv": {
        "win32": "winget install --id astral-sh.uv -e",
        "other": "curl -LsSf https://astral.sh/uv/install.sh | sh",
    },
    "git": {"win32": "winget install --id Git.Git -e", "other": "sudo apt install git"},
    "gh": {"win32": "winget install --id GitHub.cli -e", "other": "sudo apt install gh"},
}


def _install_command(tool: str) -> str:
    commands = _INSTALL[tool]
    return commands["win32"] if sys.platform == "win32" else commands["other"]


def _on_path(tool: str) -> Check:
    path = shutil.which(tool)
    if path is None:
        return Check(tool, Scope.MACHINE, Status.FAIL, "not found on PATH", _install_command(tool))
    return Check(tool, Scope.MACHINE, Status.PASS, f"found at {path}")


_IDENTITY_PLACEHOLDERS = {"user.name": "Your Name", "user.email": "you@example.com"}


def _git_identity() -> Check:
    values = {key: machine_config(key) for key in _IDENTITY_PLACEHOLDERS}
    missing = [key for key, value in values.items() if not value]
    if missing:
        fix = "; ".join(
            f'git config --global {key} "{_IDENTITY_PLACEHOLDERS[key]}"' for key in missing
        )
        message = f"{' and '.join(missing)} not set"
        return Check("git_identity", Scope.MACHINE, Status.FAIL, message, fix)
    message = f"{values['user.name']} <{values['user.email']}>"
    return Check("git_identity", Scope.MACHINE, Status.PASS, message)


def _gh_auth() -> Check:
    if run("gh", "auth", "status", "--hostname", "github.com").returncode != 0:
        message = "not signed in to github.com"
        return Check("gh_auth", Scope.MACHINE, Status.FAIL, message, "gh auth login")
    return Check("gh_auth", Scope.MACHINE, Status.PASS, "signed in to github.com")
