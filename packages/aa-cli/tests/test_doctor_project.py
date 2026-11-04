"""``aa doctor`` inside a project: the project checks, against projects made by ``aa init``."""

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

MACHINE_IDS = ["uv", "git", "git_identity", "gh", "gh_auth"]
PROJECT_IDS = ["aa_config", "python_version", "lockfile", "agents_md", "ci"]


def checks_by_id(envelope):
    return {check["id"]: check for check in envelope["data"]["checks"]}


@pytest.fixture(scope="module")
def made_project(tmp_path_factory, new_machine, aa_in) -> Path:
    """One project made by ``aa init``, shared by the tests in this module. Never change it."""
    folder = tmp_path_factory.mktemp("made")
    result = aa_in(folder, "init", "demo", "--json", env=new_machine().full().env)
    assert result.exit_code == 0, result.output
    return folder / "demo"


@pytest.fixture
def project(made_project, tmp_path) -> Path:
    """A copy of the made project, with its git history, that a test may change."""
    copy = tmp_path / "demo"
    shutil.copytree(made_project, copy, ignore=shutil.ignore_patterns(".venv"))
    return copy


def test_doctor_in_a_project_made_by_init_passes_every_check(aa_in, machine, project):
    result = aa_in(project, "doctor", "--json", env=machine.full().env)

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    checks = envelope["data"]["checks"]
    assert [check["id"] for check in checks] == [*MACHINE_IDS, *PROJECT_IDS]
    assert [check["scope"] for check in checks] == ["machine"] * 5 + ["project"] * 5
    assert all(check["status"] == "pass" for check in checks)


