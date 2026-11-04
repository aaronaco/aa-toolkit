"""Ctrl+C: an interrupted aa reports ``aborted`` with exit 130, never a crash."""

import json


def doctor_machine(machine):
    """A machine where Ctrl+C is pressed while ``aa doctor`` waits on gh."""
    machine.add_real("uv")
    machine.add_real("git")
    machine.set_identity()
    machine.add_ctrl_c("gh")
    return machine


def test_interrupted_json_mode_is_one_aborted_envelope_with_exit_130(aa, machine):
    result = aa("--json", "doctor", env=doctor_machine(machine).env)

    assert result.exit_code == 130
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "aborted"
    assert "Traceback" not in result.stdout


def test_interrupted_human_mode_says_aborted_on_stderr_with_exit_130(aa, machine):
    result = aa("doctor", env=doctor_machine(machine).env)

    assert result.exit_code == 130
    assert "Aborted" in result.stderr
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_interrupted_init_says_the_folder_was_left_as_it_is(aa, machine, tmp_path):
    machine.add_real("git")
    machine.set_identity()
    machine.add_ctrl_c("uv")  # Ctrl+C during uv init, after git init wrote .git

    result = aa("init", "demo", "--json", env=machine.env)

    assert result.exit_code == 130
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "aborted"
    project = tmp_path / "demo"
    assert str(project.resolve()) in error["message"]
    assert "left as it is" in error["message"]
    assert (project / ".git").is_dir()
