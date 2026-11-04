import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aa_cli.cli import app

PACKAGE_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_ambient_json(monkeypatch):
    """Keep a developer's own AA_JSON from leaking into tests."""
    monkeypatch.delenv("AA_JSON", raising=False)


@pytest.fixture
def aa():
    """Run the aa command in process and return the result."""

    def run(*args: str, env: dict[str, str] | None = None):
        return CliRunner().invoke(app, list(args), env=env)

    return run


@pytest.fixture
def package_dir() -> Path:
    """The aa-cli package folder in this checkout."""
    return PACKAGE_DIR


@pytest.fixture
def package_version() -> str:
    """The version declared in the aa-cli pyproject."""
    return tomllib.loads((PACKAGE_DIR / "pyproject.toml").read_text())["project"]["version"]
