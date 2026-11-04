import json
import os
import shutil
import sys
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aa_cli.cli import app

PACKAGE_DIR = Path(__file__).resolve().parents[1]

FAKE_GH = """\
import json
import sys
from pathlib import Path

state = json.loads((Path(__file__).parent / "gh-state.json").read_text())
if sys.argv[1:3] == ["auth", "status"]:
    if state["signed_in"]:
        print("Logged in to github.com account test-user")
        sys.exit(0)
    print("You are not logged into any GitHub hosts.", file=sys.stderr)
    sys.exit(1)
print(f"fake gh: unsupported arguments {sys.argv[1:]}", file=sys.stderr)
sys.exit(2)
"""


class Machine:
    """A stand-in machine: a PATH that holds only the tools a test puts on it.

    Real uv and git are reached through small stand-ins that forward to them.
    gh is always faked, so tests never touch GitHub. Git reads only a throwaway
    global config, so tests never depend on or change the developer's identity.
    """

    def __init__(self, root: Path) -> None:
        self.bin = root / "bin"
        self.bin.mkdir()
        self._gitconfig = root / "gitconfig"
        self._gitconfig.write_text("")
        self._identity: dict[str, str] = {}

    @property
    def env(self) -> dict[str, str | None]:
        env: dict[str, str | None] = {
            "PATH": str(self.bin),
            "GIT_CONFIG_GLOBAL": str(self._gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": str(len(self._identity)),
        }
        for index, (key, value) in enumerate(self._identity.items()):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        return env

    def add_real(self, name: str) -> None:
        """Put a stand-in on PATH that runs the real tool."""
        real = shutil.which(name)
        if real is None:
            pytest.fail(f"{name} must be installed to run this test")
        self._write_shim(name, [real])

    def add_gh(self, signed_in: bool = True) -> None:
        """Put a fake gh on PATH, signed in or signed out."""
        (self.bin / "fake_gh.py").write_text(FAKE_GH)
        (self.bin / "gh-state.json").write_text(json.dumps({"signed_in": signed_in}))
        self._write_shim("gh", [sys.executable, str(self.bin / "fake_gh.py")])

    def set_identity(
        self, name: str | None = "Test User", email: str | None = "test@example.com"
    ) -> None:
        """Set the git identity; pass None to leave the name or email unset."""
        pairs = (("user.name", name), ("user.email", email))
        self._identity = {key: value for key, value in pairs if value is not None}

    def full(self) -> Machine:
        """uv, git, a git identity and a signed-in gh."""
        self.add_real("uv")
        self.add_real("git")
        self.add_gh(signed_in=True)
        self.set_identity()
        return self

    def _write_shim(self, name: str, command: list[str]) -> None:
        if os.name == "nt":
            quoted = " ".join(f'"{part}"' for part in command)
            (self.bin / f"{name}.bat").write_text(f"@echo off\r\n{quoted} %*\r\n")
        else:
            quoted = " ".join(f"'{part}'" for part in command)
            shim = self.bin / name
            shim.write_text(f'#!/bin/sh\nexec {quoted} "$@"\n')
            shim.chmod(0o755)


@pytest.fixture
def machine(tmp_path_factory) -> Machine:
    """A stand-in machine with nothing on PATH yet. Pass ``machine.env`` to ``aa``."""
    return Machine(tmp_path_factory.mktemp("machine"))


@pytest.fixture(autouse=True)
def _no_ambient_json(monkeypatch):
    """Keep a developer's own AA_JSON from leaking into tests."""
    monkeypatch.delenv("AA_JSON", raising=False)


@pytest.fixture
def aa(tmp_path, monkeypatch):
    """Run the aa command in process, from an empty temporary folder, and return the result."""
    monkeypatch.chdir(tmp_path)

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
