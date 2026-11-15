"""``aa add``: setting up pieces in existing projects with real uv and git."""

import json
import os
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
    assert any(dep.startswith("ruff") for dep in dev_deps)
    assert any(dep.startswith("pytest") for dep in dev_deps)
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
    assert any(dep.startswith("pytest") for dep in parsed_dev["dependency-groups"]["dev"])

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
    assert not any(dep.startswith("pytest") for dep in parsed_deps["dependency-groups"]["dev"])
    assert any(dep.startswith("ruff") for dep in parsed_deps["dependency-groups"]["dev"])

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


def test_add_ci_adds_tools_to_dev_when_only_in_optional_or_non_default_group(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)
    project = make_uv_project(tmp_path, machine)
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
    assert any(dep.startswith("ruff") for dep in dev_deps)
    assert any(dep.startswith("pytest") for dep in dev_deps)
    assert parsed["project"]["optional-dependencies"]["lint"] == ["ruff>=0.16,<0.18"]
    assert parsed["dependency-groups"]["test"] == ["pytest>=8.0,<10"]


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
    project = make_uv_project(tmp_path, machine)
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
    assert as_json.exit_code == 2
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "usage"
    assert "ci" in error["message"]
