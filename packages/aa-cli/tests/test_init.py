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

COMMIT_MESSAGE = "chore: initial commit"
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


def assert_staged_with_no_commits(created: Created) -> None:
    assert created.git("rev-list", "--all", "--count").strip() == "0"
    statuses = created.git("status", "--porcelain").splitlines()
    assert statuses
    assert all(status.startswith("A  ") for status in statuses), statuses


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
    assert cli_project.pyproject["project"]["scripts"] == {"demo": "demo:main"}


@pytest.mark.parametrize("kind", ["cli_project", "lib_project"])
def test_the_created_project_has_no_aa_config_and_is_its_own_uv_workspace(request, kind):
    tool = request.getfixturevalue(kind).pyproject["tool"]

    assert "aa" not in tool
    assert "workspace" in tool["uv"]


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


def test_the_license_ignores_a_git_name_set_only_in_the_repo_aa_runs_in(aa_in, machine, tmp_path):
    machine = local_machine(machine)
    run_git(tmp_path, git_env(machine), "init", "-q")
    run_git(tmp_path, git_env(machine), "config", "user.name", "Repo User")

    created = init(aa_in, tmp_path, machine)

    assert created.result.exit_code == 0, created.result.output
    assert "Ada Lovelace" in created.read("LICENSE")
    assert "Repo User" not in created.read("LICENSE")


def test_the_license_has_the_git_name_on_git_older_than_2_26(aa_in, machine, tmp_path):
    machine.add_real("uv")
    machine.add_old_git()
    machine.set_identity(name="Ada Lovelace", email="ada@example.com")

    created = init(aa_in, tmp_path, machine)

    assert created.result.exit_code == 0, created.result.output
    assert "Ada Lovelace" in created.read("LICENSE")


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


def test_init_stages_every_file_on_main_and_makes_no_commit(cli_project):
    assert_staged_with_no_commits(cli_project)
    assert set(cli_project.git("diff", "--cached", "--name-only").splitlines()) == EXPECTED_FILES
    assert cli_project.git("branch", "--show-current").strip() == "main"


@pytest.mark.parametrize("kind", ["cli_project", "lib_project"])
def test_the_created_project_passes_its_own_tests_lint_and_format_check(request, kind):
    assert_passes_its_own_tests_and_lint(request.getfixturevalue(kind).project)


def assert_passes_its_own_tests_and_lint(project: Path) -> None:
    """The project's own pytest, ruff check and ruff format --check pass."""
    # As the project's own CI runs them: no Python override, so .python-version decides.
    env = {key: value for key, value in os.environ.items() if key != "UV_PYTHON"}
    for command in (
        ["uv", "run", "pytest"],
        ["uv", "run", "ruff", "check", "."],
        ["uv", "run", "ruff", "format", "--check", "."],
    ):
        result = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True)
        assert result.returncode == 0, f"{command}: {result.stdout}{result.stderr}"


def test_init_pins_python_3_15_even_when_uv_python_asks_for_another(aa_in, machine, tmp_path):
    machine = local_machine(machine)
    result = aa_in(tmp_path, "init", "demo", "--json", env={**machine.env, "UV_PYTHON": "3.14"})

    assert result.exit_code == 0, result.output
    project = tmp_path / "demo"
    assert (project / ".python-version").read_text().strip() == "3.15"
    assert (project / "uv.lock").is_file()


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


RULE_START = "starts with a letter"  # the opening words of the name rule


@pytest.mark.parametrize(
    ("name", "existing"),
    [
        ("123", None),
        ("a/b", None),
        ("a/b", "a"),
        ("bad@name", None),
        ("my app", None),
        # uv refuses a package name that ends in '-' or '_'.
        ("demo-", None),
        ("demo_", None),
        # A keyword is no import name, so the starter test could never import it.
        ("class", None),
        ("True", None),
        # Windows can't make a folder with a reserved device name, whatever the case.
        ("con", None),
        ("Com1", None),
    ],
    ids=[
        "digits",
        "path",
        "path-in-existing-folder",
        "at",
        "space",
        "dash-end",
        "us-end",
        "kw",
        "kw-capitalized",
        "reserved",
        "reserved-mixed-case",
    ],
)
def test_a_name_that_breaks_the_rule_is_a_usage_error_and_creates_nothing(
    aa, machine, tmp_path, name, existing
):
    if existing:
        (tmp_path / existing).mkdir()

    result = aa("init", name, "--json", env=local_machine(machine).env)

    assert result.exit_code == 2
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "usage"
    assert RULE_START in envelope["error"]["message"]
    assert [path.name for path in tmp_path.rglob("*")] == ([existing] if existing else [])


