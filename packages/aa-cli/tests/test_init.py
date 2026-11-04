"""``aa init``: creating a local project with real uv and git."""

import datetime
import json
import os
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

COMMIT_MESSAGE = "chore: initialize project with aa"
EXPECTED_FILES = {
    ".github/workflows/ci.yml",
    ".gitignore",
    ".python-version",
    "AGENTS.md",
    "CLAUDE.md",
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "src/demo/__init__.py",
    "tests/test_demo.py",
    "uv.lock",
}


@dataclass
class Created:
    """What one ``aa init`` run left behind."""

    result: object
    project: Path
    git_env: dict[str, str]

    @property
    def envelope(self) -> dict:
        return json.loads(self.result.stdout)

    @property
    def pyproject(self) -> dict:
        return tomllib.loads((self.project / "pyproject.toml").read_text(encoding="utf-8"))

    def read(self, path: str) -> str:
        return (self.project / path).read_text(encoding="utf-8")

    def git(self, *args: str) -> str:
        return run_git(self.project, self.git_env, *args)


def run_git(cwd: Path, env: dict[str, str], *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    )
    return result.stdout


def git_env(machine) -> dict[str, str]:
    """The real PATH with the stand-in machine's throwaway git identity."""
    return {**os.environ, **{k: v for k, v in machine.env.items() if k != "PATH"}}


def local_machine(machine):
    """What a local ``aa init`` needs: uv, git and a git identity, but no gh."""
    machine.add_real("uv")
    machine.add_real("git")
    machine.set_identity(name="Ada Lovelace", email="ada@example.com")
    return machine


def init(aa_in, folder: Path, machine, *args: str) -> Created:
    result = aa_in(folder, "init", "demo", "--json", *args, env=machine.env)
    return Created(result, folder / "demo", git_env(machine))


@pytest.fixture(scope="module")
def cli_project(tmp_path_factory, new_machine, aa_in) -> Created:
    folder = tmp_path_factory.mktemp("init-cli")
    return init(aa_in, folder, local_machine(new_machine()))


@pytest.fixture(scope="module")
def lib_project(tmp_path_factory, new_machine, aa_in) -> Created:
    folder = tmp_path_factory.mktemp("init-lib")
    return init(aa_in, folder, local_machine(new_machine()), "--lib")


def test_init_without_a_kind_creates_a_cli_project(cli_project):
    assert cli_project.result.exit_code == 0, cli_project.result.output
    assert cli_project.envelope["ok"] is True
    assert cli_project.envelope["data"]["kind"] == "cli"
    assert cli_project.pyproject["tool"]["aa"] == {"kind": "cli"}
    assert cli_project.pyproject["project"]["scripts"] == {"demo": "demo:main"}


def test_init_json_data_has_the_path_kind_files_and_no_github_url(cli_project):
    data = cli_project.envelope["data"]

    assert Path(data["path"]).is_absolute()
    assert Path(data["path"]) == cli_project.project.resolve()
    assert data["github_url"] is None
    assert set(data["files"]) == EXPECTED_FILES
    assert set(data["files"]) == set(cli_project.git("ls-files").splitlines())


def test_init_lib_creates_a_typed_library_without_a_command(lib_project):
    assert lib_project.result.exit_code == 0, lib_project.result.output
    assert lib_project.envelope["data"]["kind"] == "lib"
    assert lib_project.pyproject["tool"]["aa"] == {"kind": "lib"}
    assert "scripts" not in lib_project.pyproject["project"]
    assert (lib_project.project / "src" / "demo" / "py.typed").is_file()
    assert "src/demo/py.typed" in lib_project.envelope["data"]["files"]


