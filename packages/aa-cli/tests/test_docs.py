"""The toolkit's docs: what they no longer describe."""

import re

import pytest

REMOVED = re.compile(
    r"aa doctor|\[tool\.aa\]|preflight_failed|checks_failed|\bchecks\b|\*\*Check\*\*"
)


@pytest.mark.parametrize("doc", ["README.md", "GLOSSARY.md"])
def test_the_doc_does_not_mention_what_was_removed(package_dir, doc):
    text = (package_dir.parents[1] / doc).read_text(encoding="utf-8")

    assert REMOVED.findall(text) == []


def test_the_glossary_defines_a_project_without_aa_config(package_dir):
    glossary = (package_dir.parents[1] / "GLOSSARY.md").read_text(encoding="utf-8")

    definition = glossary.split("**Project**:\n")[1].split("\n")[0]
    assert "aa init" in definition
    assert "config" not in definition
