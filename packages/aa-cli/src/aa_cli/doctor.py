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
from aa_cli.init import CI_WORKFLOW, PYTHON_VERSION, Kind
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
    gh = _on_path("gh")
    gh_auth = _needs(gh, "gh_auth") or _gh_auth()
    return [*preflight_checks(), gh, gh_auth]


def preflight_checks() -> list[Check]:
    """The machine checks ``aa init`` needs to pass: uv, git and the git identity."""
    uv = _on_path("uv")
    git = _on_path("git")
    git_identity = _needs(git, "git_identity") or _git_identity()
    return [uv, git, git_identity]


def _needs(dependency: Check, check_id: str, scope: Scope | None = None) -> Check | None:
    """A failure pointing at ``dependency`` when it failed, else None so the check runs.

    The failure is in ``scope``, by default the dependency's own.
    """
    if dependency.status is not Status.FAIL:
        return None
    message = f"needs the {dependency.id} check, which failed"
    return Check(check_id, scope or dependency.scope, Status.FAIL, message, dependency.fix)


def project_checks(start: Path) -> list[Check]:
    """The project's checks, in order, or a single "not a project" result outside one."""
    root = find_project(start)
    if root is None:
        return [Check("project", Scope.PROJECT, Status.INFO, "not a project")]
    project = _Project(root, start)
    return [
        _aa_config(project),
        _python_version(project),
        _needs(_on_path("uv"), "lockfile", Scope.PROJECT) or _lockfile(project),
        _file_exists("agents_md", project, "AGENTS.md", "how to install, test, lint and commit"),
        _file_exists("ci", project, CI_WORKFLOW, "a workflow that runs ruff and pytest"),
    ]


@dataclass(frozen=True)
class _Project:
    root: Path
    here: Path  # the folder aa ran in: the root or a folder under it

    def cd_to_root(self, command: str) -> str:
        """``command`` with a ``cd`` to the root first, unless aa already ran there."""
        if self.here == self.root:
            return command
        # Single quotes keep $ and ` literal in PowerShell and in sh. A path that
        # holds a single quote can't go in them, so it falls back to double quotes.
        root = str(self.root)
        quoted = f'"{root}"' if "'" in root else f"'{root}'"
        return f"cd {quoted}; {command}"


def find_project(start: Path) -> Path | None:
    """The folder of the nearest pyproject above ``start``, if it has ``[tool.aa]``."""
    for folder in (start, *start.parents):
        pyproject = folder / "pyproject.toml"
        if pyproject.is_file():
            tool = (_read_pyproject(pyproject) or {}).get("tool")
            return folder if isinstance(tool, dict) and "aa" in tool else None
    return None


def _read_pyproject(pyproject: Path) -> dict[str, Any] | None:
    """The parsed pyproject, or None when it can't be read. A leading BOM is allowed."""
    try:
        return tomllib.loads(pyproject.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        log.debug("Cannot read %s: %s", pyproject, exc)
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


def _aa_config(project: _Project) -> Check:
    pyproject = project.root / "pyproject.toml"
    # find_project already read this file and found [tool.aa] in it.
    aa = (_read_pyproject(pyproject) or {}).get("tool", {}).get("aa")
    kind = aa.get("kind") if isinstance(aa, dict) else None
    if isinstance(kind, str) and kind in Kind:
        return Check("aa_config", Scope.PROJECT, Status.PASS, f"kind is {kind}")
    kinds = " or ".join(f'"{choice}"' for choice in Kind)
    fix = f"Set kind = {kinds} under [tool.aa] in {pyproject}"
    if not isinstance(aa, dict):
        message = "[tool.aa] is not a table"
    elif kind is None:
        message = "[tool.aa] has no kind"
    else:
        message = f"kind {kind!r} is not one of {', '.join(Kind)}"
    return Check("aa_config", Scope.PROJECT, Status.FAIL, message, fix)


def _python_version(project: _Project) -> Check:
    pin = project.root / ".python-version"
    if not pin.is_file():
        fix = project.cd_to_root(f"uv python pin {PYTHON_VERSION}")
        return Check("python_version", Scope.PROJECT, Status.FAIL, ".python-version not found", fix)
    pinned = pin.read_text(encoding="utf-8").strip()
    return Check("python_version", Scope.PROJECT, Status.PASS, f"pins Python {pinned}")


def _lockfile(project: _Project) -> Check:
    fix = project.cd_to_root("uv lock")
    if not (project.root / "uv.lock").is_file():
        return Check("lockfile", Scope.PROJECT, Status.FAIL, "uv.lock not found", fix)
    result = run("uv", "lock", "--check", cwd=project.root)
    if result.returncode == 0:
        message = "uv.lock is in sync with pyproject.toml"
        return Check("lockfile", Scope.PROJECT, Status.PASS, message)
    # uv exits 1 when the lockfile needs updating, and 2 for any other error.
    if result.returncode == 1:
        message = "uv.lock is out of sync with pyproject.toml"
        return Check("lockfile", Scope.PROJECT, Status.FAIL, message, fix)
    # Relocking would fail the same way until the error itself is fixed.
    detail = " ".join((result.stderr or result.stdout).split())
    message = f"uv lock --check failed: {detail}" if detail else "uv lock --check failed"
    fix = f"Fix the error uv reports, then run {fix}"
    return Check("lockfile", Scope.PROJECT, Status.FAIL, message, fix)


def _file_exists(check_id: str, project: _Project, path: str, purpose: str) -> Check:
    """Pass when ``path`` exists. The fix restores it from git, or else says to write it."""
    if (project.root / path).is_file():
        return Check(check_id, Scope.PROJECT, Status.PASS, f"{path} found")
    if _in_last_commit(project.root, path):
        fix = project.cd_to_root(f"git checkout HEAD -- {path}")
    else:
        fix = f"Create {path} in {project.root} with {purpose}"
    return Check(check_id, Scope.PROJECT, Status.FAIL, f"{path} not found", fix)


def _in_last_commit(root: Path, path: str) -> bool:
    if shutil.which("git") is None:
        return False
    return run("git", "cat-file", "-e", f"HEAD:./{path}", cwd=root).returncode == 0


def _gh_auth() -> Check:
    if run("gh", "auth", "status", "--hostname", "github.com").returncode != 0:
        message = "not signed in to github.com"
        return Check("gh_auth", Scope.MACHINE, Status.FAIL, message, "gh auth login")
    return Check("gh_auth", Scope.MACHINE, Status.PASS, "signed in to github.com")
