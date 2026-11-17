import _thread
import contextlib
import io
import json
import os
import shutil
import signal
import sys
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aa_cli.cli import app

PACKAGE_DIR = Path(__file__).resolve().parents[1]

FAKE_GH = r"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

here = Path(__file__).parent
state = json.loads((here / "gh-state.json").read_text())
git = shutil.which("git")
log = subprocess.run([git, "log", "-1", "--format=%s"], capture_output=True, text=True)
with (here / "gh-calls.jsonl").open("a") as calls:
    call = {"args": sys.argv[1:], "cwd": os.getcwd(), "last_commit": log.stdout.strip() or None}
    calls.write(json.dumps(call) + "\n")
if sys.argv[1:3] == ["repo", "create"]:
    if not state["signed_in"]:
        print("To get started with GitHub CLI, please run:  gh auth login", file=sys.stderr)
        sys.exit(4)
    if state["repo_create_fails"]:
        print("GraphQL: Name already exists on this account (createRepository)", file=sys.stderr)
        sys.exit(1)
    # Like gh: the repo exists and is the origin remote before the push runs.
    url = f"https://github.com/test-user/{sys.argv[3]}"
    subprocess.run([git, "remote", "add", "origin", url + ".git"], check=True)
    if state["push_fails"]:
        print("failed to run git: exit status 128", file=sys.stderr)
        sys.exit(1)
    if state["prints_url"]:
        print(url)
    sys.exit(0)
if sys.argv[1:] == ["repo", "view", "--json", "url", "--jq", ".url"]:
    print(f"https://github.com/test-user/{Path.cwd().name}")
    sys.exit(0)
if sys.argv[1:] == ["auth", "status", "--hostname", "github.com"]:
    if not state["signed_in"]:
        print("You are not logged into any GitHub hosts. To log in, run: gh auth login",
              file=sys.stderr)
        sys.exit(1)
    print("github.com\n  Logged in to github.com account test-user")
    sys.exit(0)
if sys.argv[1:] == ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]:
    # Like gh: the repo comes from a git remote that points at github.com.
    remotes = subprocess.run([git, "remote", "-v"], capture_output=True, text=True).stdout
    found = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?\s", remotes)
    if not found:
        print("none of the git remotes configured for this repository point to a known GitHub"
              " host. To tell gh about a new GitHub host, please use `gh auth login`",
              file=sys.stderr)
        sys.exit(1)
    print(f"{found.group(1)}/{found.group(2)}")
    sys.exit(0)
if sys.argv[1:] == ["api", "graphql", "--input", "-"]:
    # Answers like GitHub from the canned pull requests, within each connection's first/last
    # limit. A commit GitHub has is linked to the merged pull requests that hold it or whose
    # squash commit it is, and, only while it isn't on the default branch, to the open ones
    # that hold it.
    body = json.load(sys.stdin)
    with (here / "gh-graphql.jsonl").open("a") as requests:
        requests.write(json.dumps(body) + "\n")
    if state["graphql_fails"]:
        print("error connecting to api.github.com", file=sys.stderr)
        sys.exit(1)
    for args in state["during_graphql"]:  # another program changing the repo meanwhile
        subprocess.run([git, *args], check=True, capture_output=True)
    query, variables = body["query"], body["variables"]
    prs = state["pull_requests"]
    on_github = {oid for pr in prs for oid in [*pr["commits"], pr["merge_commit"]] if oid}

    def on_default_branch(oid):
        is_ancestor = [git, "merge-base", "--is-ancestor", oid, "main"]
        return subprocess.run(is_ancestor, capture_output=True).returncode == 0

    def node(pr):
        commits = [{"commit": {"oid": oid}} for oid in pr["commits"][-100:]]
        return {
            "number": pr["number"],
            "state": pr["state"],
            "headRefName": pr["head"],
            "commits": {"totalCount": len(pr["commits"]), "nodes": commits},
        }

    repository = {}
    if "defaultBranchRef { name }" in query:
        repository["defaultBranchRef"] = {"name": "main"}
    pattern = (
        r"(\w+): object\(oid: \$(\w+)\) \{ \.\.\. on Commit \{"
        r" associatedPullRequests\(first: (\d+)\)"
    )
    for alias, var, first in re.findall(pattern, query):
        oid = variables[var]
        linked = [
            pr for pr in prs
            if (pr["state"] == "MERGED" and (oid in pr["commits"] or oid == pr["merge_commit"]))
            or (pr["state"] == "OPEN" and oid in pr["commits"] and not on_default_branch(oid))
        ]
        repository[alias] = (
            {"associatedPullRequests": {"nodes": [node(pr) for pr in linked[: int(first)]]}}
            if oid in on_github else None
        )
    pattern = r"(\w+): pullRequests\(headRefName: \$(\w+), states: \[([A-Z, ]+)\], last: (\d+)\)"
    for alias, var, states, last in re.findall(pattern, query):
        wanted = {s.strip() for s in states.split(",")}
        named = [pr for pr in prs if pr["head"] == variables[var] and pr["state"] in wanted]
        repository[alias] = {"nodes": [node(pr) for pr in named[-int(last):]]}
    for alias, first in re.findall(r"(\w+): pullRequests\(states: \[OPEN\], first: (\d+)\)", query):
        open_prs = [pr for pr in prs if pr["state"] == "OPEN"]
        repository[alias] = {
            "totalCount": len(open_prs),
            "nodes": [node(pr) for pr in open_prs[: int(first)]],
        }
    print(json.dumps({"data": {"repository": repository}}))
    sys.exit(0)
