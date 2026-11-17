"""``aa prune``: remove each Finished branch and its worktree, and keep everything else."""

__lazy_modules__ = {"aa_cli.process", "json"}

import json
import logging
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from aa_cli.process import run

log = logging.getLogger("aa")

# Branches asked about in one GraphQL request. Each one reads up to 2 x 10 pull requests of
# up to 100 commits, so 50 stays well under GitHub's limit of 500,000 nodes per request.
BATCH_SIZE = 50

_PULL_REQUEST_FIELDS = "number state commits(last: 100) { nodes { commit { oid } } }"


class PruneError(Exception):
    """aa prune can't start. Nothing was changed."""

    def __init__(self, code: str, message: str, fix: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.fix = fix


class Action(StrEnum):
    WOULD_REMOVE = "would_remove"
    REMOVED = "removed"
    KEEP = "keep"
    FAILED = "failed"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ")


@dataclass(frozen=True)
class Line:
    """What aa prune did or would do with one branch, or with one detached worktree."""

    branch: str | None
    action: Action
    reason: str
    pull_request: int | None
    worktree: Path | None

    def as_json(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "action": str(self.action),
            "reason": self.reason,
            "pull_request": self.pull_request,
            "worktree": None if self.worktree is None else str(self.worktree),
        }


@dataclass(frozen=True)
class _Worktree:
    path: Path
    branch: str | None  # None when detached
    locked: bool
    main: bool


@dataclass(frozen=True)
class _PullRequest:
    number: int
    state: str  # OPEN or MERGED
    commits: frozenset[str]


@dataclass(frozen=True)
class _GitHubView:
    """The pull requests linked to a branch's last commit, and those opened from its name."""

    linked: list[_PullRequest]
    named: list[_PullRequest]


def prune(cwd: Path, names: Sequence[str], *, dry_run: bool) -> list[Line]:
    """Remove every Finished branch (or only those of ``names``) and its worktree.

    With ``dry_run``, change nothing and say what would be removed.
    """
    top = _top_level(cwd)
    worktrees = _worktrees(top)
    tips = _local_branches(top)
    unknown = [name for name in names if name not in tips]
    if unknown:
        listed = ", ".join(unknown)
        raise PruneError(
            "branch_not_found",
            f"No local branch named {listed}; nothing changed",
            fix="git branch --list",
        )
    chosen = list(dict.fromkeys(names)) if names else list(tips)
    owner, repo = _github_repo(top)
    views = _ask_github(top, owner, repo, [(name, tips[name]) for name in chosen])
    by_branch = {tree.branch: tree for tree in worktrees if tree.branch is not None}
    lines = []
    for name in chosen:
        line = _decide(name, tips[name], by_branch.get(name), top, views[name])
        if line.action is Action.WOULD_REMOVE and not dry_run:
            line = _remove(top, line)
        lines.append(line)
    if not names:
        lines.extend(
            Line(None, Action.KEEP, "no branch checked out (detached)", None, tree.path)
            for tree in worktrees
            if tree.branch is None
        )
    return lines


def _top_level(cwd: Path) -> Path:
    result = run("git", "rev-parse", "--show-toplevel", cwd=cwd)
    if result.returncode != 0:
        raise PruneError(
            "not_a_git_repo",
            f"{cwd} is not inside a git repo; nothing changed",
            fix="Run aa prune from a folder of the repo to clean up",
        )
    return Path(result.stdout.strip())


def _git(top: Path, *args: str) -> str:
    result = run("git", *args, cwd=top)
    if result.returncode != 0:
        raise PruneError("step_failed", f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def _worktrees(top: Path) -> list[_Worktree]:
    """Every worktree git knows, the main folder first; a bare main folder is left out."""
    records = _git(top, "worktree", "list", "--porcelain", "-z").split("\0\0")
    trees = []
    for index, record in enumerate(filter(None, records)):
        fields = dict(
            (key, value) for key, _, value in (field.partition(" ") for field in record.split("\0"))
        )
        if "bare" in fields:
            continue
        branch = fields.get("branch")
        trees.append(
            _Worktree(
                path=Path(fields["worktree"]),
                branch=branch.removeprefix("refs/heads/") if branch else None,
                locked="locked" in fields,
                main=index == 0,
            )
        )
    return trees


def _local_branches(top: Path) -> dict[str, str]:
    """Each local branch's name and last commit, in git's order."""
    listed = _git(top, "for-each-ref", "--format=%(refname)%00%(objectname)", "refs/heads/")
    pairs = (line.split("\0") for line in listed.splitlines() if line)
    return {ref.removeprefix("refs/heads/"): oid for ref, oid in pairs}


def _github_repo(top: Path) -> tuple[str, str]:
    """The owner and name of the repo's GitHub repo, as gh sees it."""
    auth = run("gh", "auth", "status", "--hostname", "github.com", cwd=top)
    if auth.returncode != 0:
        raise PruneError(
            "gh_signed_out",
            "gh is not signed in to github.com; nothing changed",
            fix="gh auth login",
        )
    view = run("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner", cwd=top)
    owner, _, name = view.stdout.strip().partition("/")
    if view.returncode != 0 or not name:
        detail = (view.stderr or view.stdout).strip()
        raise PruneError(
            "no_github_remote",
            f"gh found no GitHub repo for {top}: {detail}",
            fix="git remote add origin https://github.com/OWNER/REPO.git",
        )
    return owner, name


def _ask_github(
    top: Path, owner: str, repo: str, tips: list[tuple[str, str]]
) -> dict[str, _GitHubView]:
    """Ask GitHub about every branch, one GraphQL request per batch of branches."""
    views: dict[str, _GitHubView] = {}
    for batch in _batches(tips):
        variables: dict[str, str] = {"owner": owner, "name": repo}
        for index, (name, oid) in enumerate(batch):
            variables[f"oid{index}"] = oid
            variables[f"ref{index}"] = name
        body = json.dumps({"query": _query(len(batch)), "variables": variables})
        result = run("gh", "api", "graphql", "--input", "-", cwd=top, stdin=body)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise PruneError(
                "github_request_failed",
                f"Asking GitHub about the pull requests failed: {detail}; nothing changed",
            )
        found = json.loads(result.stdout)["data"]["repository"]
        for index, (name, _) in enumerate(batch):
            commit = found.get(f"c{index}") or {}
            views[name] = _GitHubView(
                linked=_pull_requests(commit.get("associatedPullRequests")),
                named=_pull_requests(found.get(f"h{index}")),
            )
    return views


def _batches(tips: list[tuple[str, str]]) -> Iterator[list[tuple[str, str]]]:
    for start in range(0, len(tips), BATCH_SIZE):
        yield tips[start : start + BATCH_SIZE]


def _query(count: int) -> str:
    params = ["$owner: String!", "$name: String!"]
    fields = []
    for index in range(count):
        params += [f"$oid{index}: GitObjectID!", f"$ref{index}: String!"]
        fields.append(
            f"c{index}: object(oid: $oid{index}) {{ ... on Commit {{"
            " associatedPullRequests(first: 10) { nodes { ...pr } } } }"
        )
        fields.append(
            f"h{index}: pullRequests(headRefName: $ref{index}, states: [OPEN, MERGED], last: 10)"
            " { nodes { ...pr } }"
        )
    return (
        f"query({', '.join(params)}) {{ repository(owner: $owner, name: $name) {{"
        f" {' '.join(fields)} }} }} fragment pr on PullRequest {{ {_PULL_REQUEST_FIELDS} }}"
    )


def _pull_requests(connection: dict[str, Any] | None) -> list[_PullRequest]:
    nodes = (connection or {}).get("nodes") or []
    return [
        _PullRequest(
            number=node["number"],
            state=node["state"],
            commits=frozenset(item["commit"]["oid"] for item in node["commits"]["nodes"]),
        )
        for node in nodes
    ]


def _decide(name: str, tip: str, tree: _Worktree | None, top: Path, view: _GitHubView) -> Line:
    """Whether ``name`` is a Finished branch that can go with nothing lost, and why."""
    number, github_reason = _github_verdict(tip, view)
    path = tree.path if tree is not None else None

    def keep(reason: str) -> Line:
        return Line(name, Action.KEEP, reason, number, path)

    if tree is not None:
        if _same_folder(tree.path, top):
            return keep("the folder aa runs from")
        if tree.main:
            return keep("checked out in the main folder")
        if not tree.path.is_dir():
            return keep("worktree folder is missing (git worktree prune clears it)")
        if tree.locked:
            return keep("worktree is locked")
    if github_reason is not None:
        return keep(github_reason)
    if tree is None:
        return Line(name, Action.WOULD_REMOVE, f"PR #{number} merged, no worktree", number, None)
    dirty = _dirty_reason(tree.path)
    if dirty is not None:
        return keep(dirty)
    return Line(name, Action.WOULD_REMOVE, f"PR #{number} merged, worktree clean", number, path)


def _github_verdict(tip: str, view: _GitHubView) -> tuple[int | None, str | None]:
    """The pull request that decides, and the reason to keep the branch, or None to remove it.

    Only a pull request whose own commits hold the last commit counts: GitHub also links the
    squash commit on the default branch to its pull request, so a branch fresh from main
    looks linked to the last merged one.
    """
    holding = [pr for pr in [*view.linked, *view.named] if tip in pr.commits]
    open_holding = [pr for pr in holding if pr.state == "OPEN"]
    if open_holding:
        return open_holding[0].number, f"PR #{open_holding[0].number} open"
    merged_holding = [pr for pr in holding if pr.state == "MERGED"]
    if merged_holding:
        return merged_holding[0].number, None
    open_named = [pr for pr in view.named if pr.state == "OPEN"]
    if open_named:
        return open_named[0].number, f"PR #{open_named[0].number} open"
    merged_named = [pr for pr in view.named if pr.state == "MERGED"]
    if merged_named:
        number = merged_named[-1].number
        return number, f"commits added after PR #{number} merged"
    return None, "no merged pull request"


def _same_folder(a: Path, b: Path) -> bool:
    return os.path.normcase(a.resolve()) == os.path.normcase(b.resolve())


def _dirty_reason(folder: Path) -> str | None:
    status = run("git", "status", "--porcelain", "--untracked-files=normal", cwd=folder)
    if status.returncode != 0:
        return f"git status failed: {status.stderr.strip()}"
    entries = status.stdout.splitlines()
    if any(not entry.startswith("??") for entry in entries):
        return "worktree has uncommitted changes"
    if entries:
        return "worktree has untracked files"
    return None


def _remove(top: Path, line: Line) -> Line:
    """Remove the worktree first, then the branch; report git's message if either fails."""
    assert line.branch is not None  # noqa: S101  # detached worktrees are never removed
    if line.worktree is not None:
        removed = run("git", "worktree", "remove", str(line.worktree), cwd=top)
        if removed.returncode != 0:
            return replace(line, action=Action.FAILED, reason=_one_line(removed.stderr))
    # -D: git never sees a squash-merged branch as merged.
    deleted = run("git", "branch", "-D", line.branch, cwd=top)
    if deleted.returncode != 0:
        return replace(line, action=Action.FAILED, reason=_one_line(deleted.stderr))
    return replace(line, action=Action.REMOVED)


def _one_line(message: str) -> str:
    return " ".join(message.split())


def format_lines(lines: Sequence[Line]) -> str:
    """One aligned line per branch: the action, the branch and the reason."""
    if not lines:
        return "No local branches."
    names = [line.branch or "(detached)" for line in lines]
    action_width = max(len(line.action.label) for line in lines) + 2
    name_width = max(len(name) for name in names) + 2
    rows = []
    for line, name in zip(lines, names, strict=True):
        reason = line.reason if line.branch else f"{line.reason}, {line.worktree}"
        rows.append(f"{line.action.label:<{action_width}}{name:<{name_width}}{reason}")
    return "\n".join(rows)
