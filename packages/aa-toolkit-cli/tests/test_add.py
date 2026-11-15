"""``aa add``: setting up pieces in existing projects with real uv and git."""

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest


def uv_machine(machine):
    """A stand-in machine with real uv, real git and a throwaway git identity."""
    machine.add_real("uv")
    machine.add_real("git")
    machine.set_identity(name="Ada Lovelace", email="ada@example.com")
    return machine


def host_env(machine) -> dict[str, str]:
    """The real PATH and environment with the stand-in machine's throwaway git identity."""
    return {
        **os.environ,
        **{k: v for k, v in machine.env.items() if k != "PATH" and v is not None},
    }


def make_uv_project(folder: Path, machine) -> Path:
    """Create a plain Python project in ``folder`` with ``uv init``."""
    subprocess.run(
        ["uv", "init"],
        cwd=folder,
        env=host_env(machine),
        check=True,
        capture_output=True,
        text=True,
    )
    return folder


def run_git(cwd: Path, machine, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=host_env(machine),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def req_names(deps: list[str]) -> set[str]:
    """Normalized package names from PEP 508 requirement strings."""
    return {re.split(r"[<>=!~;\[\s]", dep, maxsplit=1)[0].lower() for dep in deps}


def test_add_ci_writes_workflow_adds_dev_tools_creates_lockfile_and_leaves_git_alone(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)
    init_parent = tmp_path / "init"
    init_parent.mkdir()
    init_result = aa_in(init_parent, "init", "expected", "--json", env=machine.env)
    assert init_result.exit_code == 0, init_result.output
    expected_workflow = (init_parent / "expected" / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project = make_uv_project(project_dir, machine)

    result = aa_in(project, "add", "ci", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope == {
        "ok": True,
        "data": {
            "piece": "ci",
            "files": [".github/workflows/ci.yml", "pyproject.toml", "uv.lock"],
            "next_steps": [],
        },
    }
    assert (project / ".github/workflows/ci.yml").read_text(encoding="utf-8") == expected_workflow
    pyproject = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    dev_deps = pyproject["dependency-groups"]["dev"]
    assert {"ruff", "pytest"} <= req_names(dev_deps)
    assert (project / "uv.lock").is_file()
    assert run_git(project, machine, "diff", "--cached", "--name-only") == ""
    assert run_git(project, machine, "rev-list", "--all", "--count").strip() == "0"


def test_add_ci_in_human_mode_lists_the_same_files(aa_in, machine, tmp_path):
    machine = uv_machine(machine)
    project = make_uv_project(tmp_path, machine)

    result = aa_in(project, "add", "ci", env=machine.env)

    assert result.exit_code == 0, result.output
    for file_path in (".github/workflows/ci.yml", "pyproject.toml", "uv.lock"):
        assert file_path in result.stdout


def test_add_ci_keeps_existing_dependency_version_requirements_unchanged(aa_in, machine, tmp_path):
    machine = uv_machine(machine)

    dev_dir = tmp_path / "has-ruff-in-dev"
    dev_dir.mkdir()
    make_uv_project(dev_dir, machine)
    dev_pyproject = dev_dir / "pyproject.toml"
    dev_pyproject.write_text(
        dev_pyproject.read_text(encoding="utf-8")
        + '\n[dependency-groups]\ndev = ["ruff>=0.16,<0.18"]\n',
        encoding="utf-8",
    )

    res_dev = aa_in(dev_dir, "add", "ci", "--json", env=machine.env)
    assert res_dev.exit_code == 0, res_dev.output
    parsed_dev = tomllib.loads(dev_pyproject.read_text(encoding="utf-8"))
    assert "ruff>=0.16,<0.18" in parsed_dev["dependency-groups"]["dev"]
    assert "pytest" in req_names(parsed_dev["dependency-groups"]["dev"])

    deps_dir = tmp_path / "has-pytest-in-deps"
    deps_dir.mkdir()
    make_uv_project(deps_dir, machine)
    deps_pyproject = deps_dir / "pyproject.toml"
    deps_pyproject.write_text(
        deps_pyproject.read_text(encoding="utf-8").replace(
            "dependencies = []", 'dependencies = ["pytest>=8.0,<10"]'
        ),
        encoding="utf-8",
    )

    res_deps = aa_in(deps_dir, "add", "ci", "--json", env=machine.env)
    assert res_deps.exit_code == 0, res_deps.output
    parsed_deps = tomllib.loads(deps_pyproject.read_text(encoding="utf-8"))
    assert parsed_deps["project"]["dependencies"] == ["pytest>=8.0,<10"]
    assert "pytest" not in req_names(parsed_deps["dependency-groups"]["dev"])
    assert "ruff" in req_names(parsed_deps["dependency-groups"]["dev"])

    both_dir = tmp_path / "has-both-unlocked"
    both_dir.mkdir()
    make_uv_project(both_dir, machine)
    both_pyproject = both_dir / "pyproject.toml"
    both_pyproject.write_text(
        both_pyproject.read_text(encoding="utf-8")
        + '\n[dependency-groups]\ndev = ["ruff>=0.16,<0.18", "pytest>=8.0,<10"]\n',
        encoding="utf-8",
    )
    before_bytes = both_pyproject.read_bytes()

    res_both = aa_in(both_dir, "add", "ci", "--json", env=machine.env)
    assert res_both.exit_code == 0, res_both.output
    assert both_pyproject.read_bytes() == before_bytes
    assert (both_dir / "uv.lock").is_file()
    assert json.loads(res_both.stdout)["data"]["files"] == [".github/workflows/ci.yml", "uv.lock"]

    (both_dir / "uv.lock").unlink()
    res_relock = aa_in(both_dir, "add", "ci", "--json", env=machine.env)
    assert res_relock.exit_code == 0, res_relock.output
    assert (both_dir / "uv.lock").is_file()
    assert json.loads(res_relock.stdout)["data"]["files"] == ["uv.lock"]


def test_add_ci_adds_tools_to_dev_when_only_in_optional_or_non_default_group(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)
    project_dir = tmp_path / "optional-and-non-default"
    project_dir.mkdir()
    project = make_uv_project(project_dir, machine)
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8")
        + '\n[project.optional-dependencies]\nlint = ["ruff>=0.16,<0.18"]\n'
        + '\n[dependency-groups]\ntest = ["pytest>=8.0,<10"]\n',
        encoding="utf-8",
    )

    result = aa_in(project, "add", "ci", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    parsed = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dev_deps = parsed["dependency-groups"]["dev"]
    assert {"ruff", "pytest"} <= req_names(dev_deps)
    assert parsed["project"]["optional-dependencies"]["lint"] == ["ruff>=0.16,<0.18"]
    assert parsed["dependency-groups"]["test"] == ["pytest>=8.0,<10"]

    included_dir = tmp_path / "legacy-dev-included"
    included_dir.mkdir()
    make_uv_project(included_dir, machine)
    included_pyproject = included_dir / "pyproject.toml"
    included_pyproject.write_text(
        included_pyproject.read_text(encoding="utf-8")
        + '\n[tool.uv]\ndefault-groups = "all"\ndev-dependencies = ["ruff>=0.16,<0.18"]\n'
        + '\n[dependency-groups]\ntest = [{include-group = "lint"}]\nlint = []\n',
        encoding="utf-8",
    )

    res_included = aa_in(included_dir, "add", "ci", "--json", env=machine.env)

    assert res_included.exit_code == 0, res_included.output
    parsed_included = tomllib.loads(included_pyproject.read_text(encoding="utf-8"))
    assert "ruff>=0.16,<0.18" in parsed_included["tool"]["uv"]["dev-dependencies"]
    assert {"ruff", "pytest"} <= req_names(parsed_included["tool"]["uv"]["dev-dependencies"])

    excluded_dir = tmp_path / "legacy-dev-excluded"
    excluded_dir.mkdir()
    make_uv_project(excluded_dir, machine)
    excluded_pyproject = excluded_dir / "pyproject.toml"
    excluded_pyproject.write_text(
        excluded_pyproject.read_text(encoding="utf-8")
        + '\n[tool.uv]\ndefault-groups = ["test"]\n'
        + 'dev-dependencies = ["ruff>=0.16,<0.18", "pytest>=8.0,<10"]\n'
        + "\n[dependency-groups]\ntest = []\n",
        encoding="utf-8",
    )
    res_excluded = aa_in(excluded_dir, "add", "ci", "--json", env=machine.env)

    assert res_excluded.exit_code == 0, res_excluded.output
    assert json.loads(res_excluded.stdout)["data"]["files"] == [
        ".github/workflows/ci.yml",
        "pyproject.toml",
        "uv.lock",
    ]


def snapshot(project: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }


def test_existing_workflow_with_different_content_fails_with_file_exists_and_changes_nothing(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)
    project_dir = tmp_path / "workflow-file"
    project_dir.mkdir()
    project = make_uv_project(project_dir, machine)
    workflow = project / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: Custom CI\n", encoding="utf-8")
    before = snapshot(project)

    human = aa_in(project, "add", "ci", env=machine.env)
    as_json = aa_in(project, "add", "ci", "--json", env=machine.env)

    assert human.exit_code == 1
    assert ".github/workflows/ci.yml" in human.stderr
    assert as_json.exit_code == 1
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "file_exists"
    assert ".github/workflows/ci.yml" in error["message"]
    assert snapshot(project) == before
    assert not (project / "uv.lock").exists()

    parent_dir = tmp_path / "parent-file"
    parent_dir.mkdir()
    parent_conflict = make_uv_project(parent_dir, machine)
    (parent_conflict / ".github").write_text("not a dir\n", encoding="utf-8")
    before_parent = snapshot(parent_conflict)

    parent_json = aa_in(parent_conflict, "add", "ci", "--json", env=machine.env)

    assert parent_json.exit_code == 1
    parent_error = json.loads(parent_json.stdout)["error"]
    assert parent_error["code"] == "file_exists"
    assert ".github" in parent_error["message"]
    assert snapshot(parent_conflict) == before_parent
    assert not (parent_conflict / "uv.lock").exists()


def test_when_ci_is_already_there_it_says_so_changes_nothing_and_exits_0(aa_in, machine, tmp_path):
    machine = uv_machine(machine)
    project = make_uv_project(tmp_path, machine)
    first = aa_in(project, "add", "ci", "--json", env=machine.env)
    assert first.exit_code == 0, first.output
    before = snapshot(project)

    human = aa_in(project, "add", "ci", env=machine.env)
    as_json = aa_in(project, "add", "ci", "--json", env=machine.env)

    assert human.exit_code == 0, human.output
    assert "already there" in human.stdout.lower()
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.stdout) == {
        "ok": True,
        "data": {"piece": "ci", "files": [], "next_steps": []},
    }
    assert snapshot(project) == before


def test_when_no_pyproject_is_present_it_fails_with_not_a_project(aa, machine, tmp_path):
    machine = uv_machine(machine)

    human = aa("add", "ci", env=machine.env)
    as_json = aa("add", "ci", "--json", env=machine.env)

    assert human.exit_code == 1
    assert "pyproject.toml" in human.stderr
    assert "project's root folder" in human.stderr
    assert as_json.exit_code == 1
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "not_a_project"
    assert "project's root folder" in error["fix"]
    assert list(tmp_path.iterdir()) == []


def test_when_uv_fails_it_exits_1_with_step_failed_and_writes_no_workflow(aa_in, machine, tmp_path):
    machine.add_real("git")
    machine.set_identity(name="Ada Lovelace", email="ada@example.com")
    project = make_uv_project(tmp_path, machine)
    machine.add_failing("uv", "fake uv: the index is unreachable")

    human = aa_in(project, "add", "ci", env=machine.env)
    as_json = aa_in(project, "add", "ci", "--json", env=machine.env)

    assert human.exit_code == 1
    assert "fake uv: the index is unreachable" in human.stderr
    assert as_json.exit_code == 1
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "step_failed"
    assert "fake uv: the index is unreachable" in error["message"]
    assert not (project / ".github/workflows/ci.yml").exists()


@pytest.mark.parametrize("args", [["add"], ["add", "unknown"]], ids=["missing", "unknown"])
def test_missing_or_unknown_piece_is_a_usage_error_listing_valid_pieces(aa, args):
    human = aa(*args)
    as_json = aa(*args, "--json")

    assert human.exit_code == 2
    assert human.stdout == ""
    assert "ci" in human.stderr
    assert "log" in human.stderr
    assert as_json.exit_code == 2
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "usage"
    assert "ci" in error["message"]
    assert "log" in error["message"]


EXPECTED_LOG_REQUIREMENT = (
    "aa-toolkit-log @ git+https://github.com/aaronaco/aa-toolkit@log-v0.1.0"
    "#subdirectory=packages/aa-toolkit-log"
)


def test_add_log_runs_uv_add_with_pinned_github_requirement_and_leaves_code_and_gitignore_alone(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)
    project_dir = tmp_path / "my-app"
    project_dir.mkdir()
    subprocess.run(
        ["uv", "init", "--package"],
        cwd=project_dir,
        env=host_env(machine),
        check=True,
        capture_output=True,
        text=True,
    )
    gitignore = project_dir / ".gitignore"
    gitignore.write_text("__pycache__/\n.venv/\n", encoding="utf-8")
    before_src = snapshot(project_dir / "src")
    before_gitignore = gitignore.read_bytes()

    machine.add_fake_uv()
    result = aa_in(project_dir, "add", "log", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    calls = machine.uv_calls()
    assert len(calls) == 1
    assert calls[0].cwd == project_dir.resolve()
    assert calls[0].args == ["add", EXPECTED_LOG_REQUIREMENT]
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    data = envelope["data"]
    assert data["piece"] == "log"
    assert data["files"] == ["pyproject.toml", "uv.lock"]
    next_steps = data["next_steps"]
    assert isinstance(next_steps, list)
    assert all(isinstance(item, str) for item in next_steps)
    assert len(next_steps) == 2
    assert "from aa_log import configure_logging" in next_steps[0]
    assert "configure_logging()" in next_steps[0]
    assert "only apps" in next_steps[0].lower()
    assert "library" in next_steps[0].lower()
    assert "*.log" in next_steps[1]
    assert "*.log.[1-3]" in next_steps[1]
    assert snapshot(project_dir / "src") == before_src
    assert gitignore.read_bytes() == before_gitignore
    assert run_git(project_dir, machine, "diff", "--cached", "--name-only") == ""
    assert run_git(project_dir, machine, "rev-list", "--all", "--count").strip() == "0"


def test_add_log_in_human_mode_lists_changed_files_and_next_steps(aa_in, machine, tmp_path):
    machine = uv_machine(machine)
    project = make_uv_project(tmp_path, machine)
    machine.add_fake_uv()

    result = aa_in(project, "add", "log", env=machine.env)

    assert result.exit_code == 0, result.output
    for file_path in ("pyproject.toml", "uv.lock"):
        assert file_path in result.stdout
    assert "from aa_log import configure_logging" in result.stdout
    assert "configure_logging()" in result.stdout
    assert "only apps" in result.stdout.lower()
    assert "library" in result.stdout.lower()
    assert "*.log" in result.stdout
    assert "*.log.[1-3]" in result.stdout


def test_add_log_skips_gitignore_step_when_both_lines_are_present_and_shows_only_missing_ones(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)

    both_dir = tmp_path / "both-present"
    both_dir.mkdir()
    make_uv_project(both_dir, machine)
    (both_dir / ".gitignore").write_text(".venv/\n*.log\n*.log.[1-3]\n", encoding="utf-8")

    only_star_dir = tmp_path / "only-star-log"
    only_star_dir.mkdir()
    make_uv_project(only_star_dir, machine)
    (only_star_dir / ".gitignore").write_text("*.log\n", encoding="utf-8")

    only_rotated_dir = tmp_path / "only-rotated"
    only_rotated_dir.mkdir()
    make_uv_project(only_rotated_dir, machine)
    (only_rotated_dir / ".gitignore").write_text("*.log.[1-3]\n", encoding="utf-8")

    commented_dir = tmp_path / "commented"
    commented_dir.mkdir()
    make_uv_project(commented_dir, machine)
    (commented_dir / ".gitignore").write_text("# *.log\n", encoding="utf-8")

    machine.add_fake_uv()

    res_both = aa_in(both_dir, "add", "log", "--json", env=machine.env)
    assert res_both.exit_code == 0, res_both.output
    both_steps = json.loads(res_both.stdout)["data"]["next_steps"]
    assert len(both_steps) == 1
    assert ".gitignore" not in both_steps[0]

    human_both = aa_in(both_dir, "add", "log", env=machine.env)
    assert human_both.exit_code == 0, human_both.output
    assert ".gitignore" not in human_both.stdout

    no_gitignore_dir = tmp_path / "no-gitignore"
    no_gitignore_dir.mkdir()
    make_uv_project(no_gitignore_dir, machine)
    gitignore_path = no_gitignore_dir / ".gitignore"
    if gitignore_path.exists():
        gitignore_path.unlink()
    res_no_gitignore = aa_in(no_gitignore_dir, "add", "log", "--json", env=machine.env)
    assert res_no_gitignore.exit_code == 0, res_no_gitignore.output
    assert not gitignore_path.exists()
    no_gi_steps = json.loads(res_no_gitignore.stdout)["data"]["next_steps"]
    assert len(no_gi_steps) == 2
    assert "*.log" in no_gi_steps[1]
    assert "*.log.[1-3]" in no_gi_steps[1]

    res_only_star = aa_in(only_star_dir, "add", "log", "--json", env=machine.env)
    assert res_only_star.exit_code == 0, res_only_star.output
    star_steps = json.loads(res_only_star.stdout)["data"]["next_steps"]
    assert len(star_steps) == 2
    assert star_steps[1] == "Add *.log.[1-3] to .gitignore."

    res_only_rotated = aa_in(only_rotated_dir, "add", "log", "--json", env=machine.env)
    assert res_only_rotated.exit_code == 0, res_only_rotated.output
    rotated_steps = json.loads(res_only_rotated.stdout)["data"]["next_steps"]
    assert len(rotated_steps) == 2
    assert rotated_steps[1] == "Add *.log to .gitignore."

    res_commented = aa_in(commented_dir, "add", "log", "--json", env=machine.env)
    assert res_commented.exit_code == 0, res_commented.output
    commented_steps = json.loads(res_commented.stdout)["data"]["next_steps"]
    assert len(commented_steps) == 2
    assert "*.log" in commented_steps[1]
    assert "*.log.[1-3]" in commented_steps[1]


def test_when_log_is_already_a_dependency_it_says_so_skips_uv_prints_next_steps_and_exits_0(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)
    project = make_uv_project(tmp_path, machine)
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            "dependencies = []",
            f'dependencies = ["{EXPECTED_LOG_REQUIREMENT}"]',
        ),
        encoding="utf-8",
    )
    before = snapshot(project)

    human = aa_in(project, "add", "log", env=machine.env)
    as_json = aa_in(project, "add", "log", "--json", env=machine.env)

    assert human.exit_code == 0, human.output
    assert "already there" in human.stdout.lower()
    assert "from aa_log import configure_logging" in human.stdout
    assert "configure_logging()" in human.stdout
    assert "only apps" in human.stdout.lower()
    assert "*.log" in human.stdout
    assert "*.log.[1-3]" in human.stdout

    assert as_json.exit_code == 0, as_json.output
    envelope = json.loads(as_json.stdout)
    assert envelope["ok"] is True
    assert envelope["data"]["piece"] == "log"
    assert envelope["data"]["files"] == []
    assert len(envelope["data"]["next_steps"]) == 2
    assert snapshot(project) == before


def test_add_log_when_uv_fails_exits_1_with_step_failed(aa_in, machine, tmp_path):
    machine.add_real("git")
    machine.set_identity(name="Ada Lovelace", email="ada@example.com")
    project = make_uv_project(tmp_path, machine)
    before = snapshot(project)
    machine.add_failing("uv", "fake uv: failed to fetch tag log-v0.1.0")

    human = aa_in(project, "add", "log", env=machine.env)
    as_json = aa_in(project, "add", "log", "--json", env=machine.env)

    assert human.exit_code == 1
    assert "fake uv: failed to fetch tag log-v0.1.0" in human.stderr
    assert as_json.exit_code == 1
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "step_failed"
    assert "fake uv: failed to fetch tag log-v0.1.0" in error["message"]
    assert snapshot(project) == before
