"""``aa prune``: remove each Finished branch and its worktree, and keep everything else."""

__lazy_modules__ = {"aa_cli.process", "json", "subprocess"}

import json
import logging
import os
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from aa_cli.process import run

log = logging.getLogger("aa")

HEADS = "refs/heads/"

# Branches asked about in one GraphQL request. Each reads up to 25 linked pull requests of up
# to 100 commits, so 50 stay well under GitHub's limit of 500,000 nodes per request.
BATCH_SIZE = 50
LINKED_LIMIT = 25
OPEN_LIMIT = 100
COMMIT_LIMIT = 100

_PULL_REQUEST_FIELDS = (
    f"number state headRefName commits(last: {COMMIT_LIMIT})"
    " { totalCount nodes { commit { oid } } }"
)


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
class Outcome:
    """What aa prune did or would do with one branch, or with one detached worktree."""

    branch: str | None
    action: Action
    reason: str
    pull_request: int | None
    worktree: Path | None

    def but(self, action: Action, reason: str | None = None) -> Outcome:
        """The same outcome with another action, and another reason when one is given."""
        new_reason = self.reason if reason is None else reason
        return Outcome(self.branch, action, new_reason, self.pull_request, self.worktree)

    def as_json(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "action": str(self.action),
            "reason": self.reason,
            "pull_request": self.pull_request,
            "worktree": None if self.worktree is None else str(self.worktree),
        }


@dataclass(frozen=True)
class _Branch:
    name: str
    tip: str  # its last commit

    @property
    def ref(self) -> str:
        return HEADS + self.name


@dataclass(frozen=True)
class _Worktree:
    path: Path
    branch: str | None  # None when detached
    locked: bool
    main: bool


class _PullRequestState(StrEnum):
    OPEN = "OPEN"
    MERGED = "MERGED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class _PullRequest:
    number: int
    state: _PullRequestState
    head: str
    commits: frozenset[str]
    all_commits_listed: bool


@dataclass(frozen=True)
class _GitHub:
    """What GitHub says: the default branch, every open pull request, and per branch the
    pull requests linked to its last commit and those merged from its name."""

    default_branch: str
    open_prs: list[_PullRequest]
    all_open_listed: bool
    linked: dict[str, list[_PullRequest]]
    merged_from: dict[str, list[int]]


def prune(cwd: Path, names: Sequence[str], *, dry_run: bool) -> list[Outcome]:
    """Remove every Finished branch (or only those of ``names``) and its worktree.

    Every branch is decided before anything is removed. With ``dry_run``, nothing changes.
    """
    top = _top_level(cwd)
    worktrees = _worktrees(top)
    branches = _local_branches(top)
    unknown = [name for name in names if name not in branches]
    if unknown:
        listed = ", ".join(unknown)
        raise PruneError(
            "branch_not_found",
            f"No local branch named {listed}; nothing changed",
            fix="git branch --list",
        )
    chosen = [branches[name] for name in dict.fromkeys(names or branches)]
    owner, repo = _github_repo(top)
    github = _ask_github(top, owner, repo, chosen)
    outcomes = [_decide(branch, worktrees, top, github) for branch in chosen]
    if not dry_run:
        outcomes = [
            _remove(top, branch, outcome) if outcome.action is Action.WOULD_REMOVE else outcome
            for branch, outcome in zip(chosen, outcomes, strict=True)
        ]
    if not names:
        outcomes.extend(
            Outcome(None, Action.KEEP, "no branch checked out (detached)", None, tree.path)
            for tree in worktrees
            if tree.branch is None
        )
    return outcomes


def _tool_error(result: subprocess.CompletedProcess[str]) -> str:
    """A tool's error message on one line."""
    return " ".join((result.stderr or result.stdout).split())


def _top_level(cwd: Path) -> Path:
    result = run("git", "rev-parse", "--show-toplevel", cwd=cwd)
    if result.returncode != 0:
        raise PruneError(
            "not_a_git_repo",
            f"{cwd} is not inside a git repo; nothing changed",
            fix="Run aa prune from a folder of the repo to clean up",
        )
    return Path(result.stdout.strip())


