"""``aa init``: the steps that turn an empty folder into a project."""

import datetime
import logging
import re
from enum import StrEnum
from importlib.resources import files
from pathlib import Path

from aa_cli.doctor import machine_git_config
from aa_cli.process import run

log = logging.getLogger("aa")

PYTHON_VERSION = "3.15"
COMMIT_MESSAGE = "chore: initialize project with aa"

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class Kind(StrEnum):
    CLI = "cli"
    LIB = "lib"


class License(StrEnum):
    MIT = "MIT"
    NONE = "none"


class StepFailed(Exception):
    """A step after preflight failed. The message names the step and the tool's error."""

    def __init__(self, step: str, detail: str) -> None:
        super().__init__(f"step '{step}' failed: {detail}" if detail else f"step '{step}' failed")
        self.step = step


def is_empty_folder_or_missing(target: Path) -> bool:
    return not target.exists() or (target.is_dir() and not any(target.iterdir()))


def create_project(target: Path, kind: Kind, license_choice: License) -> list[str]:
    """Create the project in ``target`` (missing or empty) and return the files it holds."""
    target.mkdir(exist_ok=True)
    # aa makes the repo itself: uv init skips it inside another repo, and the
    # branch must be main whatever the machine's default is.
    _step("git init", target, "git", "init", "--quiet", "--initial-branch=main")
    _step(
        "uv init",
        target,
        "uv",
        "init",
        "--lib" if kind is Kind.LIB else "--app",
        "--package",
        "--python",
        PYTHON_VERSION,
        "--no-workspace",
        "--vcs",
        "none",
    )
    _add_aa_config(target, kind)
    # --python wins over a UV_PYTHON set in the environment, which would
    # otherwise override the project's pin.
    _step(
        "add dev dependencies",
        target,
        "uv",
        "add",
        "--python",
        PYTHON_VERSION,
        "--dev",
        "ruff",
        "pytest",
    )
    _write_files(target, kind, license_choice)
    _step("initial commit", target, "git", "add", "--all")
    _step("initial commit", target, "git", "commit", "--quiet", "--message", COMMIT_MESSAGE)
    listed = _step("list files", target, "git", "ls-files")
    return sorted(listed.splitlines())


def _step(step: str, cwd: Path, tool: str, *args: str) -> str:
    log.debug("Step: %s", step)
    result = run(tool, *args, cwd=cwd)
    if result.returncode != 0:
        raise StepFailed(step, (result.stderr or result.stdout).strip())
    return result.stdout


def _add_aa_config(target: Path, kind: Kind) -> None:
    pyproject = target / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
        _write(pyproject, text.rstrip("\n") + "\n\n" + _render("pyproject.toml.tmpl", kind=kind))
    except OSError as exc:
        raise StepFailed("add aa config", str(exc)) from exc


def _write_files(target: Path, kind: Kind, license_choice: License) -> None:
    package = _package_name(target)
    values = {
        "name": target.name,
        "package": package,
        "year": str(datetime.date.today().year),
        "holder": machine_git_config("user.name"),
    }
    outputs = {
        f"src/{package}/__init__.py": f"{kind}_init.py.tmpl",
        f"tests/test_{package}.py": f"{kind}_test.py.tmpl",
        "AGENTS.md": "AGENTS.md.tmpl",
        "CLAUDE.md": "CLAUDE.md.tmpl",
        "README.md": "README.md.tmpl",
        ".gitignore": "gitignore.tmpl",
        ".github/workflows/ci.yml": "ci.yml.tmpl",
    }
    if license_choice is License.MIT:
        outputs["LICENSE"] = "LICENSE.tmpl"
    try:
        for path, template in outputs.items():
            _write(target / path, _render(template, **values))
    except OSError as exc:
        raise StepFailed("write files", str(exc)) from exc


def _package_name(target: Path) -> str:
    """The import name uv init chose: the one package folder under ``src``."""
    packages = [path.name for path in (target / "src").iterdir() if path.is_dir()]
    if len(packages) != 1:
        raise StepFailed("write files", f"expected one package under src, found {packages}")
    return packages[0]


def _render(template: str, **values: str) -> str:
    """Fill ``{{key}}`` placeholders. A placeholder without a value is a bug, so it raises."""
    text = (files("aa_cli") / "templates" / template).read_text(encoding="utf-8")
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], text)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
