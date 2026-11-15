"""``aa init``: the steps that turn an empty folder into a project."""

import contextlib
import datetime
import keyword
import logging
import re
import tomllib
from collections.abc import Generator
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
PYPROJECT = "pyproject.toml"
WRITE_FILES_STEP = "write files"
CI_WORKFLOW = ".github/workflows/ci.yml"
CI_TEMPLATE = "ci.yml.tmpl"

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
    """A step failed. The message names the step and the tool's error."""

    def __init__(self, step: str, detail: str, fix: str | None = None) -> None:
        super().__init__(f"step '{step}' failed: {detail}" if detail else f"step '{step}' failed")
        self.step = step
        self.detail = detail
        self.fix = fix


@dataclass(frozen=True)
class StepSpec:
    """One external command ``aa init`` runs."""

    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class InitPlan:
    """What ``aa init --dry-run`` would create and run."""

    files: list[str]
    steps: list[StepSpec]


@dataclass(frozen=True)
class OuterWorkspace:
    """A uv workspace above the target whose members would include the new project."""

    root: Path
    member: str  # the target's path relative to the root, as uv's globs see it

    @property
    def fix(self) -> str:
        pyproject = self.root / PYPROJECT
        return (
            f'Under [tool.uv.workspace] in {pyproject}, add exclude = ["{self.member}"]'
            f' (or add "{self.member}" to the existing exclude list)'
        )


def _import_name(name: str) -> str:
    # uv lowercases the name and turns '-' into '_' to get the import name.
    return name.lower().replace("-", "_")


def is_valid_name(name: str) -> bool:
    """Whether ``name`` follows NAME_RULE, so uv can build a package from it as it is."""
    import_name = _import_name(name)
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
        workspace = _uv_workspace(folder / PYPROJECT)
        if workspace is None:
            continue
        member = target.relative_to(folder).as_posix()
        if _matches(member, workspace.get("members", [])) and not _matches(
            member, workspace.get("exclude", [])
        ):
            return OuterWorkspace(folder, member)
        return None
    return None


def _uv_workspace(pyproject: Path) -> dict[str, list[str]] | None:
    if not pyproject.is_file():
        return None
    try:
        config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        log.debug("Cannot read %s: %s", pyproject, exc)
        return None
    workspace = config.get("tool", {}).get("uv", {}).get("workspace")
    if not isinstance(workspace, dict):
        return None
    table: dict[str, list[str]] = workspace  # uv's only workspace keys: members and exclude
    return table


def _matches(member: str, patterns: list[str]) -> bool:
    path = PurePosixPath(member)
    return any(path.full_match(pattern.removeprefix("./").rstrip("/")) for pattern in patterns)


@contextlib.contextmanager
def _rerun_note(target: Path) -> Generator[None]:
    """Add to a failure what stops ``aa init`` from running again: what it left in ``target``."""

    def note() -> str:
        if is_empty_folder_or_missing(target):
            return ""
        return f"The folder {target} was left as it is; delete it before running aa init again."

    try:
        yield
    except StepFailed as exc:
        detail = "\n".join(filter(None, [exc.detail, note()]))
        raise StepFailed(exc.step, detail, exc.fix) from exc
    except FileNotFoundError as exc:
        raise FileNotFoundError(" ".join(filter(None, [f"{exc}.", note()]))) from exc


def _local_steps(kind: Kind) -> list[StepSpec]:
    # --python wins over a UV_PYTHON set in the environment, which would
    # otherwise override the project's pin.
    return [
        # aa makes the repo itself: uv init skips it inside another repo, and the
        # branch must be main whatever the machine's default is.
        StepSpec("git init", ("git", "init", "--quiet", f"--initial-branch={BRANCH}")),
        StepSpec(
            "uv init",
            (
                "uv",
                "init",
                "--lib" if kind is Kind.LIB else "--app",
                "--package",
                "--python",
                PYTHON_VERSION,
                "--no-workspace",
                "--vcs",
                "none",
            ),
        ),
        StepSpec(
            "add dev dependencies",
            ("uv", "add", "--python", PYTHON_VERSION, "--dev", "ruff", "pytest"),
        ),
        # The folder holds only what aa just made, so global ignore rules have nothing to protect.
        # One like *.lock would drop a file the project's CI needs, and git add wouldn't say so.
        StepSpec("stage files", ("git", "-c", "core.excludesFile=", "add", "--all")),
    ]


def _github_steps(repo_name: str, public: bool) -> list[StepSpec]:
    return [
        StepSpec("initial commit", ("git", "commit", "--quiet", "--message", COMMIT_MESSAGE)),
        StepSpec(
            "create GitHub repo",
            (
                "gh",
                "repo",
                "create",
                repo_name,
                "--public" if public else "--private",
                "--source",
                ".",
                "--push",
            ),
        ),
    ]


def plan_project(
    target: Path, kind: Kind, license_choice: License, *, github: bool, public: bool
) -> InitPlan:
    """Validate and render templates in memory for ``aa init --dry-run``, writing nothing."""
    holder = _resolve_license_holder(license_choice)
    package = _import_name(target.name)
    # Render every template in memory so a template bug fails the dry run like a real run.
    render("pyproject.toml.tmpl")
    rendered = _render_outputs(target.name, package, kind, license_choice, holder)
    uv_files = {".python-version", PYPROJECT, "uv.lock"}
    if kind is Kind.LIB:
        uv_files.add(f"src/{package}/py.typed")
    steps = _local_steps(kind)
    if github:
        steps.extend(_github_steps(target.name, public))
    return InitPlan(files=sorted(uv_files | rendered.keys()), steps=steps)


