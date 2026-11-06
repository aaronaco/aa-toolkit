import _thread
import contextlib
import json
import os
import shutil
import signal
import sys
import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aa_cli.cli import app

PACKAGE_DIR = Path(__file__).resolve().parents[1]

FAKE_GH = r"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

here = Path(__file__).parent
state = json.loads((here / "gh-state.json").read_text())
with (here / "gh-calls.jsonl").open("a") as calls:
    calls.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
if sys.argv[1:3] == ["auth", "status"]:
    if state["signed_in"]:
        print("Logged in to github.com account test-user")
        sys.exit(0)
    print("You are not logged into any GitHub hosts.", file=sys.stderr)
    sys.exit(1)
if sys.argv[1:3] == ["repo", "create"]:
    if not state["signed_in"]:
        print("To get started with GitHub CLI, please run:  gh auth login", file=sys.stderr)
        sys.exit(4)
    if state["repo_create_fails"]:
        print("GraphQL: Name already exists on this account (createRepository)", file=sys.stderr)
        sys.exit(1)
    # Like gh: the repo exists and is the origin remote before the push runs.
    url = f"https://github.com/test-user/{sys.argv[3]}"
    subprocess.run([shutil.which("git"), "remote", "add", "origin", url + ".git"], check=True)
    if state["push_fails"]:
        print("failed to run git: exit status 128", file=sys.stderr)
        sys.exit(1)
    if state["prints_url"]:
        print(url)
    sys.exit(0)
if sys.argv[1:] == ["repo", "view", "--json", "url", "--jq", ".url"]:
    print(f"https://github.com/test-user/{Path.cwd().name}")
    sys.exit(0)
print(f"fake gh: unsupported arguments {sys.argv[1:]}", file=sys.stderr)
sys.exit(2)
"""


@dataclass(frozen=True)
class GhCall:
    """One run of the fake gh: its arguments and the folder it ran in."""

    args: list[str]
    cwd: Path


OLD_GIT = """\
import subprocess
import sys

if "--show-scope" in sys.argv[1:]:
    print("error: unknown option `show-scope'", file=sys.stderr)
    sys.exit(129)
sys.exit(subprocess.run([{real!r}, *sys.argv[1:]]).returncode)
"""

FAILING_TOOL = """\
import sys

print({message!r}, file=sys.stderr)
sys.exit(1)
"""

# Runs until the test presses Ctrl+C, then fails the way a tool stopped by Ctrl+C does.
CTRL_C_TOOL = """\
import sys
import time
from pathlib import Path

(Path({started!r})).touch()
deadline = time.monotonic() + 60
while not Path({released!r}).exists() and time.monotonic() < deadline:
    time.sleep(0.01)
sys.exit(1)
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

    def add_old_git(self) -> None:
        """Put a git older than 2.26 on PATH: the real git, minus ``--show-scope``."""
        real = shutil.which("git")
        if real is None:
            pytest.fail("git must be installed to run this test")
        (self.bin / "old_git.py").write_text(OLD_GIT.format(real=real))
        self._write_shim("git", [sys.executable, str(self.bin / "old_git.py")])

    def add_gh(
        self,
        signed_in: bool = True,
        repo_create_fails: bool = False,
        push_fails: bool = False,
        prints_url: bool = True,
    ) -> None:
        """Put a fake gh on PATH, signed in or signed out, that records every call.

        ``gh repo create <name>`` adds the new repo as the origin remote and
        prints its URL. ``repo_create_fails`` makes it fail before that,
        ``push_fails`` makes it fail after adding the remote, and
        ``prints_url=False`` makes it print nothing (``gh repo view`` still
        gives the URL).
        """
        state = {
            "signed_in": signed_in,
            "repo_create_fails": repo_create_fails,
            "push_fails": push_fails,
            "prints_url": prints_url,
        }
        (self.bin / "fake_gh.py").write_text(FAKE_GH)
        (self.bin / "gh-state.json").write_text(json.dumps(state))
        self._write_shim("gh", [sys.executable, str(self.bin / "fake_gh.py")])

    def gh_calls(self) -> list[GhCall]:
        """Every call the fake gh got, in order."""
        log = self.bin / "gh-calls.jsonl"
        if not log.exists():
            return []
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return [GhCall(call["args"], Path(call["cwd"])) for call in calls]

    def add_failing(self, name: str, message: str) -> None:
        """Put a tool on PATH that prints ``message`` to stderr and fails on every call."""
        script = self.bin / f"failing_{name}.py"
        script.write_text(FAILING_TOOL.format(message=message))
        self._write_shim(name, [sys.executable, str(script)])

    def add_ctrl_c(self, name: str) -> None:
        """Put a tool on PATH during whose first run the user presses Ctrl+C.

        Ctrl+C reaches aa as SIGINT, which Python turns into KeyboardInterrupt
        in the main thread. A watcher thread raises that same signal in this
        process once the tool is running, then lets the tool exit.
        """
        started = self.bin / f"{name}-started"
        released = self.bin / f"{name}-released"
        script = self.bin / f"ctrl_c_{name}.py"
        script.write_text(CTRL_C_TOOL.format(started=str(started), released=str(released)))
        self._write_shim(name, [sys.executable, str(script)])

        def press_ctrl_c() -> None:
            deadline = time.monotonic() + 60
            while not started.exists():
                if time.monotonic() > deadline:
                    return
                time.sleep(0.01)
            _thread.interrupt_main(signal.SIGINT)
            released.touch()

        threading.Thread(target=press_ctrl_c, daemon=True).start()

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


@pytest.fixture(scope="session")
def new_machine(tmp_path_factory):
    """Make a stand-in machine with nothing on PATH yet; usable from fixtures of any scope."""
    return lambda: Machine(tmp_path_factory.mktemp("machine"))


@pytest.fixture
def machine(new_machine) -> Machine:
    """A stand-in machine with nothing on PATH yet. Pass ``machine.env`` to ``aa``."""
    return new_machine()


@pytest.fixture(scope="session")
def aa_in():
    """Run the aa command in process from ``cwd``; usable from fixtures of any scope.

    AA_JSON is cleared unless ``env`` sets it, so a developer's own setting never leaks in.
    """

    def run(cwd: Path, *args: str, env: dict[str, str | None] | None = None):
        with contextlib.chdir(cwd):
            return CliRunner().invoke(app, list(args), env={"AA_JSON": None, **(env or {})})

    return run


@pytest.fixture(autouse=True)
def _no_ambient_json(monkeypatch):
    """Keep a developer's own AA_JSON from leaking into tests that run aa as a subprocess."""
    monkeypatch.delenv("AA_JSON", raising=False)


@pytest.fixture
def aa(aa_in, tmp_path, monkeypatch):
    """Run the aa command in process from the current folder, at first an empty temporary one."""
    monkeypatch.chdir(tmp_path)
    return lambda *args, env=None: aa_in(Path.cwd(), *args, env=env)


@pytest.fixture
def package_dir() -> Path:
    """The aa-cli package folder in this checkout."""
    return PACKAGE_DIR


@pytest.fixture
def package_version() -> str:
    """The version declared in the aa-cli pyproject."""
    return tomllib.loads((PACKAGE_DIR / "pyproject.toml").read_text())["project"]["version"]
