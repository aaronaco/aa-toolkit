def test_help_lists_the_global_flags(aa):
    result = aa("--help")

    assert result.exit_code == 0
    for flag in ("--json", "--verbose", "--version"):
        assert flag in result.stdout
