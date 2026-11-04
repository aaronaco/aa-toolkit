"""``aa doctor``: machine checks, and the "not a project" result outside a project."""

import json

import pytest

MACHINE_IDS = ["uv", "git", "git_identity", "gh", "gh_auth"]


def checks_by_id(envelope):
    return {check["id"]: check for check in envelope["data"]["checks"]}


def test_doctor_on_a_ready_machine_passes_every_machine_check(aa, machine):
    result = aa("doctor", env=machine.full().env)

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    for check_id in MACHINE_IDS:
        assert any(check_id in line and "[ok]" in line for line in lines), check_id
    assert any("not a project" in line and "[info]" in line for line in lines)


def test_doctor_json_lists_every_check_with_its_fields(aa, machine):
    result = aa("doctor", "--json", env=machine.full().env)

    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    checks = envelope["data"]["checks"]
    assert [check["id"] for check in checks if check["scope"] == "machine"] == MACHINE_IDS
    for check in checks:
        assert set(check) == {"id", "scope", "status", "message", "fix"}
    assert all(check["status"] == "pass" for check in checks if check["scope"] == "machine")
    assert all(check["fix"] is None for check in checks if check["status"] == "pass")


def test_missing_uv_fails_its_check_and_the_other_checks_still_run(aa, machine):
    machine.add_real("git")
    machine.add_gh(signed_in=True)
    machine.set_identity()

    result = aa("--json", "doctor", env=machine.env)

    assert result.exit_code == 1
    checks = checks_by_id(json.loads(result.stdout))
    assert checks["uv"]["status"] == "fail"
    assert checks["uv"]["fix"]
    for check_id in ["git", "git_identity", "gh", "gh_auth"]:
        assert checks[check_id]["status"] == "pass", check_id


def test_missing_git_fails_git_and_points_git_identity_at_it(aa, machine):
    machine.add_real("uv")
    machine.add_gh(signed_in=True)

    result = aa("doctor", "--json", env=machine.env)

    assert result.exit_code == 1
    checks = checks_by_id(json.loads(result.stdout))
    assert checks["git"]["status"] == "fail"
    assert checks["git"]["fix"]
    assert checks["git_identity"]["status"] == "fail"
    assert "git check" in checks["git_identity"]["message"]
    assert checks["git_identity"]["fix"]


@pytest.mark.parametrize(
    ("name", "email", "missing"),
    [
        (None, None, ["user.name", "user.email"]),
        (None, "test@example.com", ["user.name"]),
        ("Test User", None, ["user.email"]),
    ],
    ids=["no-name-or-email", "no-name", "no-email"],
)
def test_missing_git_identity_fails_with_the_git_config_commands(aa, machine, name, email, missing):
    machine.full()
    machine.set_identity(name=name, email=email)

    result = aa("doctor", "--json", env=machine.env)

    assert result.exit_code == 1
    check = checks_by_id(json.loads(result.stdout))["git_identity"]
    assert check["status"] == "fail"
    for key in missing:
        assert f"git config --global {key}" in check["fix"]


def test_missing_gh_fails_gh_and_points_gh_auth_at_it(aa, machine):
    machine.add_real("uv")
    machine.add_real("git")
    machine.set_identity()

    result = aa("doctor", "--json", env=machine.env)

    assert result.exit_code == 1
    checks = checks_by_id(json.loads(result.stdout))
    assert checks["gh"]["status"] == "fail"
    assert checks["gh"]["fix"]
    assert checks["gh_auth"]["status"] == "fail"
    assert "gh check" in checks["gh_auth"]["message"]


def test_signed_out_gh_fails_gh_auth_with_the_sign_in_command(aa, machine):
    machine.full()
    machine.add_gh(signed_in=False)

    result = aa("doctor", "--json", env=machine.env)

    assert result.exit_code == 1
    checks = checks_by_id(json.loads(result.stdout))
    assert checks["gh"]["status"] == "pass"
    assert checks["gh_auth"]["status"] == "fail"
    assert checks["gh_auth"]["fix"] == "gh auth login"


def test_failed_checks_in_json_are_a_checks_failed_envelope_with_every_check(aa, machine):
    machine.add_gh(signed_in=False)

    result = aa("doctor", "--json", env=machine.env)

    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "checks_failed"
    ids = [check["id"] for check in envelope["data"]["checks"]]
    assert ids == [*MACHINE_IDS, "project"]
    statuses = [check["status"] for check in envelope["data"]["checks"]]
    assert statuses == ["fail", "fail", "fail", "pass", "fail", "info"]


def test_failed_checks_in_human_mode_show_the_fix_under_each_failure(aa, machine):
    machine.full()
    machine.add_gh(signed_in=False)

    result = aa("doctor", env=machine.env)

    assert result.exit_code == 1
    lines = result.stdout.splitlines()
    failed = next(i for i, line in enumerate(lines) if "[fail]" in line and "gh_auth" in line)
    assert "gh auth login" in lines[failed + 1]
    assert "gh_auth" in result.stderr


@pytest.mark.parametrize(
    "pyproject",
    [None, '[project]\nname = "plain"\n', "[tool.ruff]\nline-length = 100\n"],
    ids=["no-pyproject", "no-tool-section", "other-tool-only"],
)
def test_a_folder_without_aa_config_is_not_a_project_and_never_fails(
    aa, machine, tmp_path, pyproject
):
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject)

    result = aa("doctor", "--json", env=machine.full().env)

    assert result.exit_code == 0
    project = [
        check
        for check in json.loads(result.stdout)["data"]["checks"]
        if check["scope"] == "project"
    ]
    assert project == [
        {
            "id": "project",
            "scope": "project",
            "status": "info",
            "message": "not a project",
            "fix": None,
        }
    ]


def test_a_subfolder_of_a_repo_without_aa_config_is_not_a_project(
    aa, machine, tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "plain"\n')
    subfolder = tmp_path / "src" / "plain"
    subfolder.mkdir(parents=True)
    monkeypatch.chdir(subfolder)

    result = aa("doctor", "--json", env=machine.full().env)

    assert result.exit_code == 0
    assert checks_by_id(json.loads(result.stdout))["project"]["message"] == "not a project"


def test_a_folder_with_aa_config_is_not_reported_as_not_a_project(aa, machine, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n\n[tool.aa]\nkind = "cli"\n'
    )

    result = aa("doctor", "--json", env=machine.full().env)

    assert "project" not in checks_by_id(json.loads(result.stdout))


def test_an_unreadable_pyproject_is_not_a_project_rather_than_a_crash(aa, machine, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project\nname = ")

    result = aa("doctor", "--json", env=machine.full().env)

    assert result.exit_code == 0
    assert checks_by_id(json.loads(result.stdout))["project"]["message"] == "not a project"


def test_verbose_logs_each_external_command_and_its_exit_code_to_stderr(aa, machine):
    machine.full()
    machine.add_gh(signed_in=False)

    quiet = aa("doctor", "--json", env=machine.env)
    loud = aa("doctor", "--json", "--verbose", env=machine.env)

    assert "git config --get user.name" not in quiet.stderr
    assert loud.stdout == quiet.stdout
    lines = loud.stderr.splitlines()
    assert any("git config --get user.name" in line and "exit 0" in line for line in lines)
    assert any("gh auth status" in line and "exit 1" in line for line in lines)
