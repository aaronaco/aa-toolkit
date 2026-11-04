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