def _git(cwd: Path, *args: str) -> str:
    result = run("git", *args, cwd=cwd)
    if result.returncode != 0:
        detail = _tool_error(result)
        raise PruneError("step_failed", f"git {args[0]} in {cwd} failed: {detail}; nothing changed")
    return result.stdout


def _worktrees(top: Path) -> list[_Worktree]:
    """Every worktree git knows, the main folder first; a bare main folder is left out."""
    records = _git(top, "worktree", "list", "--porcelain", "-z").split("\0\0")
    trees = []
    for index, record in enumerate(filter(None, records)):
        fields = {
            key: value for key, _, value in (field.partition(" ") for field in record.split("\0"))
        }
        if "bare" in fields:
            continue
        branch = fields.get("branch")
        trees.append(
            _Worktree(
                path=Path(fields["worktree"]),
                branch=branch.removeprefix(HEADS) if branch else None,
                locked="locked" in fields,
                main=index == 0,
            )
        )
    return trees


def _local_branches(top: Path) -> dict[str, _Branch]:
    """Each local branch by name, in git's order."""
    listed = _git(top, "for-each-ref", "--format=%(refname)%00%(objectname)", HEADS)
    pairs = (line.split("\0") for line in listed.splitlines() if line)
    branches = (_Branch(ref.removeprefix(HEADS), oid) for ref, oid in pairs)
    return {branch.name: branch for branch in branches}


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
        raise PruneError(
            "no_github_remote",
            f"gh found no GitHub repo for {top}: {_tool_error(view)}",
            fix="git remote add origin https://github.com/OWNER/REPO.git",
        )
    return owner, name


def _ask_github(top: Path, owner: str, repo: str, branches: list[_Branch]) -> _GitHub:
    """Ask GitHub about every branch, one GraphQL request per batch of branches.

    The first request also reads the default branch and every open pull request.
    """
    repository_facts: dict[str, Any] = {}
    linked: dict[str, list[_PullRequest]] = {}
    merged_from: dict[str, list[int]] = {}
    for number, batch in enumerate(_batches(branches)):
        variables: dict[str, str] = {"owner": owner, "name": repo}
        for index, branch in enumerate(batch):
            variables[f"oid{index}"] = branch.tip
            variables[f"ref{index}"] = branch.name
        body = json.dumps({"query": _query(len(batch), first=number == 0), "variables": variables})
        result = run("gh", "api", "graphql", "--input", "-", cwd=top, stdin=body)
        if result.returncode != 0:
            raise PruneError(
                "github_request_failed",
                f"Asking GitHub about the pull requests failed: {_tool_error(result)};"
                " nothing changed",
            )
        repository = json.loads(result.stdout)["data"]["repository"]
        if number == 0:
            repository_facts = repository
        for index, branch in enumerate(batch):
            commit = repository.get(f"linked{index}") or {}
            linked[branch.name] = _pull_requests(commit.get("associatedPullRequests"))
            merged = (repository.get(f"merged{index}") or {}).get("nodes") or []
            merged_from[branch.name] = [node["number"] for node in merged]
    open_connection = repository_facts.get("openPullRequests") or {}
    open_prs = _pull_requests(open_connection)
    return _GitHub(
        default_branch=(repository_facts.get("defaultBranchRef") or {}).get("name", ""),
        open_prs=open_prs,
        all_open_listed=open_connection.get("totalCount", 0) <= len(open_prs),
        linked=linked,
        merged_from=merged_from,
    )


def _batches(branches: list[_Branch]) -> Iterator[list[_Branch]]:
    for start in range(0, len(branches), BATCH_SIZE):
        yield branches[start : start + BATCH_SIZE]