def test_init_dot_creates_the_project_in_the_current_folder(aa_in, machine, tmp_path):
    folder = tmp_path / "dot-demo"
    folder.mkdir()

    result = aa_in(folder, "init", ".", "--json", env=local_machine(machine).env)

    assert result.exit_code == 0, result.output
    assert Path(json.loads(result.stdout)["data"]["path"]) == folder.resolve()
    assert (folder / "src" / "dot_demo" / "__init__.py").is_file()


def test_init_dot_in_a_folder_whose_name_breaks_the_rule_is_a_usage_error(aa_in, machine, tmp_path):
    folder = tmp_path / "1st try"
    folder.mkdir()

    result = aa_in(folder, "init", ".", "--json", env=local_machine(machine).env)

    assert result.exit_code == 2
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "usage"
    assert RULE_START in error["message"]
    assert list(folder.iterdir()) == []


@pytest.mark.parametrize("name", ["my-app", "my_app2"])
def test_a_name_with_dashes_underscores_or_digits_passes_its_own_tests_and_lint(
    aa_in, machine, tmp_path, name
):
    result = aa_in(tmp_path, "init", name, "--json", env=local_machine(machine).env)

    assert result.exit_code == 0, result.output
    assert_passes_its_own_tests_and_lint(tmp_path / name)


def test_license_none_creates_no_license_file(aa_in, machine, tmp_path):
    created = init(aa_in, tmp_path, local_machine(machine), "--license", "none")

    assert created.result.exit_code == 0, created.result.output
    assert not (created.project / "LICENSE").exists()
    assert "LICENSE" not in created.envelope["data"]["files"]
    assert_staged_with_no_commits(created)


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


@pytest.mark.parametrize("missing", ["uv", "git"])
def test_a_missing_tool_is_reported_as_unexpected_with_no_check_first(aa, machine, missing):
    if missing != "uv":
        machine.add_real("uv")
    if missing != "git":
        machine.add_real("git")
    machine.set_identity()

    result = aa("init", "demo", "--json", env=machine.env)

    assert result.exit_code == 3
    envelope = json.loads(result.stdout)
    assert envelope["error"]["code"] == "unexpected"
    assert "data" not in envelope


def no_identity_env(machine) -> dict[str, str | None]:
    """The machine's env, with git stopped from making up an identity from the user and host."""
    return {
        **machine.env,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "user.useConfigOnly",
        "GIT_CONFIG_VALUE_0": "true",
    }


def test_init_without_github_makes_no_commit_so_it_needs_no_git_identity(aa_in, machine, tmp_path):
    machine.add_real("uv")
    machine.add_real("git")
    env = no_identity_env(machine)

    result = aa_in(tmp_path, "init", "demo", "--license", "none", "--json", env=env)

    assert result.exit_code == 0, result.output
    assert_staged_with_no_commits(Created(result, tmp_path / "demo", git_env(machine)))


def test_init_github_without_a_git_identity_fails_the_initial_commit_with_gits_error(
    aa_in, machine, tmp_path
):
    machine.add_real("uv")
    machine.add_real("git")
    machine.add_gh()
    env = no_identity_env(machine)

    result = aa_in(tmp_path, "init", "demo", "--license", "none", "--github", "--json", env=env)

    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "step_failed"
    assert "initial commit" in error["message"]
    assert "user.email" in error["message"]
    assert repo_creates(machine) == []


def test_a_license_without_a_git_name_is_step_failed_and_never_committed(aa_in, machine, tmp_path):
    machine.add_real("uv")
    machine.add_real("git")
    machine.set_identity(name=None, email="ada@example.com")

    created = init(aa_in, tmp_path, machine)

    assert created.result.exit_code == 1
    error = created.envelope["error"]
    assert error["code"] == "step_failed"
    assert "user.name" in error["message"]
    assert error["fix"] == 'git config --global user.name "Your Name"'
    assert not (created.project / "LICENSE").exists()


def test_a_local_init_does_not_need_gh(cli_project):
    assert cli_project.result.exit_code == 0


@pytest.mark.parametrize("ok", [True, False], ids=["created", "target-not-empty"])
def test_aa_json_env_gives_init_one_envelope_whose_ok_matches_the_exit_code(
    aa, machine, tmp_path, ok
):
    if not ok:
        (tmp_path / "demo").write_text("keep me")

    result = aa("init", "demo", env={**local_machine(machine).env, "AA_JSON": "1"})

    assert json.loads(result.stdout)["ok"] is ok
    assert result.exit_code == (0 if ok else 1)


