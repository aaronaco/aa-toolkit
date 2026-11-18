"""``aa standup``: what the user did on GitHub, by day and repo, with real git and a fake gh."""

import json
import os
import subprocess
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest

SEARCH_KINDS = ("prs", "issues", "commits")


def local(day: str, clock: str = "10:00") -> datetime:
    """A moment on ``day`` in this machine's own time zone."""
    return datetime.fromisoformat(f"{day}T{clock}").astimezone()


def utc(moment: datetime) -> str:
    """A moment written the way GitHub search gives pull request and issue times."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def midnight(day: date) -> str:
    """The start of ``day`` in this machine's time zone, as aa writes it in a search."""
    return datetime.combine(day, time.min).astimezone().isoformat()


def pull_request(
    repo: str, number: int, title: str, opened: datetime, merged: datetime | None = None
) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/{repo}/pull/{number}",
        "repository": {"name": repo.split("/")[1], "nameWithOwner": repo},
        "createdAt": utc(opened),
        "closedAt": utc(merged) if merged else None,
        "state": "merged" if merged else "open",
    }


def issue(repo: str, number: int, title: str, opened: datetime) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/{repo}/issues/{number}",
        "repository": {"name": repo.split("/")[1], "nameWithOwner": repo},
        "createdAt": utc(opened),
        "isPullRequest": False,
    }


def commit(repo: str, sha: str, message: str, committed: datetime) -> dict[str, Any]:
    owner, name = repo.split("/")
    return {
        "sha": sha,
        "url": f"https://github.com/{repo}/commit/{sha}",
        "repository": {"fullName": repo, "name": name, "owner": {"login": owner}},
        "commit": {
            "message": message,
            "committer": {"date": committed.isoformat()},
            "author": {"date": committed.isoformat()},
        },
    }


def standup_machine(machine):
    machine.add_real("git")
    machine.add_gh()
    machine.set_identity()
    return machine


def outside_any_repo(tmp_path: Path, machine) -> tuple[Path, dict[str, str | None]]:
    """A folder no git repo holds, and the env that keeps git from looking above it."""
    folder = tmp_path / "outside"
    folder.mkdir()
    return folder, {**machine.env, "GIT_CEILING_DIRECTORIES": str(tmp_path)}


def git_repo(tmp_path: Path, machine, remote: str | None) -> Path:
    """A real git repo, with ``remote`` as its origin when given."""
    folder = tmp_path / "repo"
    folder.mkdir()
    env = {**os.environ, **{k: v for k, v in machine.env.items() if k != "PATH" and v}}
    subprocess.run(["git", "init", "--quiet"], cwd=folder, env=env, check=True)
    if remote:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=folder, env=env, check=True)
    return folder


def searches(machine) -> list[list[str]]:
    """The arguments of every gh search aa ran."""
    return [call.args for call in machine.gh_calls() if call.args[:1] == ["search"]]


def option(args: list[str], flag: str) -> list[str]:
    """Every value given to ``flag`` in a gh command line."""
    return [value for name, value in zip(args, args[1:], strict=False) if name == flag]


def test_outside_any_repo_it_prints_one_heading_per_day_and_one_line_per_repo(
    aa_in, machine, tmp_path
):
    machine = standup_machine(machine)
    machine.set_search_results(
        prs=[
            pull_request(
                "test-user/aa-toolkit",
                99,
                "feat(cli): aa init stops writing a CI workflow",
                local("2026-11-14"),
                local("2026-11-17", "15:00"),
            ),
            pull_request(
                "test-user/aa-toolkit",
                94,
                "feat(cli)!: add aa prune to remove Finished branches",
                local("2026-11-15"),
                local("2026-11-17", "09:00"),
            ),
            pull_request(
                "test-user/aa-toolkit",
                102,
                "feat(cli): aa add ci sets up four CI parts",
                local("2026-11-17", "21:00"),
            ),
            pull_request(
                "someone/other", 7, "fix: handle empty input", local("2026-11-18", "08:00")
            ),
        ],
        issues=[
            issue("test-user/aa-toolkit", 97, "Workflow audit part", local("2026-11-17", "12:00")),
            issue("test-user/aa-toolkit", 96, "Tests part", local("2026-11-17", "11:00")),
        ],
        commits=[
            commit(
                "test-user/vibes",
                "336175d0a1b2c3d4e5f60718293a4b5c6d7e8f90",
                "Add debug-tool glossary terms and north ADR\n\nLonger body.",
                local("2026-11-17", "23:30"),
            ),
            commit(
                "test-user/vibes",
                "4a5b6c7d8e9f0a1b2c3d4e5f60718293a4b5c6d7",
                "feat: add a title screen",
                local("2026-11-18", "07:00"),
            ),
        ],
    )
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-16", env=env)

    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "2026-11-17\n"
        "  aa-toolkit: merged #94 (add aa prune to remove Finished branches),"
        " #99 (aa init stops writing a CI workflow)\n"
        "              opened #102 (aa add ci sets up four CI parts)\n"
        "              tickets #96, #97\n"
        '  vibes:      pushed "Add debug-tool glossary terms and north ADR"\n'
        "\n"
        "2026-11-18\n"
        "  someone/other: opened #7 (handle empty input)\n"
        '  vibes:         pushed "feat: add a title screen"\n'
    )