def _query(count: int, *, first: bool) -> str:
    params = ["$owner: String!", "$name: String!"]
    fields = []
    if first:
        fields.append("defaultBranchRef { name }")
        fields.append(
            f"openPullRequests: pullRequests(states: [OPEN], first: {OPEN_LIMIT})"
            " { totalCount nodes { ...pr } }"
        )
    for index in range(count):
        params += [f"$oid{index}: GitObjectID!", f"$ref{index}: String!"]
        fields.append(
            f"linked{index}: object(oid: $oid{index}) {{ ... on Commit {{"
            f" associatedPullRequests(first: {LINKED_LIMIT}) {{ nodes {{ ...pr }} }} }} }}"
        )
        fields.append(
            f"merged{index}: pullRequests(headRefName: $ref{index}, states: [MERGED], last: 10)"
            " { nodes { number } }"
        )
    return (
        f"query({', '.join(params)}) {{ repository(owner: $owner, name: $name) {{"
        f" {' '.join(fields)} }} }} fragment pr on PullRequest {{ {_PULL_REQUEST_FIELDS} }}"
    )


def _pull_requests(connection: dict[str, Any] | None) -> list[_PullRequest]:
    nodes = (connection or {}).get("nodes") or []
    pull_requests = []
    for node in nodes:
        commits = node["commits"]
        oids = frozenset(item["commit"]["oid"] for item in commits["nodes"])
        pull_requests.append(
            _PullRequest(
                number=node["number"],
                state=_PullRequestState(node["state"]),
                head=node["headRefName"],
                commits=oids,
                all_commits_listed=commits["totalCount"] <= len(oids),
            )
        )
    return pull_requests


def _decide(branch: _Branch, worktrees: list[_Worktree], top: Path, github: _GitHub) -> Outcome:
    """Whether ``branch`` is a Finished branch that can go with nothing lost, and why."""
    trees = [tree for tree in worktrees if tree.branch == branch.name]
    number, github_reason = _github_verdict(branch, github)
    path = trees[0].path if len(trees) == 1 else None

    def keep(reason: str) -> Outcome:
        return Outcome(branch.name, Action.KEEP, reason, number, path)

    if len(trees) > 1:
        return keep("checked out in more than one worktree")
    tree = trees[0] if trees else None
    if tree is not None:
        if _same_folder(tree.path, top):
            return keep("the folder aa runs from")
        if tree.main:
            return keep("checked out in the main folder")
        if not tree.path.is_dir():
            return keep("worktree folder is missing (git worktree prune clears it)")
        if tree.locked:
            return keep("worktree is locked")
    if branch.name == github.default_branch:
        return keep("the repo's default branch")
    if github_reason is not None:
        return keep(github_reason)
    if tree is None:
        return Outcome(
            branch.name, Action.WOULD_REMOVE, f"PR #{number} merged, no worktree", number, None
        )
    dirty = _dirty_reason(tree.path)
    if dirty is not None:
        return keep(dirty)
    return Outcome(
        branch.name, Action.WOULD_REMOVE, f"PR #{number} merged, worktree clean", number, path
    )


def _github_verdict(branch: _Branch, github: _GitHub) -> tuple[int | None, str | None]:
    """The pull request that decides, and the reason to keep the branch, or None to remove it.

    Only a merged pull request whose own commits hold the last commit counts: GitHub also
    links the squash commit on the default branch to its pull request, so a branch fresh
    from main looks linked to the last merged one. Open pull requests come from the full
    list, because GitHub stops linking open ones to a commit once it's on the default branch.
    """
    linked = github.linked[branch.name]
    open_prs = [
        pr
        for pr in [*github.open_prs, *linked]
        if pr.state is _PullRequestState.OPEN
        and (branch.tip in pr.commits or pr.head == branch.name or pr in linked)
    ]
    if open_prs:
        return open_prs[0].number, f"PR #{open_prs[0].number} open"
    merged = [
        pr for pr in linked if pr.state is _PullRequestState.MERGED and branch.tip in pr.commits
    ]
    if not merged:
        named = github.merged_from[branch.name]
        if named:
            return named[-1], f"commits added after PR #{named[-1]} merged"
        return None, "no merged pull request"
    number = merged[0].number
    if not github.all_open_listed:
        return number, f"over {OPEN_LIMIT} open pull requests, so aa can't check them all"
    unsure = [pr for pr in github.open_prs if not pr.all_commits_listed]
    if unsure:
        reason = f"over {COMMIT_LIMIT} commits, so aa can't tell if it holds this one"
        return number, f"PR #{unsure[0].number} open has {reason}"
    return number, None


