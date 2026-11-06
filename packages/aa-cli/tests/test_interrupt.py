"""Ctrl+C: an interrupted aa reports ``aborted`` with exit 130, never a crash."""

import json
from pathlib import Path


def ctrl_c_machine(machine):
    """A machine where Ctrl+C is pressed while ``aa init`` waits on uv, after git init ran."""
    machine.add_real("git")
    machine.set_identity()
    machine.add_ctrl_c("uv")
    return machine


def test_interrupted_json_mode_is_one_aborted_envelope_with_exit_130(aa, machine):
    result = aa("--json", "init", "demo", env=ctrl_c_machine(machine).env)

    assert result.exit_code == 130
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "aborted"
    assert "Traceback" not in result.stdout


def test_interrupted_human_mode_says_aborted_on_stderr_with_exit_130(aa, machine):
    result = aa("init", "demo", env=ctrl_c_machine(machine).env)

    assert result.exit_code == 130
    assert "Aborted" in result.stderr
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_interrupted_init_says_the_folder_was_left_as_it_is(aa, machine, tmp_path):
    result = aa("init", "demo", "--json", env=ctrl_c_machine(machine).env)

    assert result.exit_code == 130
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "aborted"
    project = tmp_path / "demo"
    assert str(project.resolve()) in error["message"]
    assert "left as it is" in error["message"]
    assert (project / ".git").is_dir()


def test_ctrl_c_before_init_starts_writing_is_aborted_and_names_no_folder(
    aa_in, tmp_path, monkeypatch
):
    def press_ctrl_c(cls):
        raise KeyboardInterrupt

    monkeypatch.setattr(Path, "cwd", classmethod(press_ctrl_c))

    result = aa_in(tmp_path, "init", "demo", "--json")

    assert result.exit_code == 130
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "aborted"
    assert error["message"] == "Aborted"
    assert list(tmp_path.iterdir()) == []
