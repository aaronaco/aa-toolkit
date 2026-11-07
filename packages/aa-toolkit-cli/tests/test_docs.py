"""The toolkit's docs: what they no longer describe."""

import re
import subprocess

import pytest

REMOVED = re.compile(
    r"aa doctor|\[tool\.aa\]|preflight_failed|checks_failed|\bchecks\b|\*\*Check\*\*"
    r"|carry `data`"
)


@pytest.mark.parametrize("doc", ["README.md", "GLOSSARY.md"])
def test_the_doc_does_not_mention_what_was_removed(package_dir, doc):
    text = (package_dir.parents[1] / doc).read_text(encoding="utf-8")

    assert REMOVED.findall(text) == []


def test_the_readme_says_init_commits_only_with_github(package_dir):
    readme = (package_dir.parents[1] / "README.md").read_text(encoding="utf-8")

    assert "`aa init` commits only with `--github`" in readme


def test_the_glossary_defines_a_project_without_aa_config(package_dir):
    glossary = (package_dir.parents[1] / "GLOSSARY.md").read_text(encoding="utf-8")

    definition = glossary.split("**Project**:\n")[1].split("\n")[0]
    assert "aa init" in definition
    assert "config" not in definition


def test_the_readme_installs_aa_from_the_cli_package_folder(package_dir):
    readme = (package_dir.parents[1] / "README.md").read_text(encoding="utf-8")

    installs = re.findall(r"^uv tool install .*--editable .*$", readme, flags=re.MULTILINE)
    assert installs == [
        "uv tool install --editable ./packages/aa-toolkit-cli",
        "uv tool install --force --editable ./packages/aa-toolkit-cli",
    ]
    assert package_dir.name == "aa-toolkit-cli"


def test_the_repo_names_the_cli_package_only_by_its_new_name(package_dir):
    # The bracket keeps this pattern from matching its own source line.
    found = subprocess.run(
        ["git", "grep", "-n", "-e", "aa[-]cli", "--", ".", ":!docs/research"],
        cwd=package_dir.parents[1],
        capture_output=True,
        text=True,
    )

    assert found.stdout == ""
    assert found.returncode == 1
