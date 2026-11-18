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
    env: dict[str, str | None] = {**machine.env, "GIT_CEILING_DIRECTORIES": str(tmp_path)}
    return folder, env


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


def test_a_pull_request_merged_the_day_it_opened_shows_only_as_merged(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    machine.set_search_results(
        prs=[
            pull_request(
                "test-user/app", 5, "fix: same day", local("2026-11-17", "09:00"),
                local("2026-11-17", "17:00"),
            ),
            pull_request(
                "test-user/app", 6, "feat: next day", local("2026-11-17", "10:00"),
                local("2026-11-18", "11:00"),
            ),
        ]
    )  # fmt: skip
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-17", env=env)

    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "2026-11-17\n"
        "  app: merged #5 (same day)\n"
        "       opened #6 (next day)\n"
        "\n"
        "2026-11-18\n"
        "  app: merged #6 (next day)\n"
    )


def on_github(
    number: int, commits: list[str], merge_commit: str | None, repo: str | None = None
) -> dict[str, Any]:
    """A merged pull request as GitHub links it to commits: its own and the one it left on the
    default branch (a squash or merge commit, or None for a rebase merge). With ``repo``,
    GitHub links them only in that repo."""
    return {
        "number": number,
        "state": "MERGED",
        "head": f"branch-{number}",
        "commits": commits,
        "merge_commit": merge_commit,
        "repo": repo,
    }


def test_commits_that_came_from_a_merged_pull_request_are_not_listed_as_pushed(
    aa_in, machine, tmp_path
):
    machine = standup_machine(machine)
    merged = local("2026-11-17", "17:00")
    squash, merge, rebased, direct = "a" * 40, "b" * 40, "d" * 40, "c" * 40
    machine.set_search_results(
        prs=[pull_request("test-user/app", 5, "fix: crash", local("2026-11-17"), merged)],
        commits=[
            commit("test-user/app", squash, "fix: crash (#5)\n\n* fix: crash", merged),
            commit("test-user/app", merge, "Merge pull request #4 from test-user/x", merged),
            commit("test-user/app", rebased, "Tidy the menu", local("2026-11-17", "12:00")),
            commit("test-user/app", direct, "Bump the version", local("2026-11-17", "18:00")),
        ],
    )
    machine.set_pull_requests(
        [
            on_github(5, ["1" * 40], squash),
            on_github(4, ["2" * 40], merge),
            on_github(6, [rebased], None),
        ]
    )
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-17", env=env)

    assert result.exit_code == 0, result.output
    assert result.stdout == (
        '2026-11-17\n  app: merged #5 (crash)\n       pushed "Bump the version"\n'
    )
    assert len(machine.graphql_requests()) == 1


def test_a_failed_pull_request_lookup_for_commits_fails_with_ghs_error(aa_in, machine, tmp_path):
    machine.add_real("git")
    machine.add_gh(graphql_fails=True)
    machine.set_search_results(
        commits=[commit("test-user/app", "c" * 40, "Bump the version", local("2026-11-17"))]
    )
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-17", "--json", env=env)

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "github_request_failed"
    assert "error connecting to api.github.com" in error["message"]