def test_the_created_project_has_the_standard_files(cli_project):
    assert cli_project.read(".python-version").strip() == "3.15"
    assert "[[package]]" in cli_project.read("uv.lock")
    assert "def test_" in cli_project.read("tests/test_demo.py")
    assert cli_project.read("CLAUDE.md") == "@AGENTS.md\n"
    agents = cli_project.read("AGENTS.md")
    for command in ("uv sync", "uv run pytest", "uv run ruff check", "uv run ruff format"):
        assert command in agents, command
    assert "Conventional Commits" in agents
    gitignore = cli_project.read(".gitignore").splitlines()
    for pattern in (".venv/", "__pycache__/", ".pytest_cache/", ".ruff_cache/", "dist/"):
        assert pattern in gitignore, pattern


def test_the_license_is_mit_with_the_git_name_and_current_year(cli_project):
    license_text = cli_project.read("LICENSE")

    assert license_text.startswith("MIT License")
    assert f"Copyright (c) {datetime.date.today().year} Ada Lovelace" in license_text


def test_the_readme_has_the_name_and_the_install_test_and_lint_commands(cli_project):
    readme = cli_project.read("README.md")

    assert readme.startswith("# demo")
    for command in ("uv sync", "uv run pytest", "uv run ruff check"):
        assert command in readme, command


def test_the_ci_workflow_runs_lint_and_tests_on_windows_and_linux(cli_project):
    workflow = cli_project.read(".github/workflows/ci.yml")

    assert "push:\n    branches: [main]" in workflow
    assert "pull_request:" in workflow
    assert "os: [ubuntu-latest, windows-latest]" in workflow
    assert re.search(r"astral-sh/setup-uv@[0-9a-f]{40} # v10\.", workflow)
    assert re.search(r"actions/checkout@[0-9a-f]{40} # v\d+\.", workflow)
    assert re.search(r'version: "\d+\.\d+\.\d+"', workflow)
    steps = [line.strip() for line in workflow.splitlines() if line.strip().startswith("- run:")]
    assert steps == [
        "- run: uv python install",
        "- run: uv sync --locked",
        "- run: uv run ruff check .",
        "- run: uv run ruff format --check .",
        "- run: uv run pytest",
    ]


def test_the_history_is_one_initial_commit_on_main_with_a_clean_tree(cli_project):
    assert cli_project.git("log", "--format=%s").splitlines() == [COMMIT_MESSAGE]
    assert cli_project.git("branch", "--show-current").strip() == "main"
    assert cli_project.git("status", "--porcelain") == ""


@pytest.mark.parametrize("kind", ["cli_project", "lib_project"])
def test_the_created_project_passes_its_own_tests_lint_and_format_check(request, kind):
    project = request.getfixturevalue(kind).project
    for command in (
        ["uv", "run", "pytest"],
        ["uv", "run", "ruff", "check", "."],
        ["uv", "run", "ruff", "format", "--check", "."],
    ):
        result = subprocess.run(command, cwd=project, capture_output=True, text=True)
        assert result.returncode == 0, f"{command}: {result.stdout}{result.stderr}"


def test_init_with_both_cli_and_lib_is_a_usage_error_and_creates_nothing(aa, machine, tmp_path):
    result = aa("init", "demo", "--cli", "--lib", "--json", env=local_machine(machine).env)

    assert result.exit_code == 2
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "usage"
    assert not (tmp_path / "demo").exists()


def test_an_unknown_license_is_a_usage_error(aa, machine):
    result = aa("init", "demo", "--license", "GPL", "--json", env=local_machine(machine).env)

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "usage"


def test_license_none_creates_no_license_file(aa_in, machine, tmp_path):
    created = init(aa_in, tmp_path, local_machine(machine), "--license", "none")

    assert created.result.exit_code == 0, created.result.output
    assert not (created.project / "LICENSE").exists()
    assert "LICENSE" not in created.envelope["data"]["files"]
    assert created.git("status", "--porcelain") == ""


def test_init_into_an_existing_empty_folder_creates_the_project_there(aa_in, machine, tmp_path):
    (tmp_path / "demo").mkdir()

    created = init(aa_in, tmp_path, local_machine(machine), "--lib")

    assert created.result.exit_code == 0, created.result.output
    assert (created.project / "pyproject.toml").is_file()


