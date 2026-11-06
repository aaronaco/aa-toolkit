"""``aa init``: the steps that turn an empty folder into a project."""

import contextlib
import datetime
import keyword
import logging
import re
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path, PurePosixPath

from aa_cli.git import machine_config
from aa_cli.process import run

log = logging.getLogger("aa")

PYTHON_VERSION = "3.15"
COMMIT_MESSAGE = "chore: initial commit"
BRANCH = "main"

NAME_RULE = (
    "a project name starts with a letter, ends with a letter or digit, holds only"
    " letters, digits, '-' and '_', and is not a Python keyword or a name Windows reserves"
    " (con, prn, aux, nul, com0-com9, lpt0-lpt9)"
)
_NAME = re.compile(r"[A-Za-z](?:[A-Za-z0-9_-]*[A-Za-z0-9])?")
# Windows can't create a folder with one of these names, in any case.
_WINDOWS_RESERVED = re.compile(r"con|prn|aux|nul|com\d|lpt\d", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_GITHUB_URL = re.compile(r"https://\S+")


class Kind(StrEnum):
    CLI = "cli"
    LIB = "lib"


class License(StrEnum):
    MIT = "MIT"
    NONE = "none"


# The package code and the starter test each kind starts with.
_KIND_TEMPLATES = {
    Kind.CLI: ("cli_init.py.tmpl", "cli_test.py.tmpl"),
    Kind.LIB: ("lib_init.py.tmpl", "lib_test.py.tmpl"),
}


class StepFailed(Exception):
    """A step of ``aa init`` failed. The message names the step and the tool's error."""

    def __init__(self, step: str, detail: str, fix: str | None = None) -> None:
        super().__init__(f"step '{step}' failed: {detail}" if detail else f"step '{step}' failed")
        self.step = step
        self.detail = detail
        self.fix = fix


@dataclass(frozen=True)
class OuterWorkspace:
    """A uv workspace above the target whose members would include the new project."""

    root: Path
    member: str  # the target's path relative to the root, as uv's globs see it

    @property
    def fix(self) -> str:
        pyproject = self.root / "pyproject.toml"
        return (
            f'Under [tool.uv.workspace] in {pyproject}, add exclude = ["{self.member}"]'
            f' (or add "{self.member}" to the existing exclude list)'
        )


def is_valid_name(name: str) -> bool:
    """Whether ``name`` follows NAME_RULE, so uv can build a package from it as it is."""
    # uv lowercases the name and turns '-' into '_' to get the import name.
    import_name = name.lower().replace("-", "_")
    return (
        _NAME.fullmatch(name) is not None
        # True, False and None are keywords only as typed; the import name catches the rest.
        and not keyword.iskeyword(name)
        and not keyword.iskeyword(import_name)
        and _WINDOWS_RESERVED.fullmatch(name) is None
    )


def is_empty_folder_or_missing(target: Path) -> bool:
    return not target.exists() or (target.is_dir() and not any(target.iterdir()))


def outer_workspace_taking_in(target: Path) -> OuterWorkspace | None:
    """The uv workspace above ``target`` that would take it in as a member, if any.

    uv uses the nearest workspace root above a project. If that root's members
    match the project and its excludes don't, the project joins it no matter
    how it was created, and a project of its own there breaks the outer lock.
    """
    for folder in target.parents:
        workspace = _uv_workspace(folder / "pyproject.toml")
        if workspace is None:
            continue
        member = target.relative_to(folder).as_posix()
        if _matches(member, workspace.get("members", [])) and not _matches(
            member, workspace.get("exclude", [])
        ):
            return OuterWorkspace(folder, member)
        return None
    return None


def _uv_workspace(pyproject: Path) -> dict | None:
    if not pyproject.is_file():
        return None
    try:
        config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        log.debug("Cannot read %s: %s", pyproject, exc)
        return None
    workspace = config.get("tool", {}).get("uv", {}).get("workspace")
    return workspace if isinstance(workspace, dict) else None


def _matches(member: str, patterns: list[str]) -> bool:
    path = PurePosixPath(member)
    return any(path.full_match(pattern.removeprefix("./").rstrip("/")) for pattern in patterns)


def create_project(target: Path, kind: Kind, license_choice: License) -> list[str]:
    """Create the project in ``target`` (missing or empty) and return the files it holds."""
    target.mkdir(exist_ok=True)
    # aa makes the repo itself: uv init skips it inside another repo, and the
    # branch must be main whatever the machine's default is.
    _step("git init", target, "git", "init", "--quiet", f"--initial-branch={BRANCH}")
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
    _add_uv_workspace(target)
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


def create_github_repo(target: Path, public: bool) -> str:
    """Create the GitHub repo for the project in ``target``, push to it and return its URL."""
    args = [
        "repo",
        "create",
        target.name,
        "--public" if public else "--private",
        "--source",
        ".",
        "--push",
    ]
    kept = f"The project at {target} is kept; run the fix from inside it."
    try:
        stdout = _step("create GitHub repo", target, "gh", *args)
    except StepFailed as exc:
        # gh adds the new repo as origin before it pushes. Once origin is there,
        # rerunning gh repo create fails on the taken name; only the push is left.
        has_origin = run("git", "remote", "get-url", "origin", cwd=target).returncode == 0
        fix = f"git push --set-upstream origin {BRANCH}" if has_origin else " ".join(["gh", *args])
        raise StepFailed(exc.step, f"{exc.detail}\n{kept}".lstrip("\n"), fix) from exc
    # Without a terminal, gh prints the new repo's URL on stdout.
    url = _GITHUB_URL.search(stdout)
    if url:
        return url.group(0)
    view = ["repo", "view", "--json", "url", "--jq", ".url"]
    fix = " ".join(["gh", *view])
    return _step("read GitHub repo URL", target, "gh", *view, fix=fix).strip()


def _step(step: str, cwd: Path, tool: str, *args: str, fix: str | None = None) -> str:
    log.debug("Step: %s", step)
    result = run(tool, *args, cwd=cwd)
    if result.returncode != 0:
        raise StepFailed(step, (result.stderr or result.stdout).strip(), fix)
    return result.stdout


@contextlib.contextmanager
def _file_step(step: str) -> Iterator[None]:
    """Report a file read or write that fails as the failure of ``step``."""
    try:
        yield
    except OSError as exc:
        raise StepFailed(step, str(exc)) from exc


def _add_uv_workspace(target: Path) -> None:
    pyproject = target / "pyproject.toml"
    with _file_step("add uv workspace"):
        text = pyproject.read_text(encoding="utf-8")
        _write(pyproject, text.rstrip("\n") + "\n\n" + _render("pyproject.toml.tmpl"))


def _write_files(target: Path, kind: Kind, license_choice: License) -> None:
    package = _package_name(target)
    values = {
        "name": target.name,
        "package": package,
        "year": str(datetime.date.today().year),
        "holder": machine_config("user.name"),
    }
    package_template, test_template = _KIND_TEMPLATES[kind]
    outputs = {
        f"src/{package}/__init__.py": package_template,
        f"tests/test_{package}.py": test_template,
        "AGENTS.md": "AGENTS.md.tmpl",
        "CLAUDE.md": "CLAUDE.md.tmpl",
        "README.md": "README.md.tmpl",
        ".gitignore": "gitignore.tmpl",
        ".github/workflows/ci.yml": "ci.yml.tmpl",
    }
    if license_choice is License.MIT:
        outputs["LICENSE"] = "LICENSE.tmpl"
    with _file_step("write files"):
        for path, template in outputs.items():
            _write(target / path, _render(template, **values))


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
