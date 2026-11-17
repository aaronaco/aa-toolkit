"""The workflow templates' action pins match the toolkit's own actions.lock (ADR 0009)."""

import re
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES = PACKAGE_DIR / "src" / "aa_cli" / "templates" / "workflows"
ACTIONS_LOCK = PACKAGE_DIR.parents[1] / ".github" / "workflows" / "actions.lock"
_PIN = re.compile(r"uses: ([\w.-]+/[\w.-]+)@([0-9a-f]{40}) # (v\S+)")
_LOCKED = re.compile(
    r"^    '([^']+)':\n        ref: '[^']+'\n        commit: 'sha1-([0-9a-f]{40})'", re.MULTILINE
)


def locked_commits() -> dict[str, str]:
    """``owner/repo@version`` to the commit actions.lock records for it."""
    return dict(_LOCKED.findall(ACTIONS_LOCK.read_text(encoding="utf-8")))


def template_pins() -> list[tuple[str, str, str, str]]:
    return [
        (template.name, *pin)
        for template in sorted(TEMPLATES.iterdir())
        for pin in _PIN.findall(template.read_text(encoding="utf-8"))
    ]


def test_the_template_folder_holds_only_workflow_templates():
    names = [path.name for path in TEMPLATES.iterdir()]

    assert names
    assert all(name.endswith(".yml") for name in names), names


@pytest.mark.parametrize(("template", "action", "commit", "version"), template_pins())
def test_a_template_pin_matches_the_commit_actions_lock_records(template, action, commit, version):
    # Dependabot bumps the toolkit's workflows, actions.lock and the templates in one PR.
    # If it ever misses a template, this fails on that PR.
    locked = locked_commits().get(f"{action}@{version}")

    assert locked is not None, (
        f"{template}: actions.lock has no {action}@{version}; pin the version the toolkit's"
        " own workflows use"
    )
    assert commit == locked, f"{template}: {action}@{version} is {locked} in actions.lock"