print(f"fake gh: unsupported arguments {sys.argv[1:]}", file=sys.stderr)
sys.exit(2)
"""


FAKE_UV = r"""
import json
import os
import re
import sys
import tomllib
from pathlib import Path

here = Path(__file__).parent
with (here / "uv-calls.jsonl").open("a", encoding="utf-8") as calls:
    calls.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd()}) + "\n")

if sys.argv[1:2] == ["add"]:
    reqs = [arg for arg in sys.argv[2:] if not arg.startswith("-")]
    pyproject = Path.cwd() / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    existing = tomllib.loads(text).get("project", {}).get("dependencies", [])
    updated = [*existing, *reqs]
    formatted = "dependencies = [\n" + "".join(f'    "{item}",\n' for item in updated) + "]"
    new_text = re.sub(
        r"^dependencies = \[.*?\]",
        lambda _m: formatted,
        text,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )
    pyproject.write_text(new_text, encoding="utf-8")
    (Path.cwd() / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    sys.exit(0)

print(f"fake uv: unsupported arguments {sys.argv[1:]}", file=sys.stderr)
sys.exit(2)
"""


@dataclass(frozen=True)
class GhCall:
    """One run of the fake gh: its arguments, its folder and the commit there at that moment."""

    args: list[str]
    cwd: Path
    last_commit: str | None


@dataclass(frozen=True)
class UvCall:
    """One run of the fake uv: its arguments and its folder."""

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
        graphql_fails: bool = False,
    ) -> None:
        """Put a fake gh on PATH, signed in or signed out, that records every call.

        ``gh repo create <name>`` adds the new repo as the origin remote and
        prints its URL. Signed out or with ``repo_create_fails`` it fails before
        that, ``push_fails`` makes it fail after adding the remote, and
        ``prints_url=False`` makes it print nothing (``gh repo view`` still
        gives the URL). ``graphql_fails`` makes every GraphQL request fail as if offline.
        """
        state = {
            "signed_in": signed_in,
            "repo_create_fails": repo_create_fails,
            "push_fails": push_fails,
            "prints_url": prints_url,
            "graphql_fails": graphql_fails,
            "pull_requests": [],
            "during_graphql": [],
        }
        (self.bin / "fake_gh.py").write_text(FAKE_GH)
        (self.bin / "gh-state.json").write_text(json.dumps(state))
        self._write_shim("gh", [sys.executable, str(self.bin / "fake_gh.py")])

    def set_pull_requests(self, pull_requests: list[dict[str, Any]]) -> None:
        """Give the fake gh the pull requests GitHub knows about.

        Each has ``number``, ``state`` (OPEN, MERGED or CLOSED), ``head`` (its branch name),
        ``commits`` (its own commits, oldest first) and ``merge_commit`` (the squash commit on
        the default branch, or None).
        """
        path = self.bin / "gh-state.json"
        state = json.loads(path.read_text())
        state["pull_requests"] = pull_requests
        path.write_text(json.dumps(state))

    def change_repo_during_graphql(self, *commands: list[str]) -> None:
        """Run these git commands, as another program would, while gh asks GitHub."""
        path = self.bin / "gh-state.json"
        state = json.loads(path.read_text())
        state["during_graphql"] = [list(command) for command in commands]
        path.write_text(json.dumps(state))

    def graphql_requests(self) -> list[dict[str, Any]]:
        """The body of every GraphQL request the fake gh got, in order."""
        log = self.bin / "gh-graphql.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def gh_calls(self) -> list[GhCall]:
        """Every call the fake gh got, in order."""
        log = self.bin / "gh-calls.jsonl"
        if not log.exists():
            return []
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return [GhCall(call["args"], Path(call["cwd"]), call["last_commit"]) for call in calls]

    def add_fake_uv(self) -> None:
        """Put a fake uv on PATH that records every call and edits pyproject.toml on ``uv add``."""
        (self.bin / "fake_uv.py").write_text(FAKE_UV, encoding="utf-8")
        self._write_shim("uv", [sys.executable, str(self.bin / "fake_uv.py")])

    def uv_calls(self) -> list[UvCall]:
        """Every call the fake uv got, in order."""
        log = self.bin / "uv-calls.jsonl"
        if not log.exists():
            return []
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        return [UvCall(call["args"], Path(call["cwd"])) for call in calls]

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

    def ignore_globally(self, *patterns: str) -> None:
        """Add ignore rules of the developer's own, through git's ``core.excludesFile``."""
        ignore = self._gitconfig.with_name("global-ignore")
        ignore.write_text("\n".join(patterns) + "\n")
        self._gitconfig.write_text(f'[core]\n\texcludesFile = "{ignore.as_posix()}"\n')

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
def machine(new_machine: Callable[[], Machine]) -> Machine:
    """A stand-in machine with nothing on PATH yet. Pass ``machine.env`` to ``aa``."""
    return new_machine()


class _TerminalStdin(io.TextIOWrapper):
    name = "<stdin>"
    mode = "r"

    def isatty(self) -> bool:
        return True


class _Runner(CliRunner):
    """A ``CliRunner`` whose ``sys.stdin`` is a terminal until ``input`` is passed.

    ``typed`` is the text typed at a terminal prompt; the terminal itself stays empty.
    """

    def __init__(self, typed: str | None = None) -> None:
        super().__init__()
        self.typed = typed

    @contextlib.contextmanager
    def isolation(self, input=None, env=None, color=False):
        # Click's prompts read from the stream given here, not from sys.stdin.
        prompt_input = self.typed if input is None else input
        with super().isolation(input=prompt_input, env=env, color=color) as streams:
            if input is None:
                sys.stdin = _TerminalStdin(io.BytesIO(), encoding=self.charset)
            yield streams


@pytest.fixture(scope="session")
def aa_in():
    """Run the aa command in process from ``cwd``; usable from fixtures of any scope.

    ``stdin`` is piped text; without it standard input is a terminal, where ``typed``
    is what a person types at a prompt.

    AA_JSON is cleared unless ``env`` sets it, so a developer's own setting never leaks in.
    """

    def run(
        cwd: Path,
        *args: str,
        stdin: str | bytes | None = None,
        env: dict[str, str | None] | None = None,
        typed: str | None = None,
    ):
        with contextlib.chdir(cwd):
            return _Runner(typed).invoke(
                app,
                list(args),
                input=stdin,
                env={"AA_JSON": None, **(env or {})},
            )

    return run


@pytest.fixture(scope="session", autouse=True)
def _no_ambient_git_repo():
    """Keep a git hook that runs the suite from sending the tests' git commands to its repo."""
    with pytest.MonkeyPatch.context() as patch:
        for variable in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
            patch.delenv(variable, raising=False)
        yield


@pytest.fixture(autouse=True)
def _no_ambient_json(monkeypatch):
    """Keep a developer's own AA_JSON from leaking into tests that run aa as a subprocess."""
    monkeypatch.delenv("AA_JSON", raising=False)


@pytest.fixture(autouse=True)
def local_app_data(tmp_path_factory: pytest.TempPathFactory, monkeypatch) -> Path:
    """Point LOCALAPPDATA at a temporary folder, so no test writes a Crash report into the real one.

    It sits outside ``tmp_path``, so tests that check their folder stays empty still can.
    """
    folder = tmp_path_factory.mktemp("localappdata")
    monkeypatch.setenv("LOCALAPPDATA", str(folder))
    return folder


@pytest.fixture
def crash_folder(local_app_data: Path) -> Path:
    """Where aa saves Crash reports during a test."""
    return local_app_data / "aa" / "crash"


@pytest.fixture
def aa(aa_in, tmp_path, monkeypatch):
    """Run the aa command in process from the current folder, at first an empty temporary one."""
    monkeypatch.chdir(tmp_path)
    return lambda *args, stdin=None, env=None, typed=None: aa_in(
        Path.cwd(), *args, stdin=stdin, env=env, typed=typed
    )


@pytest.fixture
def package_dir() -> Path:
    """The aa-toolkit-cli package folder in this checkout."""
    return PACKAGE_DIR


@pytest.fixture
def package_version() -> str:
    """The version declared in the aa-toolkit-cli pyproject."""
    pyproject = tomllib.loads((PACKAGE_DIR / "pyproject.toml").read_text())
    version: str = pyproject["project"]["version"]
    return version
