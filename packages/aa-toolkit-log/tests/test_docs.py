"""What the docs tell a developer about the log library."""

import logging
import re
import subprocess

import pytest


@pytest.fixture
def readme(package_dir):
    return (package_dir / "README.md").read_text(encoding="utf-8")


@pytest.fixture
def glossary(package_dir):
    return (package_dir.parents[1] / "GLOSSARY.md").read_text(encoding="utf-8")


def test_the_readme_installs_from_github_with_a_version_tag(readme):
    url = "git+https://github.com/aaronaco/aa-toolkit@log-v0.1.0"
    assert f'uv add "aa-toolkit-log @ {url}#subdirectory=packages/aa-toolkit-log"' in readme


@pytest.mark.parametrize(
    "name",
    [
        "configure_logging(",
        "get_logger(__name__)",
        "`AA_LOG_LEVEL`",
        "`AA_LOG_FORMAT`",
        "`AA_LOG_FILE`",
    ],
)
def test_the_readme_covers_the_public_interface(readme, name):
    assert name in readme


def test_the_readme_says_to_ignore_log_files(readme):
    assert "`*.log`" in readme
    assert "`.gitignore`" in readme


def test_the_readme_warns_that_logs_do_not_hide_secrets(readme):
    assert "don't hide secrets" in readme


def test_the_readme_lists_every_name_python_reserves_in_extra(readme):
    reserved = {*vars(logging.makeLogRecord({})), "message", "asctime"}

    assert [name for name in sorted(reserved) if f"`{name}`" not in readme] == []


def test_the_root_readme_lists_the_log_library(package_dir):
    root_readme = (package_dir.parents[1] / "README.md").read_text(encoding="utf-8")

    assert "| `packages/aa-toolkit-log` | " in root_readme
    assert "`aa_log`" in root_readme


def test_the_glossary_defines_app(glossary):
    definition = glossary.split("**App**:\n")[1].split("\n\n")[0]

    assert "A program someone runs, as opposed to a library that other code imports." in definition
    assert "An app decides how its logs look and where they go." in definition
    assert "_Avoid_: program, service" in definition


def test_the_glossary_defines_log_library(glossary):
    definition = glossary.split("**Log library**:\n")[1].split("\n\n")[0]

    assert "The library that gives an app a ready-made logging setup." in definition
    assert "_Avoid_: log engine, logger (when you mean the library)" in definition


def test_the_ignore_rules_in_the_readme_cover_a_log_file_and_its_old_copies(readme, tmp_path):
    rules = re.findall(r"`(\*\.log[^`]*)`", readme)
    (tmp_path / ".gitignore").write_text("\n".join(rules) + "\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    names = ["app.log", "app.log.1", "app.log.2", "app.log.3"]

    done = subprocess.run(
        ["git", "check-ignore", "--no-index", *names], cwd=tmp_path, capture_output=True, text=True
    )

    assert done.stdout.split() == names


def test_the_readme_says_a_bad_level_falls_back_to_the_level_argument(readme):
    assert "A bad `AA_LOG_LEVEL` gives a warning and the `level` argument is used" in readme
