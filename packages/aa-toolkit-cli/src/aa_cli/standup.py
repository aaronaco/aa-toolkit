"""``aa standup``: what the user did on GitHub, one heading per day and one line per repo."""

__lazy_modules__ = {"aa_cli.github", "aa_cli.process", "json"}

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from aa_cli.github import GitHubError, check_signed_in, folder_repo
from aa_cli.process import error_line, run

# GitHub search gives at most 1,000 results per search.
SEARCH_LIMIT = 1000

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# A leading Conventional Commit type, with an optional scope and "!": "feat(cli)!: ".
_PREFIX = re.compile(r"^[A-Za-z]+(?:\([^)]*\))?!?: +")
# A squash merge's subject ends in "(#N)"; a merge commit's starts with "Merge pull request #N".
_FROM_PULL_REQUEST = re.compile(r"\(#\d+\)$|^Merge pull request #\d+")


class SinceError(ValueError):
    """``--since`` names no day aa understands, or a day after today."""


def parse_since(text: str, today: date) -> date:
    """The day ``--since`` names: yesterday, today, a weekday name or a date, never in the future.

    A weekday name means the most recent such day before today.
    """
    word = text.strip().casefold()
    if word == "yesterday":
        return today - timedelta(days=1)
    if word == "today":
        return today
    if word in WEEKDAYS:
        back = (today.weekday() - WEEKDAYS.index(word)) % 7 or 7
        return today - timedelta(days=back)
    try:
        day = date.fromisoformat(text.strip())
    except ValueError:
        raise SinceError(
            f"{text!r} isn't a day aa understands; use yesterday, today, a weekday name such as"
            " friday, or a date such as 2026-11-01"
        ) from None
    if day > today:
        raise SinceError(f"{day.isoformat()} is in the future")
    return day


@dataclass(frozen=True)
class Item:
    """One pull request or issue."""

    number: int
    title: str
    url: str

    def as_json(self) -> dict[str, Any]:
        return {"number": self.number, "title": self.title, "url": self.url}


@dataclass(frozen=True)
class Push:
    """One commit that landed on a default branch without a pull request."""

    sha: str
    subject: str
    url: str
    committed: datetime

    def as_json(self) -> dict[str, Any]:
        return {"sha": self.sha[:7], "subject": self.subject, "url": self.url}


@dataclass
class RepoDay:
    """What the user did in one repo on one day."""

    repo: str  # owner/name
    merged: list[Item] = field(default_factory=list)
    opened: list[Item] = field(default_factory=list)
    issues: list[Item] = field(default_factory=list)
    pushed: list[Push] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "merged": [item.as_json() for item in self.merged],
            "opened": [item.as_json() for item in self.opened],
            "issues": [item.as_json() for item in self.issues],
            "pushed": [push.as_json() for push in self.pushed],
        }


@dataclass(frozen=True)
class Standup:
    """What the user did on GitHub from ``since`` up to now, by day and repo."""

    since: datetime
    login: str
    repos: list[str] | None  # owner/name each, or None for every repo
    days: list[tuple[date, list[RepoDay]]]

    def as_json(self) -> dict[str, Any]:
        return {
            "since": self.since.isoformat(),
            "all_repos": self.repos is None,
            "repos": self.repos or [],
            "days": [
                {"date": day.isoformat(), "repos": [entry.as_json() for entry in entries]}
                for day, entries in self.days
            ],
        }


def standup(cwd: Path, since: date, repos: Sequence[str], *, all_repos: bool) -> Standup:
    """Ask GitHub what the user did from the start of ``since``, in local time, up to now.

    ``repos`` names the repos to cover; without them and without ``all_repos``, a folder in a
    git repo covers that repo's GitHub repo and any other folder covers every repo.
    """
    check_signed_in(cwd)
    login = _login(cwd)
    scope = _scope(cwd, login, repos, all_repos=all_repos)
    start = datetime.combine(since, time.min).astimezone()
    # A range rather than ">=": a gh run through a .cmd shim would read ">" as a redirect.
    qualifier = f"{start.isoformat()}..*"
    repo_flags = [arg for repo in scope or [] for arg in ("--repo", repo)]
    pr_fields = "number,title,url,repository,createdAt,closedAt,state"
    merged = _search(cwd, "prs", "--merged-at", qualifier, pr_fields, repo_flags)
    opened = _search(cwd, "prs", "--created", qualifier, pr_fields, repo_flags)
    issues = _search(
        cwd, "issues", "--created", qualifier, "number,title,url,repository,createdAt,isPullRequest",
        repo_flags,
    )
    commits = _search(
        cwd, "commits", "--committer-date", qualifier, "sha,url,repository,commit", repo_flags
    )
    return Standup(start, login, scope, _by_day(merged, opened, issues, commits))


def _login(cwd: Path) -> str:
    result = run("gh", "api", "user", "--jq", ".login", cwd=cwd)
    if result.returncode != 0 or not result.stdout.strip():
        raise GitHubError(
            "github_request_failed", f"Asking GitHub who is signed in failed: {error_line(result)}"
        )
    return result.stdout.strip()


