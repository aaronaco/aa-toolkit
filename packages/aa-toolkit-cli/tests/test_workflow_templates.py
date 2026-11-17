"""The workflow templates' action pins match the toolkit's own actions.lock (ADR 0009)."""

import re
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES = PACKAGE_DIR / "src" / "aa_cli" / "templates" / "workflows"
ACTIONS_LOCK = PACKAGE_DIR.parents[1] / ".github" / "workflows" / "actions.lock"
_USES = re.compile(r"^\s*(?:- )?uses:\s*([^\s@]+)(?:@(\S+))?(?:\s+#\s*(\S+))?", re.MULTILINE)
_LOCKED = re.compile(
    r"^    '([^']+)':\n        ref: '[^']+'\n        commit: 'sha1-([0-9a-f]{40})'", re.MULTILINE
)


def locked_commits() -> dict[str, str]:
    """``owner/repo@version`` to the commit actions.lock records for it."""
    return dict(_LOCKED.findall(ACTIONS_LOCK.read_text(encoding="utf-8")))


def pins_in(text: str) -> list[tuple[str, str | None, str | None]]:
    """Every ``uses:`` line as (owner/repo, ref, version comment), so none is skipped.

    An action in a subfolder of its repo, such as ``github/codeql-action/upload-sarif``, is
    locked under its repo.
    """
    pins: list[tuple[str, str | None, str | None]] = []
    for match in _USES.finditer(text):
        path, ref, version = match.group(1, 2, 3)
        parts = path.split("/")
        action = "/".join(parts[:2]) if len(parts) > 2 and parts[0] not in (".", "..") else path
        pins.append((action, ref, version))
    return pins


def template_pins() -> list[tuple[str, str, str | None, str | None]]:
    return [
        (template.name, *pin)
        for template in sorted(TEMPLATES.iterdir())
        for pin in pins_in(template.read_text(encoding="utf-8"))
    ]


def test_the_template_folder_holds_only_workflow_templates():
    names = [path.name for path in TEMPLATES.iterdir()]

    assert names
    assert all(name.endswith(".yml") for name in names), names


@pytest.mark.parametrize(("template", "action", "commit", "version"), template_pins())
def test_a_template_pin_matches_the_commit_actions_lock_records(template, action, commit, version):
    # Dependabot bumps the toolkit's workflows, actions.lock and the templates in one PR.
    # If it ever misses a template, this fails on that PR.
    assert commit is not None, f"{template}: {action} isn't pinned to a commit"
    assert re.fullmatch(r"[0-9a-f]{40}", commit), f"{template}: {action}@{commit} isn't a commit"
    assert version is not None, f"{template}: {action}@{commit} has no version comment"
    locked = locked_commits().get(f"{action}@{version}")

    assert locked is not None, (
        f"{template}: actions.lock has no {action}@{version}; pin the version the toolkit's"
        " own workflows use"
    )
    assert commit == locked, f"{template}: {action}@{version} is {locked} in actions.lock"


SHA = "33d7b85da1a04171e211befe2c739303b9a4c066"


def test_an_action_in_a_subfolder_of_its_repo_is_checked_against_its_repo():
    text = f"      - uses: github/codeql-action/upload-sarif@{SHA} # v4.39.3\n"

    assert pins_in(text) == [("github/codeql-action", SHA, "v4.39.3")]


def test_a_uses_line_without_a_commit_pin_is_still_listed():
    text = "      - uses: actions/checkout@v7.0.1\n        with:\n      - uses: ./local-action\n"

    assert pins_in(text) == [("actions/checkout", "v7.0.1", None), ("./local-action", None, None)]
