def test_verbose_logs_go_to_stderr_and_leave_stdout_alone(aa, package_version):
    quiet = aa("--version")
    loud = aa("--verbose", "--version")

    assert quiet.stderr == ""
    assert loud.stderr.strip()
    assert loud.stdout == quiet.stdout == f"{package_version}\n"
