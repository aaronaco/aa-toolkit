"""The toolkit's own setup: Python versions, dev tools, README and CI."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_project_needs_python_314_and_holds_dev_tools_without_being_a_package():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert pyproject["project"]["requires-python"] == ">=3.14"
    assert pyproject["tool"]["uv"]["package"] is False
    dev_tools = " ".join(pyproject["dependency-groups"]["dev"])
    assert "ruff" in dev_tools
    assert "pytest" in dev_tools


def test_development_python_is_pinned_to_315():
    assert (ROOT / ".python-version").read_text().strip() == "3.15"


def test_readme_explains_the_editable_install_and_the_forced_reinstall():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "uv tool install --editable ./packages/aa-cli" in readme
    assert "uv tool install --force --editable ./packages/aa-cli" in readme


def test_ci_runs_lint_format_and_tests_on_windows_and_linux_from_the_lockfile():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for expected in (
        "branches: [main]",
        "pull_request:",
        "ubuntu-latest",
        "windows-latest",
        'python: "3.14"',
        "uv sync --locked",
        "uv run ruff check",
        "uv run ruff format --check",
        "uv run pytest",
    ):
        assert expected in ci, expected