def create_project(target: Path, kind: Kind, license_choice: License) -> list[str]:
    """Create the project in ``target`` (missing or empty) and return the files it holds."""
    with _rerun_note(target):
        holder = _resolve_license_holder(license_choice)
        return _build_project(target, kind, license_choice, holder)


def _build_project(target: Path, kind: Kind, license_choice: License, holder: str) -> list[str]:
    target.mkdir(exist_ok=True)
    git_init, uv_init, add_deps, stage_files = _local_steps(kind)
    step(git_init.name, target, *git_init.command)
    step(uv_init.name, target, *uv_init.command)
    _add_uv_workspace(target)
    step(add_deps.name, target, *add_deps.command)
    _write_files(target, kind, license_choice, holder)
    step(stage_files.name, target, *stage_files.command)
    listed = step("list files", target, "git", "ls-files")
    return sorted(listed.splitlines())


def commit_and_push_to_github(target: Path, public: bool) -> str:
    """Commit the project in ``target``, create its GitHub repo, push and return the repo's URL."""
    commit_step, repo_step = _github_steps(target.name, public)
    with _rerun_note(target):
        step(commit_step.name, target, *commit_step.command)
    kept = f"The project at {target} is kept; run the fix from inside it."
    try:
        stdout = step(repo_step.name, target, *repo_step.command)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{exc}. The project at {target} is kept.") from exc
    except StepFailed as exc:
        # gh adds the new repo as origin before it pushes. Once origin is there,
        # rerunning gh repo create fails on the taken name; only the push is left.
        has_origin = run("git", "remote", "get-url", "origin", cwd=target).returncode == 0
        fix = (
            f"git push --set-upstream origin {BRANCH}"
            if has_origin
            else " ".join(repo_step.command)
        )
        raise StepFailed(exc.step, f"{exc.detail}\n{kept}".lstrip("\n"), fix) from exc
    # Without a terminal, gh prints the new repo's URL on stdout.
    url = _GITHUB_URL.search(stdout)
    if url:
        return url.group(0)
    view = ["repo", "view", "--json", "url", "--jq", ".url"]
    fix = " ".join(["gh", *view])
    return step("read GitHub repo URL", target, "gh", *view, fix=fix).strip()


def step(step_name: str, cwd: Path, tool: str, *args: str, fix: str | None = None) -> str:
    log.debug("Step: %s", step_name)
    result = run(tool, *args, cwd=cwd)
    if result.returncode != 0:
        raise StepFailed(step_name, (result.stderr or result.stdout).strip(), fix)
    return result.stdout


@contextlib.contextmanager
def file_step(step_name: str) -> Generator[None]:
    """Report a file read or write that fails as the failure of ``step_name``."""
    try:
        yield
    except OSError as exc:
        raise StepFailed(step_name, str(exc)) from exc


def _add_uv_workspace(target: Path) -> None:
    pyproject = target / PYPROJECT
    with file_step("add uv workspace"):
        text = pyproject.read_text(encoding="utf-8")
        write(pyproject, text.rstrip("\n") + "\n\n" + render("pyproject.toml.tmpl"))


def _resolve_license_holder(license_choice: License) -> str:
    if license_choice is not License.MIT:
        return ""
    holder = machine_config("user.name")
    # Nothing else stops a blank holder: git can make up an author for a commit.
    if not holder:
        detail = "the LICENSE needs a holder, but git's user.name is not set"
        raise StepFailed(WRITE_FILES_STEP, detail, 'git config --global user.name "Your Name"')
    return holder


def _render_outputs(
    name: str, package: str, kind: Kind, license_choice: License, holder: str
) -> dict[str, str]:
    values = {
        "name": name,
        "package": package,
        "year": str(datetime.date.today().year),
        "holder": holder,
    }
    package_template, test_template = _KIND_TEMPLATES[kind]
    templates = {
        f"src/{package}/__init__.py": package_template,
        f"tests/test_{package}.py": test_template,
        "AGENTS.md": "AGENTS.md.tmpl",
        "CLAUDE.md": "CLAUDE.md.tmpl",
        "README.md": "README.md.tmpl",
        ".gitignore": "gitignore.tmpl",
        CI_WORKFLOW: CI_TEMPLATE,
    }
    if license_choice is License.MIT:
        templates["LICENSE"] = "LICENSE.tmpl"
    return {path: render(template, **values) for path, template in templates.items()}


def _write_files(target: Path, kind: Kind, license_choice: License, holder: str) -> None:
    package = _package_name(target)
    rendered = _render_outputs(target.name, package, kind, license_choice, holder)
    with file_step(WRITE_FILES_STEP):
        for path, text in rendered.items():
            write(target / path, text)


def _package_name(target: Path) -> str:
    """The import name uv init chose: the one package folder under ``src``."""
    packages = [path.name for path in (target / "src").iterdir() if path.is_dir()]
    if len(packages) != 1:
        raise StepFailed(WRITE_FILES_STEP, f"expected one package under src, found {packages}")
    return packages[0]


def render(template: str, **values: str) -> str:
    """Fill ``{{key}}`` placeholders. A placeholder without a value is a bug, so it raises."""
    text = (files("aa_cli") / "templates" / template).read_text(encoding="utf-8")
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], text)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