OUTER_PYPROJECT = '[project]\nname = "outer"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n\n'


def outer_workspace(folder: Path, env: dict[str, str], workspace: str) -> dict[str, bytes]:
    """Make ``folder`` a locked uv workspace and a git repo, and return its files."""
    (folder / "pyproject.toml").write_text(OUTER_PYPROJECT + "[tool.uv.workspace]\n" + workspace)
    subprocess.run(["uv", "lock"], cwd=folder, check=True, capture_output=True)
    run_git(folder, env, "init", "-q")
    return outer_files(folder)


def outer_files(folder: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in folder.iterdir() if path.is_file()}


def outer_still_locks(folder: Path) -> bool:
    locked = subprocess.run(["uv", "lock", "--locked"], cwd=folder, capture_output=True)
    return locked.returncode == 0


@pytest.mark.parametrize(
    "workspace",
    ['members = ["packages/*"]\n', 'members = ["*"]\nexclude = ["demo"]\n'],
    ids=["not-a-member", "excluded"],
)
def test_init_inside_another_uv_workspace_does_not_join_or_break_it(
    aa_in, machine, tmp_path, workspace
):
    machine = local_machine(machine)
    env = git_env(machine)
    before = outer_workspace(tmp_path, env, workspace)

    created = init(aa_in, tmp_path, machine)

    assert created.result.exit_code == 0, created.result.output
    assert outer_files(tmp_path) == before
    assert outer_still_locks(tmp_path)
    assert (created.project / "uv.lock").is_file()
    toplevel = Path(created.git("rev-parse", "--show-toplevel").strip())
    assert toplevel.resolve() == created.project.resolve()
    assert_staged_with_no_commits(created)
    outer_log = subprocess.run(["git", "log"], cwd=tmp_path, env=env, capture_output=True)
    assert outer_log.returncode != 0  # the outer repo still has no commits


@pytest.mark.parametrize(
    ("workspace", "cwd", "member"),
    [
        ('members = ["*"]\n', ".", "demo"),
        ('members = ["packages/*"]\n', "packages", "packages/demo"),
    ],
    ids=["root-glob", "from-a-subfolder"],
)
def test_init_where_an_outer_workspace_would_take_the_project_in_stops_first(
    aa_in, machine, tmp_path, workspace, cwd, member
):
    machine = local_machine(machine)
    before = outer_workspace(tmp_path, git_env(machine), workspace)
    (tmp_path / cwd).mkdir(exist_ok=True)

    result = aa_in(tmp_path / cwd, "init", "demo", "--json", env=machine.env)

    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "target_in_workspace"
    assert f'exclude = ["{member}"]' in error["fix"]
    assert not (tmp_path / member).exists()
    assert outer_files(tmp_path) == before
    assert outer_still_locks(tmp_path)


def test_a_failed_step_is_step_failed_with_the_step_and_its_stderr(aa_in, machine, tmp_path):
    machine.add_real("git")
    machine.set_identity()
    machine.add_failing("uv", "fake uv: the index is unreachable")

    result = aa_in(tmp_path, "init", "demo", "--json", env=machine.env)

    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "step_failed"
    assert "uv init" in error["message"]
    assert "fake uv: the index is unreachable" in error["message"]
    assert (tmp_path / "demo").is_dir()


def test_init_in_human_mode_says_where_the_project_is_and_what_kind(aa, machine, tmp_path):
    result = aa("init", "demo", "--lib", env=local_machine(machine).env)

    assert result.exit_code == 0, result.output
    assert str((tmp_path / "demo").resolve()) in result.stdout
    assert "lib" in result.stdout


# --github: the GitHub repo, created through the fake gh.

GITHUB_URL = "https://github.com/test-user/demo"


def github_machine(machine, **gh_options):
    """What ``aa init --github`` needs: a local machine plus a fake gh with ``gh_options``."""
    machine = local_machine(machine)
    machine.add_gh(**gh_options)
    return machine


def repo_creates(machine) -> list:
    return [call for call in machine.gh_calls() if call.args[:2] == ["repo", "create"]]


@pytest.fixture(scope="module")
def github_project(tmp_path_factory, new_machine, aa_in):
    machine = github_machine(new_machine())
    return init(aa_in, tmp_path_factory.mktemp("init-github"), machine, "--github"), machine


def test_init_github_creates_a_private_repo_named_after_the_project_and_pushes(github_project):
    created, machine = github_project

    assert created.result.exit_code == 0, created.result.output
    [call] = repo_creates(machine)
    assert call.args[2] == "demo"
    assert "--private" in call.args
    assert "--public" not in call.args
    assert "--push" in call.args
    source = call.args[call.args.index("--source") + 1]
    assert (call.cwd / source).resolve() == created.project.resolve()


