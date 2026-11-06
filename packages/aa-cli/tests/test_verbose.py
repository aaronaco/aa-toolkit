def test_verbose_logs_go_to_stderr_and_leave_stdout_alone(aa, package_version):
    quiet = aa("--version")
    loud = aa("--verbose", "--version")

    assert quiet.stderr == ""
    assert loud.stderr.strip()
    assert loud.stdout == quiet.stdout == f"{package_version}\n"


def test_verbose_logs_each_external_command_and_its_exit_code_to_stderr(aa_in, machine, tmp_path):
    machine.add_real("git")
    machine.set_identity()
    machine.add_failing("uv", "fake uv: the index is unreachable")
    (tmp_path / "quiet").mkdir()
    (tmp_path / "loud").mkdir()

    quiet = aa_in(tmp_path / "quiet", "init", "demo", "--json", env=machine.env)
    loud = aa_in(tmp_path / "loud", "init", "demo", "--json", "--verbose", env=machine.env)

    assert "git init" not in quiet.stderr
    assert loud.stdout == quiet.stdout
    lines = loud.stderr.splitlines()
    assert any("git init" in line and "exit 0" in line for line in lines)
    assert any("uv init" in line and "exit 1" in line for line in lines)