def _scope(cwd: Path, login: str, repos: Sequence[str], *, all_repos: bool) -> list[str] | None:
    """The repos to search, as owner/name, or None for every repo."""
    if repos:
        return list(dict.fromkeys(repo if "/" in repo else f"{login}/{repo}" for repo in repos))
    if all_repos or not _inside_git_repo(cwd):
        return None
    owner, name = folder_repo(
        cwd, fix="aa standup --repo NAME for one repo, or aa standup --all for every repo"
    )
    return [f"{owner}/{name}"]


def _inside_git_repo(cwd: Path) -> bool:
    inside = run("git", "rev-parse", "--is-inside-work-tree", cwd=cwd)
    return inside.returncode == 0 and inside.stdout.strip() == "true"


def _search(
    cwd: Path, kind: str, date_flag: str, qualifier: str, fields: str, repo_flags: list[str]
) -> list[dict[str, Any]]:
    """One gh search for the whole span: the user's own work of ``kind`` since the qualifier."""
    result = run(
        "gh", "search", kind, "--author", "@me", date_flag, qualifier,
        "--limit", str(SEARCH_LIMIT), "--json", fields, *repo_flags,
        cwd=cwd,
    )  # fmt: skip
    if result.returncode != 0:
        raise GitHubError(
            "github_request_failed", f"Searching GitHub for {kind} failed: {error_line(result)}"
        )
    found: list[dict[str, Any]] = json.loads(result.stdout or "[]")
    return found


def _local_day(timestamp: str) -> date:
    return datetime.fromisoformat(timestamp).astimezone().date()


def _repo(item: dict[str, Any]) -> str:
    repository = item["repository"]
    return repository.get("nameWithOwner") or repository["fullName"]


def _by_day(
    merged: list[dict[str, Any]],
    opened: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    commits: list[dict[str, Any]],
) -> list[tuple[date, list[RepoDay]]]:
    """Every result in its local day and repo; days and repos with nothing are left out."""
    days: dict[date, dict[str, RepoDay]] = {}

    def entry(day: date, repo: str) -> RepoDay:
        return days.setdefault(day, {}).setdefault(repo, RepoDay(repo))

    def item(found: dict[str, Any]) -> Item:
        return Item(found["number"], found["title"], found["url"])

    merged_on = {found["url"]: _local_day(found["closedAt"]) for found in merged}
    for found in merged:
        entry(merged_on[found["url"]], _repo(found)).merged.append(item(found))
    for found in opened:
        day = _local_day(found["createdAt"])
        if merged_on.get(found["url"]) != day:
            entry(day, _repo(found)).opened.append(item(found))
    for found in issues:
        if not found.get("isPullRequest"):
            entry(_local_day(found["createdAt"]), _repo(found)).issues.append(item(found))
    for found in commits:
        subject = found["commit"]["message"].split("\n", 1)[0].strip()
        if _FROM_PULL_REQUEST.search(subject):
            continue
        committed = datetime.fromisoformat(found["commit"]["committer"]["date"]).astimezone()
        push = Push(found["sha"], subject, found["url"], committed)
        entry(committed.date(), _repo(found)).pushed.append(push)
    for repos in days.values():
        for repo_day in repos.values():
            for items in (repo_day.merged, repo_day.opened, repo_day.issues):
                items.sort(key=lambda found: found.number)
            repo_day.pushed.sort(key=lambda push: push.committed)
    return [(day, list(days[day].values())) for day in sorted(days)]


def _shown_name(repo: str, login: str) -> str:
    """The repo's name when the signed-in account owns it, otherwise owner/name."""
    owner, _, name = repo.partition("/")
    return name if owner.casefold() == login.casefold() else repo


def _title(text: str) -> str:
    return _PREFIX.sub("", text, count=1)


def format_standup(result: Standup) -> str:
    """One heading per day, then one line per repo with what was merged, opened and pushed."""
    if not result.days:
        return f"Nothing on GitHub since {result.since.date().isoformat()}."
    blocks = []
    for day, entries in result.days:
        named = sorted(
            ((_shown_name(entry.repo, result.login), entry) for entry in entries),
            key=lambda pair: pair[0].casefold(),
        )
        width = max(len(name) for name, _ in named) + 1
        lines = [day.isoformat()]
        for name, entry in named:
            parts = _parts(entry)
            lines.append(f"  {name + ':':<{width}} {parts[0]}")
            lines.extend(f"  {'':<{width}} {part}" for part in parts[1:])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _parts(entry: RepoDay) -> list[str]:
    parts = []
    if entry.merged:
        parts.append("merged " + ", ".join(f"#{i.number} ({_title(i.title)})" for i in entry.merged))
    if entry.opened:
        parts.append("opened " + ", ".join(f"#{i.number} ({_title(i.title)})" for i in entry.opened))
    if entry.issues:
        parts.append("tickets " + ", ".join(f"#{i.number}" for i in entry.issues))
    if entry.pushed:
        parts.append("pushed " + ", ".join(f'"{push.subject}"' for push in entry.pushed))
    return parts