def _same_folder(a: Path, b: Path) -> bool:
    return os.path.normcase(a.resolve()) == os.path.normcase(b.resolve())


def _dirty_reason(folder: Path) -> str | None:
    # --ignore-submodules=none: a submodule's own changes count, whatever .gitmodules says.
    status = _git(
        folder, "status", "--porcelain", "--untracked-files=normal", "--ignore-submodules=none"
    )
    entries = status.splitlines()
    if any(not entry.startswith("??") for entry in entries):
        return "worktree has uncommitted changes"
    if entries:
        return "worktree has untracked files"
    return None


def _remove(top: Path, branch: _Branch, outcome: Outcome) -> Outcome:
    """Remove the worktree, then the branch, unless either changed since it was checked."""
    now = run("git", "rev-parse", "--verify", "--quiet", branch.ref, cwd=top).stdout.strip()
    if not now and (outcome.worktree is None or not outcome.worktree.exists()):
        return outcome.but(Action.REMOVED, "already removed by another program")
    if now != branch.tip:
        return outcome.but(Action.KEEP, "new commits since aa checked it")
    if outcome.worktree is not None:
        if not outcome.worktree.is_dir():
            return outcome.but(
                Action.KEEP, "worktree folder is missing (git worktree prune clears it)"
            )
        head = run("git", "symbolic-ref", "--quiet", "HEAD", cwd=outcome.worktree)
        if head.stdout.strip() != branch.ref:
            return outcome.but(
                Action.KEEP, "worktree switched to another branch since aa checked it"
            )
        removed = run("git", "worktree", "remove", str(outcome.worktree), cwd=top)
        if removed.returncode != 0:
            return outcome.but(Action.FAILED, _removal_failure(top, outcome.worktree, removed))
    # Deletes the ref only if it still points at the commit GitHub was asked about; git branch
    # -D can't check that. Its config section goes too, as git branch -D would remove it.
    deleted = run("git", "update-ref", "-d", branch.ref, branch.tip, cwd=top)
    if deleted.returncode != 0:
        return outcome.but(Action.FAILED, _tool_error(deleted))
    run("git", "config", "--remove-section", f"branch.{branch.name}", cwd=top)
    return outcome.but(Action.REMOVED)


def _removal_failure(top: Path, folder: Path, removed: subprocess.CompletedProcess[str]) -> str:
    """git's message, and what to do about the folder it left behind."""
    try:
        still_registered = any(_same_folder(tree.path, folder) for tree in _worktrees(top))
    except PruneError:
        still_registered = True  # the safer advice: don't delete a folder git still tracks
    if still_registered:
        return f"{_tool_error(removed)}; close any program using {folder} and run aa prune again"
    return (
        f"{_tool_error(removed)}; git already unregistered the worktree, so close any program"
        f" using {folder} and delete that folder"
    )


def format_outcomes(outcomes: Sequence[Outcome]) -> str:
    """One aligned line per branch: the action, the branch and the reason."""
    if not outcomes:
        return "No local branches."
    names = [outcome.branch or "(detached)" for outcome in outcomes]
    action_width = max(len(outcome.action.label) for outcome in outcomes) + 2
    name_width = max(len(name) for name in names) + 2
    rows = []
    for outcome, name in zip(outcomes, names, strict=True):
        reason = outcome.reason if outcome.branch else f"{outcome.reason}, {outcome.worktree}"
        rows.append(f"{outcome.action.label:<{action_width}}{name:<{name_width}}{reason}")
    return "\n".join(rows)
