"""What the docs tell a developer about the redaction library."""

import re
import subprocess
import sys

import pytest

GLOSSARY_TERMS = {
    "Redaction library": (
        "The library that takes sensitive values out of text and data before they leave an app.\n"
        "_Avoid_: anonymizer, scrubber, sanitizer"
    ),
    "Detector": (
        "The part of the redaction library that finds one kind of sensitive value in text. "
        "It can be built in or added by an app.\n"
        "_Avoid_: recognizer, scanner, adapter"
    ),
    "Sensitive name": (
        "A field name whose value is always redacted, whatever the value looks like.\n"
        "_Avoid_: blocklist, mask key"
    ),
    "Known value": (
        "A sensitive value an app already holds and asks to have redacted wherever it appears.\n"
        "_Avoid_: deny list"
    ),
    "Placeholder": (
        "The text left where a redacted value used to be, naming only what kind of value it was, "
        "such as `[EMAIL]`.\n"
        "_Avoid_: mask, token"
    ),
}


@pytest.fixture
def readme(package_dir):
    return (package_dir / "README.md").read_text(encoding="utf-8")


def test_the_readme_installs_from_github_with_a_version_tag(readme):
    url = "git+https://github.com/aaronaco/aa-toolkit@redact-v0.1.0"
    assert f'uv add "aa-toolkit-redact @ {url}#subdirectory=packages/aa-toolkit-redact"' in readme


@pytest.mark.parametrize(
    "name", ["Redactor()", "pattern(", "Finding(", "detectors=", "without=", "`[EMAIL]`"]
)
def test_the_readme_covers_the_public_interface(readme, name):
    assert name in readme


def test_setup_is_the_first_example_and_takes_a_few_lines(readme):
    first = re.search(r"```python\n(.*?)```", readme, re.DOTALL)

    assert first
    assert "Redactor()" in first[1]
    assert len(first[1].strip().splitlines()) <= 6


def test_every_example_in_the_readme_prints_what_the_readme_says(readme):
    examples = re.findall(r"```python\n(.*?)```\n\n.*?\n\n```text\n(.*?)```", readme, re.DOTALL)
    assert len(examples) == readme.count("```python") >= 4

    for code, printed in examples:
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

        assert done.stderr == ""
        assert done.stdout == printed


def test_the_root_readme_lists_the_redaction_library(repo):
    root_readme = (repo / "README.md").read_text(encoding="utf-8")

    assert "| `packages/aa-toolkit-redact` | The redaction library" in root_readme
    assert "`aa_redact`" in root_readme
    assert "(packages/aa-toolkit-redact/README.md)" in root_readme


@pytest.mark.parametrize("term", GLOSSARY_TERMS)
def test_the_glossary_defines_the_term(repo, term):
    glossary = (repo / "GLOSSARY.md").read_text(encoding="utf-8")

    assert glossary.split(f"**{term}**:\n")[1].split("\n\n")[0] == GLOSSARY_TERMS[term]


def test_the_new_glossary_terms_come_right_after_the_log_library(repo):
    terms = re.findall(r"^\*\*(.+)\*\*:$", (repo / "GLOSSARY.md").read_text("utf-8"), re.MULTILINE)

    after_log = terms.index("Log library") + 1
    assert terms[after_log : after_log + 5] == list(GLOSSARY_TERMS)


@pytest.mark.parametrize(
    ("file", "title", "sentences"),
    [
        (
            "0004-redaction-library-without-dependencies.md",
            "# The redaction library is written here, with no third-party dependencies",
            [
                "We write a small library of Detectors on the standard library "
                "instead of adopting an existing one.",
                "every built-in pattern must stay fast on hostile input.",
            ],
        ),
        (
            "0005-redact-log-fields-before-formatting.md",
            "# Logs are redacted field by field, before formatting",
            [
                "before the formatter builds the line, and never the finished line.",
                "Redaction runs in a handler filter that passes on a redacted copy of the record.",
            ],
        ),
    ],
)
def test_the_decision_record_is_there(repo, file, title, sentences):
    record = (repo / "docs" / "adr" / file).read_text(encoding="utf-8")

    assert record.splitlines()[0] == title
    assert "\n## Consequences\n" in record
    for sentence in sentences:
        assert sentence in record