def test_a_day_with_nothing_on_it_has_no_heading(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    machine.set_search_results(
        issues=[
            issue("test-user/app", 1, "First", local("2026-11-15")),
            issue("test-user/app", 2, "Second", local("2026-11-17")),
        ]
    )
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-15", env=env)

    assert result.exit_code == 0, result.output
    assert result.stdout == "2026-11-15\n  app: tickets #1\n\n2026-11-17\n  app: tickets #2\n"


def test_a_span_with_nothing_in_it_prints_one_line_and_exits_0(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-15", env=env)

    assert result.exit_code == 0, result.output
    assert result.stdout == "Nothing on GitHub since 2026-11-15.\n"


def started_at(machine) -> set[str]:
    """The span start every gh search asked for."""
    return {
        value.partition("..")[0]
        for args in searches(machine)
        for flag in ("--merged-at", "--created", "--committer-date")
        for value in option(args, flag)
    }


def test_with_no_since_the_span_starts_at_local_midnight_of_the_day_before(
    aa_in, machine, tmp_path
):
    machine = standup_machine(machine)
    folder, env = outside_any_repo(tmp_path, machine)
    before = date.today()

    result = aa_in(folder, "standup", env=env)

    assert result.exit_code == 0, result.output
    # Read the clock on both sides, so a run across midnight still has one right answer.
    expected = {midnight(day - timedelta(days=1)) for day in (before, date.today())}
    assert len(started_at(machine)) == 1
    assert started_at(machine) <= expected


def last(weekday: int, today: date) -> date:
    """The most recent day before ``today`` that falls on ``weekday`` (Monday is 0)."""
    day = today - timedelta(days=1)
    while day.weekday() != weekday:
        day -= timedelta(days=1)
    return day


@pytest.mark.parametrize(
    ("since", "day_of"),
    [
        ("today", lambda today: today),
        ("yesterday", lambda today: today - timedelta(days=1)),
        ("friday", lambda today: last(4, today)),
        ("Monday", lambda today: last(0, today)),
        ("2026-11-01", lambda today: date(2026, 11, 1)),
    ],
)
def test_since_starts_the_span_at_local_midnight_of_the_day_it_names(
    aa_in, machine, tmp_path, since, day_of
):
    machine = standup_machine(machine)
    folder, env = outside_any_repo(tmp_path, machine)
    before = date.today()

    result = aa_in(folder, "standup", "--since", since, env=env)

    assert result.exit_code == 0, result.output
    expected = {midnight(day_of(today)) for today in (before, date.today())}
    assert len(started_at(machine)) == 1
    assert started_at(machine) <= expected


def test_a_weekday_name_never_means_today(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    folder, env = outside_any_repo(tmp_path, machine)
    today = date.today()
    name = today.strftime("%A").lower()

    result = aa_in(folder, "standup", "--since", name, env=env)

    assert result.exit_code == 0, result.output
    assert started_at(machine) <= {
        midnight(today - timedelta(days=7)),
        midnight(today - timedelta(days=6)),
    }


@pytest.mark.parametrize("since", ["2999-01-01", "last week", "2026-13-01", ""])
def test_a_future_or_unknown_since_is_a_usage_error_that_searches_nothing(
    aa_in, machine, tmp_path, since
):
    machine = standup_machine(machine)
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", since, "--json", env=env)

    assert result.exit_code == 2, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "usage"
    assert "--since" in error["message"]
    assert machine.gh_calls() == []


def test_inside_a_repo_with_a_github_remote_only_that_repo_is_searched(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    folder = git_repo(tmp_path, machine, "https://github.com/test-user/app.git")
    machine.set_search_results(
        issues=[
            issue("test-user/app", 1, "Here", local("2026-11-17")),
            issue("test-user/elsewhere", 2, "Not here", local("2026-11-17")),
        ]
    )

    result = aa_in(folder, "standup", "--since", "2026-11-17", env=machine.env)

    assert result.exit_code == 0, result.output
    assert result.stdout == "2026-11-17\n  app: tickets #1\n"
    assert len(searches(machine)) == 4
    assert all(option(args, "--repo") == ["test-user/app"] for args in searches(machine))


def test_with_all_inside_a_repo_every_repo_is_searched(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    folder = git_repo(tmp_path, machine, "https://github.com/test-user/app.git")
    machine.set_search_results(
        issues=[
            issue("test-user/app", 1, "Here", local("2026-11-17")),
            issue("test-user/elsewhere", 2, "Not here", local("2026-11-17")),
        ]
    )

    result = aa_in(folder, "standup", "--since", "2026-11-17", "--all", env=machine.env)

    assert result.exit_code == 0, result.output
    assert result.stdout == "2026-11-17\n  app:       tickets #1\n  elsewhere: tickets #2\n"
    assert all(option(args, "--repo") == [] for args in searches(machine))
    assert not any(call.args[:2] == ["repo", "view"] for call in machine.gh_calls())


@pytest.mark.parametrize("where", ["inside a repo", "outside any repo"])
def test_named_repos_are_the_only_ones_searched_wherever_aa_runs(aa_in, machine, tmp_path, where):
    machine = standup_machine(machine)
    if where == "inside a repo":
        folder = git_repo(tmp_path, machine, "https://github.com/test-user/app.git")
        env = machine.env
    else:
        folder, env = outside_any_repo(tmp_path, machine)
    machine.set_search_results(
        issues=[
            issue("test-user/app", 1, "Not named", local("2026-11-17")),
            issue("test-user/vibes", 2, "Mine", local("2026-11-17")),
            issue("owner/other", 3, "Theirs", local("2026-11-17")),
        ]
    )

    result = aa_in(
        folder, "standup", "--since", "2026-11-17", "--repo", "vibes", "--repo", "owner/other",
        env=env,
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert result.stdout == "2026-11-17\n  owner/other: tickets #3\n  vibes:       tickets #2\n"
    assert len(searches(machine)) == 4
    for args in searches(machine):
        assert option(args, "--repo") == ["test-user/vibes", "owner/other"]


def test_all_together_with_repo_is_a_usage_error(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--all", "--repo", "vibes", "--json", env=env)

    assert result.exit_code == 2, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "usage"
    assert "'--all' / '--repo'" in error["message"]
    assert error["fix"].endswith("standup --help")
    assert machine.gh_calls() == []


def test_in_a_git_folder_with_no_github_repo_it_fails_like_prune_and_suggests_repo_or_all(
    aa_in, machine, tmp_path
):
    machine = standup_machine(machine)
    folder = git_repo(tmp_path, machine, remote=None)

    result = aa_in(folder, "standup", "--json", env=machine.env)

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "no_github_remote"
    assert "none of the git remotes" in error["message"]
    assert "--repo" in error["fix"]
    assert "--all" in error["fix"]
    assert searches(machine) == []


def test_with_gh_signed_out_it_fails_like_prune(aa_in, machine, tmp_path):
    machine.add_real("git")
    machine.add_gh(signed_in=False)
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--json", env=env)

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "gh_signed_out"
    assert error["fix"] == "gh auth login"
    assert searches(machine) == []


def test_a_failed_search_fails_with_ghs_error(aa_in, machine, tmp_path):
    machine.add_real("git")
    machine.add_gh(search_fails=True)
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--json", env=env)

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "github_request_failed"
    assert "HTTP 503" in error["message"]


def test_a_span_of_several_days_runs_one_search_per_kind(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-01", env=env)

    assert result.exit_code == 0, result.output
    date_flags = ("--merged-at", "--created", "--committer-date")
    kinds = sorted(
        (args[1], flag) for args in searches(machine) for flag in args if flag in date_flags
    )
    assert kinds == [
        ("commits", "--committer-date"),
        ("issues", "--created"),
        ("prs", "--created"),
        ("prs", "--merged-at"),
    ]


def test_json_gives_the_span_start_the_repos_and_every_days_entries(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    machine.set_search_results(
        prs=[
            pull_request(
                "test-user/vibes", 3, "feat: menu", local("2026-11-16"), local("2026-11-17")
            ),
            pull_request("owner/other", 8, "docs: typo", local("2026-11-17", "12:00")),
        ],
        issues=[issue("test-user/vibes", 4, "Sound", local("2026-11-17", "13:00"))],
        commits=[
            commit(
                "test-user/vibes",
                "d75fdc281e74e99d8db0b5822651321885c5dd93",
                "Add players\n\nBody",
                local("2026-11-18", "08:00"),
            )
        ],
    )  # fmt: skip
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(
        folder, "standup", "--since", "2026-11-17", "--repo", "vibes", "--repo", "owner/other",
        "--json", env=env,
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "ok": True,
        "data": {
            "since": midnight(date(2026, 11, 17)),
            "all_repos": False,
            "repos": ["test-user/vibes", "owner/other"],
            "incomplete": [],
            "days": [
                {
                    "date": "2026-11-17",
                    "repos": [
                        {
                            "repo": "owner/other",
                            "merged": [],
                            "opened": [
                                {
                                    "number": 8,
                                    "title": "docs: typo",
                                    "url": "https://github.com/owner/other/pull/8",
                                }
                            ],
                            "issues": [],
                            "pushed": [],
                        },
                        {
                            "repo": "test-user/vibes",
                            "merged": [
                                {
                                    "number": 3,
                                    "title": "feat: menu",
                                    "url": "https://github.com/test-user/vibes/pull/3",
                                }
                            ],
                            "opened": [],
                            "issues": [
                                {
                                    "number": 4,
                                    "title": "Sound",
                                    "url": "https://github.com/test-user/vibes/issues/4",
                                }
                            ],
                            "pushed": [],
                        },
                    ],
                },
                {
                    "date": "2026-11-18",
                    "repos": [
                        {
                            "repo": "test-user/vibes",
                            "merged": [],
                            "opened": [],
                            "issues": [],
                            "pushed": [
                                {
                                    "sha": "d75fdc2",
                                    "subject": "Add players",
                                    "url": "https://github.com/test-user/vibes/commit/d75fdc281e74e99d8db0b5822651321885c5dd93",
                                }
                            ],
                        }
                    ],
                },
            ],
        },
    }


def test_json_with_every_repo_says_so(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-17", "--json", env=env)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"] == {
        "since": midnight(date(2026, 11, 17)),
        "all_repos": True,
        "repos": [],
        "incomplete": [],
        "days": [],
    }


@pytest.mark.parametrize(
    "name",
    ["", "a/b/c", "/vibes", "owner/", "my repo", "..", "owner/.", "-owner/app", "a" * 101,
     "o" * 40 + "/app"],
)  # fmt: skip
def test_a_repo_name_that_cant_be_a_github_repo_is_a_usage_error(aa_in, machine, tmp_path, name):
    machine = standup_machine(machine)
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--repo", name, "--json", env=env)

    assert result.exit_code == 2, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "usage"
    assert "--repo" in error["message"]
    assert machine.gh_calls() == []


def test_a_title_keeps_a_leading_word_that_isnt_a_conventional_commit_type(
    aa_in, machine, tmp_path
):
    machine = standup_machine(machine)
    machine.set_search_results(
        prs=[
            pull_request("test-user/app", 1, "Windows: support long paths", local("2026-11-17")),
            pull_request("test-user/app", 2, "WIP: menu", local("2026-11-17")),
            pull_request("test-user/app", 3, "fix!: drop Python 3.13", local("2026-11-17")),
        ]
    )
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-17", env=env)

    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "2026-11-17\n"
        "  app: opened #1 (Windows: support long paths), #2 (WIP: menu), #3 (drop Python 3.13)\n"
    )


def test_a_pushed_commit_that_mentions_an_issue_number_is_still_listed(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    machine.set_search_results(
        issues=[issue("test-user/app", 12, "Typo", local("2026-11-17", "09:00"))],
        commits=[commit("test-user/app", "e" * 40, "Fix typo (#12)", local("2026-11-17"))],
    )
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-17", env=env)

    assert result.exit_code == 0, result.output
    assert result.stdout == '2026-11-17\n  app: tickets #12\n       pushed "Fix typo (#12)"\n'


def test_commits_are_checked_against_pull_requests_fifty_per_request(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    shas = [f"{index:040x}" for index in range(1, 52)]
    machine.set_search_results(
        commits=[
            commit("test-user/app", sha, f"Change {index}", local("2026-11-17", "10:00"))
            for index, sha in enumerate(shas, start=1)
        ]
    )
    machine.set_pull_requests([on_github(9, [shas[-1]], None)])
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-17", "--json", env=env)

    assert result.exit_code == 0, result.output
    pushed = json.loads(result.stdout)["data"]["days"][0]["repos"][0]["pushed"]
    assert len(pushed) == 50
    assert all(push["subject"] != "Change 51" for push in pushed)
    sizes = [len(request["variables"]) - 2 for request in machine.graphql_requests()]
    assert sizes == [50, 1]


def test_a_search_that_hits_githubs_limit_warns_that_the_standup_may_be_incomplete(
    aa_in, machine, tmp_path
):
    machine = standup_machine(machine)
    machine.set_search_results(
        issues=[
            issue("test-user/app", number, "Many", local("2026-11-17")) for number in range(1, 1001)
        ]
    )
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-17", env=env)

    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("2026-11-17\n  app: tickets #1, #2, #3")
    assert result.stderr == (
        "WARNING aa: GitHub search stops at 1000 issues, so some may be missing;"
        " use a later --since\n"
    )


def test_searches_under_githubs_limit_print_no_warning(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    machine.set_search_results(issues=[issue("test-user/app", 1, "One", local("2026-11-17"))])
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-17", env=env)

    assert result.exit_code == 0, result.output
    assert result.stderr == ""


def test_the_span_ends_now_so_a_commit_dated_in_the_future_is_left_out(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    tomorrow = (datetime.now() + timedelta(days=1)).astimezone()
    machine.set_search_results(
        commits=[commit("test-user/app", "f" * 40, "From a clock set ahead", tomorrow)]
    )
    folder, env = outside_any_repo(tmp_path, machine)
    before = datetime.now().astimezone()

    result = aa_in(folder, "standup", "--since", "today", env=env)

    after = datetime.now().astimezone()
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("Nothing on GitHub since ")
    ends = {
        option(args, flag)[0].partition("..")[2]
        for args in searches(machine)
        for flag in ("--merged-at", "--created", "--committer-date")
        if option(args, flag)
    }
    assert len(ends) == 1
    end = datetime.fromisoformat(ends.pop())
    assert before.replace(microsecond=0) <= end <= after


def test_control_characters_in_titles_and_subjects_never_reach_the_terminal(
    aa_in, machine, tmp_path
):
    machine = standup_machine(machine)
    machine.set_search_results(
        prs=[pull_request("test-user/app", 1, "fix: \x1b[2Jclear\x07", local("2026-11-17"))],
        commits=[
            commit("test-user/app", "c" * 40, "Push \x1b]8;;x\x1b\\link\r", local("2026-11-17"))
        ],
    )
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-17", env=env)

    assert result.exit_code == 0, result.output
    assert result.stdout == (
        '2026-11-17\n  app: opened #1 ([2Jclear)\n       pushed "Push ]8;;x\\link"\n'
    )


def test_json_names_every_kind_whose_search_hit_githubs_limit(aa_in, machine, tmp_path):
    machine = standup_machine(machine)
    machine.set_search_results(
        issues=[
            issue("test-user/app", number, "Many", local("2026-11-17")) for number in range(1, 1001)
        ]
    )
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-17", "--json", env=env)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["incomplete"] == ["issues"]


def test_a_commit_merged_by_pull_request_in_one_repo_still_shows_as_pushed_in_another(
    aa_in, machine, tmp_path
):
    machine = standup_machine(machine)
    shared = "5" * 40  # a fork and its upstream share commits
    machine.set_search_results(
        commits=[
            commit("test-user/fork", shared, "Fix the build", local("2026-11-17")),
            commit("upstream/app", shared, "Fix the build", local("2026-11-17")),
        ]
    )
    machine.set_pull_requests([on_github(3, [shared], None, repo="upstream/app")])
    folder, env = outside_any_repo(tmp_path, machine)

    result = aa_in(folder, "standup", "--since", "2026-11-17", env=env)

    assert result.exit_code == 0, result.output
    assert result.stdout == '2026-11-17\n  fork: pushed "Fix the build"\n'