def test_doctor_in_a_lib_project_made_by_init_passes_every_check(aa_in, machine, tmp_path):
    machine.full()
    made = aa_in(tmp_path, "init", "demo", "--lib", "--json", env=machine.env)
    assert made.exit_code == 0, made.output

    result = aa_in(tmp_path / "demo", "doctor", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    checks = checks_by_id(json.loads(result.stdout))
    assert [check_id for check_id in checks if checks[check_id]["scope"] == "project"] == (
        PROJECT_IDS
    )
    assert all(check["status"] == "pass" for check in checks.values())


def test_doctor_from_a_subfolder_finds_the_project_and_runs_its_checks(aa_in, machine, project):
    result = aa_in(project / "src" / "demo", "doctor", "--json", env=machine.full().env)

    assert result.exit_code == 0, result.output
    checks = checks_by_id(json.loads(result.stdout))
    assert "project" not in checks
    assert all(checks[check_id]["status"] == "pass" for check_id in PROJECT_IDS)


def test_human_output_groups_machine_and_project_checks_under_headings(aa_in, machine, project):
    result = aa_in(project, "doctor", env=machine.full().env)

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    machine_heading, project_heading = lines.index("Machine"), lines.index("Project")
    assert machine_heading < project_heading
    for check_id in MACHINE_IDS:
        line = next(i for i, text in enumerate(lines) if f" {check_id}:" in text)
        assert machine_heading < line < project_heading, check_id
    for check_id in PROJECT_IDS:
        line = next(i for i, text in enumerate(lines) if f" {check_id}:" in text)
        assert project_heading < line and "[ok]" in lines[line], check_id


@pytest.mark.parametrize(
    "aa_section",
    ["[tool.aa]\n", '[tool.aa]\nkind = "app"\n', "[tool.aa]\nkind = 1\n", '[tool]\naa = "cli"\n'],
    ids=["missing-kind", "unknown-kind", "kind-not-a-string", "not-a-table"],
)
def test_a_missing_or_unknown_kind_fails_aa_config_with_a_fix(aa_in, machine, project, aa_section):
    pyproject = project / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(text.replace('[tool.aa]\nkind = "cli"\n', aa_section), encoding="utf-8")

    result = aa_in(project, "doctor", "--json", env=machine.full().env)

    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["error"]["code"] == "checks_failed"
    checks = checks_by_id(envelope)
    assert checks["aa_config"]["status"] == "fail"
    assert "kind" in checks["aa_config"]["fix"]
    assert all(checks[check_id]["status"] == "pass" for check_id in PROJECT_IDS[1:])


def test_a_deleted_python_version_fails_with_the_uv_pin_command(aa_in, machine, project):
    (project / ".python-version").unlink()

    result = aa_in(project, "doctor", "--json", env=machine.full().env)

    assert result.exit_code == 1
    checks = checks_by_id(json.loads(result.stdout))
    assert checks["python_version"]["status"] == "fail"
    assert checks["python_version"]["fix"] == "uv python pin 3.15"
    assert checks["agents_md"]["status"] == "pass"


def test_from_a_subfolder_a_fix_first_changes_to_the_project_folder(aa_in, machine, project):
    (project / ".python-version").unlink()

    result = aa_in(project / "src" / "demo", "doctor", "--json", env=machine.full().env)

    fix = checks_by_id(json.loads(result.stdout))["python_version"]["fix"]
    assert fix == f'cd "{project}"; uv python pin 3.15'


def test_dependencies_changed_without_relocking_fail_lockfile_with_uv_lock(aa_in, machine, project):
    pyproject = project / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "dependencies = []" in text
    pyproject.write_text(text.replace("dependencies = []", 'dependencies = ["idna"]'))

    result = aa_in(project, "doctor", "--json", env=machine.full().env)

    assert result.exit_code == 1
    checks = checks_by_id(json.loads(result.stdout))
    assert checks["lockfile"]["status"] == "fail"
    assert checks["lockfile"]["fix"] == "uv lock"
    assert checks["aa_config"]["status"] == "pass"


def test_a_missing_lockfile_fails_lockfile_with_uv_lock(aa_in, machine, project):
    (project / "uv.lock").unlink()

    result = aa_in(project, "doctor", "--json", env=machine.full().env)

    assert result.exit_code == 1
    check = checks_by_id(json.loads(result.stdout))["lockfile"]
    assert check["status"] == "fail"
    assert "not found" in check["message"]
    assert check["fix"] == "uv lock"


def test_a_lock_check_uv_cannot_run_fails_lockfile_with_uvs_error(aa_in, machine, project):
    pyproject = project / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(text.replace("dependencies = []", 'dependencies = ["not a spec!"]'))

    result = aa_in(project, "doctor", "--json", env=machine.full().env)

    assert result.exit_code == 1
    check = checks_by_id(json.loads(result.stdout))["lockfile"]
    assert check["status"] == "fail"
    assert "out of sync" not in check["message"]
    assert "not a spec!" in check["message"]
    # Relocking fails the same way, so the fix must not be uv lock on its own.
    assert check["fix"] != "uv lock"
    assert check["fix"].endswith("then run uv lock")


def test_without_uv_lockfile_fails_pointing_at_the_uv_check(aa_in, machine, project):
    machine.add_real("git")
    machine.add_gh(signed_in=True)
    machine.set_identity()

    result = aa_in(project, "doctor", "--json", env=machine.env)

    assert result.exit_code == 1
    checks = checks_by_id(json.loads(result.stdout))
    assert checks["uv"]["status"] == "fail"
    assert checks["lockfile"]["status"] == "fail"
    assert checks["lockfile"]["scope"] == "project"
    assert "uv check" in checks["lockfile"]["message"]
    assert checks["lockfile"]["fix"] == checks["uv"]["fix"]
    for check_id in ["aa_config", "python_version", "agents_md", "ci"]:
        assert checks[check_id]["status"] == "pass", check_id


@pytest.mark.parametrize(
    ("check_id", "path"),
    [("agents_md", "AGENTS.md"), ("ci", ".github/workflows/ci.yml")],
    ids=["agents_md", "ci"],
)
def test_a_deleted_file_fails_its_check_and_the_fix_restores_it(
    aa_in, machine, project, check_id, path
):
    machine.full()
    (project / path).unlink()

    result = aa_in(project, "doctor", "--json", env=machine.env)

    assert result.exit_code == 1
    checks = checks_by_id(json.loads(result.stdout))
    assert checks[check_id]["status"] == "fail"
    others = [other for other in PROJECT_IDS if other != check_id]
    assert all(checks[other]["status"] == "pass" for other in others)
    env = {**os.environ, **{k: v for k, v in machine.env.items() if k != "PATH"}}
    subprocess.run(shlex.split(checks[check_id]["fix"]), cwd=project, env=env, check=True)
    assert aa_in(project, "doctor", "--json", env=machine.env).exit_code == 0


def test_a_file_missing_from_git_too_gets_a_fix_that_says_to_write_it(aa_in, machine, project):
    # Git keeps its objects read-only, which Windows will not delete as they are.
    shutil.rmtree(project / ".git", onexc=lambda func, path, _: (os.chmod(path, 0o700), func(path)))
    (project / "AGENTS.md").unlink()

    result = aa_in(project, "doctor", "--json", env=machine.full().env)

    check = checks_by_id(json.loads(result.stdout))["agents_md"]
    assert check["status"] == "fail"
    assert check["fix"].startswith("Create AGENTS.md")