def test_init_github_json_data_has_the_repo_url(github_project):
    created, _ = github_project

    assert created.envelope["data"]["github_url"] == GITHUB_URL


def test_init_github_pushes_one_initial_commit_on_main_with_a_clean_tree(github_project):
    created, machine = github_project

    [call] = repo_creates(machine)
    assert "--push" in call.args
    assert call.last_commit == COMMIT_MESSAGE
    assert created.git("log", "--format=%s").splitlines() == [COMMIT_MESSAGE]
    assert created.git("branch", "--show-current").strip() == "main"
    assert created.git("status", "--porcelain") == ""


def test_init_github_public_creates_a_public_repo_and_shows_its_url(aa, machine):
    machine = github_machine(machine)

    result = aa("init", "demo", "--github", "--public", env=machine.env)

    assert result.exit_code == 0, result.output
    [call] = repo_creates(machine)
    assert "--public" in call.args
    assert "--private" not in call.args
    assert GITHUB_URL in result.stdout


def test_public_without_github_is_a_usage_error_and_creates_nothing(aa, machine, tmp_path):
    machine = github_machine(machine)

    result = aa("init", "demo", "--public", "--json", env=machine.env)

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "usage"
    assert list(tmp_path.iterdir()) == []
    assert repo_creates(machine) == []


def test_init_github_with_gh_signed_out_keeps_the_project_and_gives_the_gh_command_to_rerun(
    aa_in, machine, tmp_path
):
    machine = github_machine(machine, signed_in=False)

    created = init(aa_in, tmp_path, machine, "--github")

    assert created.result.exit_code == 1
    error = created.envelope["error"]
    assert error["code"] == "step_failed"
    assert "gh auth login" in error["message"]
    assert error["fix"].startswith("gh repo create demo ")
    assert created.git("log", "--format=%s").splitlines() == [COMMIT_MESSAGE]
    assert created.git("status", "--porcelain") == ""


def test_init_github_without_gh_keeps_the_project_and_reports_unexpected(aa_in, machine, tmp_path):
    created = init(aa_in, tmp_path, local_machine(machine), "--github")

    assert created.result.exit_code == 3
    assert created.envelope["error"]["code"] == "unexpected"
    assert created.git("log", "--format=%s").splitlines() == [COMMIT_MESSAGE]


def test_a_failed_repo_creation_keeps_the_project_and_gives_the_gh_command_to_rerun(
    aa_in, machine, tmp_path
):
    machine = github_machine(machine, repo_create_fails=True)

    created = init(aa_in, tmp_path, machine, "--github")

    assert created.result.exit_code == 1
    error = created.envelope["error"]
    assert error["code"] == "step_failed"
    assert "Name already exists" in error["message"]
    assert created.git("log", "--format=%s").splitlines() == [COMMIT_MESSAGE]
    assert created.git("status", "--porcelain") == ""
    [call] = repo_creates(machine)
    assert error["fix"] == " ".join(["gh", *call.args])
    assert error["fix"].startswith("gh repo create demo ")
    assert "--source ." in error["fix"]
    assert str(created.project.resolve()) in error["message"]


def test_a_failed_step_in_human_mode_shows_the_error_and_the_fix_on_stderr(aa, machine):
    machine = github_machine(machine, repo_create_fails=True)

    result = aa("init", "demo", "--github", env=machine.env)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Name already exists" in result.stderr
    assert "Fix: gh repo create demo " in result.stderr


def test_a_failed_push_after_the_repo_was_created_gives_the_push_to_rerun(aa_in, machine, tmp_path):
    machine = github_machine(machine, push_fails=True)

    created = init(aa_in, tmp_path, machine, "--github")

    assert created.result.exit_code == 1
    error = created.envelope["error"]
    assert error["code"] == "step_failed"
    assert "exit status 128" in error["message"]
    assert str(created.project.resolve()) in error["message"]
    # gh repo create would fail again now that the repo exists; only the push is left.
    assert error["fix"] == "git push --set-upstream origin main"
    assert created.git("log", "--format=%s").splitlines() == [COMMIT_MESSAGE]


def test_init_github_asks_gh_for_the_url_when_repo_create_prints_none(aa_in, machine, tmp_path):
    machine = github_machine(machine, prints_url=False)

    created = init(aa_in, tmp_path, machine, "--github")

    assert created.result.exit_code == 0, created.result.output
    assert created.envelope["data"]["github_url"] == GITHUB_URL
