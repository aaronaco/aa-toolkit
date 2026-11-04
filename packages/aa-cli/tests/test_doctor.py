"""``aa doctor``: machine checks, and the "not a project" result outside a project."""

import json

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