@pytest.mark.parametrize("entry", ["notes.txt", ".hidden", "empty-folder/"])
def test_a_folder_with_anything_in_it_is_target_not_empty_and_unchanged(
    aa, machine, tmp_path, entry
):
    target = tmp_path / "demo"
    target.mkdir()
    if entry.endswith("/"):
        (target / entry).mkdir()
    else:
        (target / entry).write_text("keep me")

    result = aa("init", "demo", "--json", env=local_machine(machine).env)

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "target_not_empty"
    assert [path.name for path in target.iterdir()] == [entry.rstrip("/")]


def test_a_file_named_like_the_project_is_target_not_empty(aa, machine, tmp_path):
    (tmp_path / "demo").write_text("keep me")

    result = aa("init", "demo", "--json", env=local_machine(machine).env)

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "target_not_empty"
    assert (tmp_path / "demo").read_text() == "keep me"


@pytest.mark.parametrize(
    ("missing", "failed"),
    [
        ("uv", ["uv"]),
        ("git", ["git", "git_identity"]),
        ("identity", ["git_identity"]),
    ],
)
def test_a_missing_tool_or_identity_fails_preflight_before_creating_anything(
    aa, machine, tmp_path, missing, failed
):
    if missing != "uv":
        machine.add_real("uv")
    if missing != "git":
        machine.add_real("git")
    if missing != "identity":
        machine.set_identity()

    result = aa("init", "demo", "--json", env=machine.env)

    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["error"]["code"] == "preflight_failed"
    assert envelope["error"]["fix"]
    assert [check["id"] for check in envelope["data"]["checks"]] == failed
    doctor = json.loads(aa("doctor", "--json", env=machine.env).stdout)["data"]["checks"]
    doctor = {check["id"]: check for check in doctor}
    for check in envelope["data"]["checks"]:
        assert check == doctor[check["id"]]
    assert list(tmp_path.iterdir()) == []


def test_preflight_does_not_need_gh(cli_project):
    assert cli_project.result.exit_code == 0


def test_init_inside_another_uv_workspace_does_not_join_it(aa_in, machine, tmp_path):
    machine = local_machine(machine)
    env = git_env(machine)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "outer"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n\n'
        '[tool.uv.workspace]\nmembers = ["*"]\n'
    )
    subprocess.run(["uv", "lock"], cwd=tmp_path, check=True, capture_output=True)
    run_git(tmp_path, env, "init", "-q")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}

    created = init(aa_in, tmp_path, machine)

    assert created.result.exit_code == 0, created.result.output
    after = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert after == before
    assert (created.project / "uv.lock").is_file()
    toplevel = Path(created.git("rev-parse", "--show-toplevel").strip())
    assert toplevel.resolve() == created.project.resolve()
    assert created.git("log", "--format=%s").splitlines() == [COMMIT_MESSAGE]
    outer_log = subprocess.run(["git", "log"], cwd=tmp_path, env=env, capture_output=True)
    assert outer_log.returncode != 0  # the outer repo still has no commits


def test_a_failed_step_is_step_failed_with_the_step_and_its_stderr(aa_in, machine, tmp_path):
    result = aa_in(tmp_path, "init", "bad!name", "--json", env=local_machine(machine).env)

    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "step_failed"
    assert "uv init" in error["message"]
    assert "not a valid" in error["message"].lower()
    assert (tmp_path / "bad!name").is_dir()


def test_init_in_human_mode_says_where_the_project_is_and_what_kind(aa, machine, tmp_path):
    result = aa("init", "demo", "--lib", env=local_machine(machine).env)

    assert result.exit_code == 0, result.output
    assert str((tmp_path / "demo").resolve()) in result.stdout
    assert "lib" in result.stdout
