"""``aa prune``: removing Finished branches and their worktrees, with real git and a fake gh."""

import json
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


class Repo:
    """A real git repo on main with a github.com origin, and worktrees next to it."""

    def __init__(self, parent: Path, machine) -> None:
        self.parent = parent
        self.root = parent / "repo"
        self.root.mkdir()
        self._env = {
            **os.environ,
            **{k: v for k, v in machine.env.items() if k != "PATH" and v is not None},
        }
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("remote", "add", "origin", "https://github.com/test-user/repo.git")
        (self.root / ".gitignore").write_text(".venv/\n")
        self.git("add", ".gitignore")
        self.commit("chore: initial commit")

    def git(self, *args: str, cwd: Path | None = None, stdin: str | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd or self.root,
            env=self._env,
            input=stdin,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def commit(self, message: str, cwd: Path | None = None) -> str:
        """Commit what is staged (or nothing) and return the new commit."""
        self.git("commit", "--quiet", "--allow-empty", "--message", message, cwd=cwd)
        return self.git("rev-parse", "HEAD", cwd=cwd)

    def worktree(self, branch: str, start: str = "main") -> Path:
        """Add a worktree next to the repo with a new branch from ``start``."""
        folder = self.parent / f"wt-{branch}"
        self.git("worktree", "add", "--quiet", "-b", branch, str(folder), start)
        return folder

    def branch_with_commit(self, branch: str) -> str:
        """Add a branch with no worktree and one commit of its own on top of main."""
        oid = self.git("commit-tree", "main^{tree}", "-p", "main", "-m", f"feat: {branch}")
        self.git("branch", branch, oid)
        return oid

    def branches(self) -> set[str]:
        listed = self.git("for-each-ref", "--format=%(refname:strip=2)", "refs/heads/")
        return set(listed.splitlines())


def pull_request(
    number: int, head: str, commits: list[str], squash: str | None = None, state: str = "MERGED"
) -> dict[str, Any]:
    return {
        "number": number,
        "state": state,
        "head": head,
        "commits": commits,
        "merge_commit": squash,
    }


def prune_machine(machine):
    machine.add_real("git")
    machine.add_gh()
    machine.set_identity()
    return machine


def lines_by_branch(stdout: str) -> dict[str, list[str]]:
    """Each output line split into its columns, keyed by the branch column."""
    rows = [re.split(r"\s{2,}", line.strip()) for line in stdout.splitlines() if line.strip()]
    return {row[1]: row for row in rows}


def finished_worktree(repo: Repo, branch: str, number: int) -> tuple[Path, dict[str, Any]]:
    """A worktree whose branch's last commit is in a pull request that was squash-merged."""
    folder = repo.worktree(branch)
    tip = repo.commit(f"feat: work on {branch}", cwd=folder)
    squash = repo.commit(f"feat: work on {branch} (#{number})")
    return folder, pull_request(number, branch, [tip], squash)


def finished_branch(repo: Repo, branch: str, number: int) -> dict[str, Any]:
    """A branch with no worktree whose last commit is in a squash-merged pull request."""
    tip = repo.branch_with_commit(branch)
    squash = repo.commit(f"feat: {branch} (#{number})")
    return pull_request(number, branch, [tip], squash)


@contextmanager
def held_open(folder: Path) -> Generator[None]:
    """Keep git from deleting ``folder``, as a terminal or editor holding a file in it would.

    The held file is ignored, so the worktree still counts as clean. Windows refuses to delete
    a file that is open; elsewhere a folder without write permission does the same.
    """
    held = folder / ".venv" / "held.txt"
    held.parent.mkdir()
    held.write_text("open in an editor\n")
    if os.name == "nt":
        with held.open():
            yield
        return
    held.parent.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        if os.access(held.parent, os.W_OK):
            pytest.skip("this user can delete files in a folder without write permission")
        yield
    finally:
        held.parent.chmod(stat.S_IRWXU)


def test_dry_run_lists_a_finished_branch_as_would_remove_and_changes_nothing(
    aa_in, machine, tmp_path
):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    folder, pr = finished_worktree(repo, "ticket-64", 69)
    machine.set_pull_requests([pr])

    result = aa_in(repo.root, "prune", "--dry-run", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["ticket-64"] == [
        "would remove",
        "ticket-64",
        "PR #69 merged, worktree clean",
    ]
    assert folder.is_dir()
    assert repo.branches() == {"main", "ticket-64"}


def test_prune_removes_a_finished_worktree_and_a_finished_branch_without_one(
    aa_in, machine, tmp_path
):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    folder, with_worktree = finished_worktree(repo, "ticket-64", 69)
    without_worktree = finished_branch(repo, "ticket-65", 70)
    machine.set_pull_requests([with_worktree, without_worktree])

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    lines = lines_by_branch(result.stdout)
    assert lines["ticket-64"] == ["removed", "ticket-64", "PR #69 merged, worktree clean"]
    assert lines["ticket-65"] == ["removed", "ticket-65", "PR #70 merged, no worktree"]
    assert not folder.exists()
    assert repo.branches() == {"main"}
    assert "wt-ticket-64" not in repo.git("worktree", "list")


def test_ignored_files_in_a_removed_worktree_go_with_the_folder(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    folder, pr = finished_worktree(repo, "ticket-64", 69)
    (folder / ".venv" / "Lib").mkdir(parents=True)
    (folder / ".venv" / "Lib" / "site.py").write_text("# installed\n")
    machine.set_pull_requests([pr])

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["ticket-64"][0] == "removed"
    assert not folder.exists()


@dataclass(frozen=True)
class MixedRepo:
    """One repo holding a branch for each reason aa prune keeps or removes one."""

    repo: Repo
    machine: Any
    worktrees: dict[str, Path]


@pytest.fixture(scope="module")
def mixed(new_machine, tmp_path_factory) -> MixedRepo:
    machine = prune_machine(new_machine())
    repo = Repo(tmp_path_factory.mktemp("mixed"), machine)
    trees: dict[str, Path] = {}
    prs = []

    trees["ticket-64"], pr = finished_worktree(repo, "ticket-64", 64)
    prs.append(pr)
    prs.append(finished_branch(repo, "ticket-65", 65))

    trees["open-pr"] = repo.worktree("open-pr")
    tip = repo.commit("feat: still in review", cwd=trees["open-pr"])
    prs.append(pull_request(66, "open-pr", [tip], state="OPEN"))

    trees["uncommitted"] = repo.worktree("uncommitted")
    (trees["uncommitted"] / "notes.txt").write_text("first\n")
    repo.git("add", "notes.txt", cwd=trees["uncommitted"])
    tip = repo.commit("feat: notes", cwd=trees["uncommitted"])
    prs.append(pull_request(67, "uncommitted", [tip], repo.commit("feat: notes (#67)")))
    (trees["uncommitted"] / "notes.txt").write_text("changed\n")

    trees["untracked"], pr = finished_worktree(repo, "untracked", 68)
    (trees["untracked"] / "new.txt").write_text("not added yet\n")
    prs.append(pr)

    trees["locked"], pr = finished_worktree(repo, "locked", 69)
    repo.git("worktree", "lock", str(trees["locked"]))
    prs.append(pr)

    trees["added-after"], pr = finished_worktree(repo, "added-after", 70)
    repo.commit("fix: one more thing", cwd=trees["added-after"])
    prs.append(pr)

    trees["closed"] = repo.worktree("closed")
    tip = repo.commit("feat: abandoned", cwd=trees["closed"])
    prs.append(pull_request(71, "closed", [tip], state="CLOSED"))

    repo.branch_with_commit("no-pr")

    # An open pull request from another branch holds the same last commit as a merged one.
    trees["overlap"], pr = finished_worktree(repo, "overlap", 73)
    prs.append(pr)
    prs.append(pull_request(74, "stacked", pr["commits"], state="OPEN"))

    # Merged with a merge commit, so its last commit is on main, where GitHub links it to the
    # merged pull request only, not to the open one from another branch that also holds it.
    tip = repo.branch_with_commit("merged-in")
    repo.git("merge", "--quiet", "--no-ff", "--message", "Merge #75", "merged-in")
    prs.append(pull_request(75, "merged-in", [tip], repo.git("rev-parse", "HEAD")))
    prs.append(pull_request(76, "release-merged-in", [tip, "f" * 40], state="OPEN"))

    trees["missing"], pr = finished_worktree(repo, "missing", 72)
    shutil.rmtree(trees["missing"])
    prs.append(pr)

    # Last, so its commit is the squash commit of PR #72 at the tip of main.
    trees["fresh"] = repo.worktree("fresh")

    trees["detached"] = repo.parent / "wt-detached"
    repo.git("worktree", "add", "--quiet", "--detach", str(trees["detached"]), "main")

    machine.set_pull_requests(prs)
    return MixedRepo(repo, machine, trees)


@pytest.fixture(scope="module")
def mixed_dry_run(mixed, aa_in, tmp_path_factory):
    # Module fixtures run before the autouse one that moves LOCALAPPDATA, so move it here too:
    # a crash in this run must not write a Crash report into the real one.
    env = {**mixed.machine.env, "LOCALAPPDATA": str(tmp_path_factory.mktemp("localappdata"))}
    return aa_in(mixed.repo.root, "prune", "--dry-run", env=env)


@pytest.mark.parametrize(
    ("branch", "action", "reason"),
    [
        ("ticket-64", "would remove", "PR #64 merged, worktree clean"),
        ("ticket-65", "would remove", "PR #65 merged, no worktree"),
        ("open-pr", "keep", "PR #66 open"),
        ("uncommitted", "keep", "worktree has uncommitted changes"),
        ("untracked", "keep", "worktree has untracked files"),
        ("locked", "keep", "worktree is locked"),
        ("added-after", "keep", "commits added after PR #70 merged"),
        ("closed", "keep", "no merged pull request"),
        ("no-pr", "keep", "no merged pull request"),
        ("fresh", "keep", "no merged pull request"),
        ("missing", "keep", "worktree folder is missing (git worktree prune clears it)"),
        ("overlap", "keep", "PR #74 open"),
        ("merged-in", "keep", "PR #76 open"),
        ("main", "keep", "the folder aa runs from"),
    ],
)
def test_each_branch_is_removed_or_kept_with_its_reason(mixed_dry_run, branch, action, reason):
    assert mixed_dry_run.exit_code == 0, mixed_dry_run.output
    assert lines_by_branch(mixed_dry_run.stdout)[branch] == [action, branch, reason]


def test_a_detached_worktree_is_listed_as_kept_with_its_folder(mixed, mixed_dry_run):
    assert mixed_dry_run.exit_code == 0, mixed_dry_run.output
    action, _, reason = lines_by_branch(mixed_dry_run.stdout)["(detached)"]
    assert action == "keep"
    assert reason.startswith("no branch checked out (detached), ")
    assert Path(reason.split(", ", 1)[1]) == mixed.worktrees["detached"]


def test_a_dry_run_changes_no_folder_and_no_branch(mixed, mixed_dry_run):
    assert mixed_dry_run.exit_code == 0, mixed_dry_run.output
    assert mixed.worktrees["ticket-64"].is_dir()
    assert {"ticket-64", "ticket-65"} <= mixed.repo.branches()


def test_run_from_a_worktree_keeps_that_worktree_and_the_main_folders_branch(mixed, aa_in):
    result = aa_in(mixed.worktrees["fresh"], "prune", "--dry-run", env=mixed.machine.env)

    assert result.exit_code == 0, result.output
    lines = lines_by_branch(result.stdout)
    assert lines["fresh"] == ["keep", "fresh", "the folder aa runs from"]
    assert lines["main"] == ["keep", "main", "checked out in the main folder"]


def test_json_lists_every_branch_with_action_reason_pull_request_and_worktree(mixed, aa_in):
    result = aa_in(mixed.repo.root, "prune", "--dry-run", "--json", env=mixed.machine.env)

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    assert envelope["data"]["dry_run"] is True
    entries = envelope["data"]["branches"]
    by_branch = {entry["branch"]: entry for entry in entries}
    assert set(by_branch) == mixed.repo.branches() | {None}
    assert set(by_branch["ticket-64"]) == {
        "branch",
        "action",
        "reason",
        "pull_request",
        "worktree",
    }
    assert by_branch["ticket-64"]["action"] == "would_remove"
    assert by_branch["ticket-64"]["reason"] == "PR #64 merged, worktree clean"
    assert by_branch["ticket-64"]["pull_request"] == 64
    assert Path(by_branch["ticket-64"]["worktree"]) == mixed.worktrees["ticket-64"]
    assert by_branch["ticket-65"]["worktree"] is None
    assert by_branch["open-pr"]["action"] == "keep"
    assert by_branch["open-pr"]["pull_request"] == 66
    assert by_branch["no-pr"]["pull_request"] is None
    assert Path(by_branch[None]["worktree"]) == mixed.worktrees["detached"]


def test_json_after_a_real_run_says_removed_and_not_a_dry_run(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    machine.set_pull_requests([finished_branch(repo, "ticket-65", 65)])

    result = aa_in(repo.root, "prune", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["dry_run"] is False
    by_branch = {entry["branch"]: entry for entry in data["branches"]}
    assert by_branch["ticket-65"]["action"] == "removed"


def test_named_branches_limit_the_run_to_those_branches(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    folder, named = finished_worktree(repo, "ticket-64", 64)
    other = finished_branch(repo, "ticket-65", 65)
    machine.set_pull_requests([named, other])

    result = aa_in(repo.root, "prune", "ticket-64", env=machine.env)

    assert result.exit_code == 0, result.output
    assert list(lines_by_branch(result.stdout)) == ["ticket-64"]
    assert not folder.exists()
    assert repo.branches() == {"main", "ticket-65"}


def test_a_named_branch_that_is_kept_makes_aa_exit_1(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    folder = repo.worktree("open-pr")
    tip = repo.commit("feat: in review", cwd=folder)
    machine.set_pull_requests([pull_request(66, "open-pr", [tip], state="OPEN")])

    result = aa_in(repo.root, "prune", "open-pr", env=machine.env)

    assert result.exit_code == 1, result.output
    assert lines_by_branch(result.stdout)["open-pr"] == ["keep", "open-pr", "PR #66 open"]
    assert folder.is_dir()


def test_an_unknown_branch_name_fails_with_nothing_changed(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    folder, pr = finished_worktree(repo, "ticket-64", 64)
    machine.set_pull_requests([pr])

    result = aa_in(repo.root, "prune", "ticket-64", "no-such-branch", "--json", env=machine.env)

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "branch_not_found"
    assert "no-such-branch" in error["message"]
    assert error["fix"]
    assert folder.is_dir()
    assert repo.branches() == {"main", "ticket-64"}
    assert machine.graphql_requests() == []


def test_a_worktree_that_cannot_be_removed_fails_and_the_others_still_go(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    held, held_pr = finished_worktree(repo, "ticket-64", 64)
    free, free_pr = finished_worktree(repo, "ticket-65", 65)
    machine.set_pull_requests([held_pr, free_pr])

    with held_open(held):
        result = aa_in(repo.root, "prune", "--json", env=machine.env)

    assert result.exit_code == 1, result.output
    by_branch = {entry["branch"]: entry for entry in json.loads(result.stdout)["data"]["branches"]}
    assert by_branch["ticket-64"]["action"] == "failed"
    reason = by_branch["ticket-64"]["reason"]
    assert "failed to delete" in reason
    # git unregisters the worktree before it gives up, so only the folder is left to delete.
    assert reason.endswith(f"close any program using {held} and delete that folder")
    assert by_branch["ticket-65"]["action"] == "removed"
    assert not free.exists()
    assert repo.branches() == {"main", "ticket-64"}


def test_many_branches_take_one_graphql_request_per_batch(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    head = repo.git("rev-parse", "HEAD")
    updates = "".join(f"create refs/heads/topic-{index:02}\0{head}\0" for index in range(60))
    repo.git("update-ref", "--stdin", "-z", stdin=updates)

    result = aa_in(repo.root, "prune", "--dry-run", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)["data"]["branches"]) == 61
    requests = machine.graphql_requests()
    assert len(requests) == 2
    asked = [value for body in requests for value in body["variables"].values()]
    assert sum(value.startswith("topic-") for value in asked) == 60


def test_outside_a_git_repo_aa_fails_with_a_fix(aa_in, machine, tmp_path):
    machine = prune_machine(machine)

    result = aa_in(tmp_path, "prune", "--json", env=machine.env)

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "not_a_git_repo"
    assert error["fix"]


def test_with_gh_signed_out_aa_fails_with_a_fix_and_changes_nothing(aa_in, machine, tmp_path):
    machine.add_real("git")
    machine.add_gh(signed_in=False)
    machine.set_identity()
    repo = Repo(tmp_path, machine)
    folder, pr = finished_worktree(repo, "ticket-64", 64)
    machine.set_pull_requests([pr])

    result = aa_in(repo.root, "prune", "--json", env=machine.env)

    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["error"] == {
        "code": "gh_signed_out",
        "message": "gh is not signed in to github.com; nothing changed",
        "fix": "gh auth login",
    }
    assert folder.is_dir()
    assert repo.branches() == {"main", "ticket-64"}


def test_with_no_github_remote_aa_fails_with_a_fix_and_changes_nothing(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    repo.git("remote", "remove", "origin")
    folder, pr = finished_worktree(repo, "ticket-64", 64)
    machine.set_pull_requests([pr])

    result = aa_in(repo.root, "prune", "--json", env=machine.env)

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "no_github_remote"
    assert "none of the git remotes" in error["message"]
    assert error["fix"] == "git remote add origin https://github.com/OWNER/REPO.git"
    assert folder.is_dir()


def test_a_failed_github_request_fails_and_changes_nothing(aa_in, machine, tmp_path):
    machine.add_real("git")
    machine.add_gh(graphql_fails=True)
    machine.set_identity()
    repo = Repo(tmp_path, machine)
    folder, pr = finished_worktree(repo, "ticket-64", 64)
    machine.set_pull_requests([pr])

    result = aa_in(repo.root, "prune", "--json", env=machine.env)

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "github_request_failed"
    assert "error connecting to api.github.com" in error["message"]
    assert folder.is_dir()


def test_errors_in_human_mode_show_the_message_and_fix_on_stderr(aa_in, machine, tmp_path):
    machine = prune_machine(machine)

    result = aa_in(tmp_path, "prune", env=machine.env)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error: " in result.stderr
    assert "Fix: " in result.stderr


def test_after_a_failed_removal_a_rerun_removes_the_branch(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    held, pr = finished_worktree(repo, "ticket-64", 64)
    machine.set_pull_requests([pr])
    with held_open(held):
        first = aa_in(repo.root, "prune", env=machine.env)
    assert first.exit_code == 1, first.output

    rerun = aa_in(repo.root, "prune", env=machine.env)

    assert rerun.exit_code == 0, rerun.output
    assert lines_by_branch(rerun.stdout)["ticket-64"] == [
        "removed",
        "ticket-64",
        "PR #64 merged, no worktree",
    ]


def test_the_default_branch_is_kept_when_the_main_folder_has_another_branch(
    aa_in, machine, tmp_path
):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    main_tip = repo.git("rev-parse", "main")
    repo.git("switch", "--quiet", "--create", "work")
    machine.set_pull_requests([pull_request(90, "release", [main_tip], "e" * 40)])

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["main"] == ["keep", "main", "the repo's default branch"]
    assert "main" in repo.branches()


def test_a_branch_checked_out_in_two_worktrees_is_kept(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    folder, pr = finished_worktree(repo, "ticket-64", 64)
    second = repo.parent / "wt-second"
    repo.git("worktree", "add", "--quiet", "--force", str(second), "ticket-64")
    machine.set_pull_requests([pr])

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["ticket-64"] == [
        "keep",
        "ticket-64",
        "checked out in more than one worktree",
    ]
    assert folder.is_dir()
    assert second.is_dir()


def test_changes_in_a_submodule_keep_the_worktree_even_when_git_is_told_to_ignore_them(
    aa_in, machine, tmp_path
):
    machine = prune_machine(machine)
    library = tmp_path / "library"
    library.mkdir()
    lib = Repo(library, machine)
    repo = Repo(tmp_path, machine)
    folder = repo.worktree("ticket-64")
    add_submodule = ["-c", "protocol.file.allow=always", "submodule", "add", "--quiet"]
    repo.git(*add_submodule, str(lib.root), "lib", cwd=folder)
    repo.git("config", "--file", ".gitmodules", "submodule.lib.ignore", "all", cwd=folder)
    repo.git("add", ".gitmodules", cwd=folder)
    tip = repo.commit("feat: add the library", cwd=folder)
    machine.set_pull_requests([pull_request(64, "ticket-64", [tip], repo.commit("feat (#64)"))])
    (folder / "lib" / "local-work.txt").write_text("not saved anywhere else\n")

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["ticket-64"] == [
        "keep",
        "ticket-64",
        "worktree has uncommitted changes",
    ]
    assert (folder / "lib" / "local-work.txt").exists()


def test_a_worktree_git_cannot_read_stops_aa_before_anything_is_removed(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    broken, broken_pr = finished_worktree(repo, "ticket-64", 64)
    git_dir = Path(repo.git("rev-parse", "--absolute-git-dir", cwd=broken))
    (git_dir / "index").write_bytes(b"not an index")
    other, other_pr = finished_worktree(repo, "ticket-65", 65)
    machine.set_pull_requests([broken_pr, other_pr])

    result = aa_in(repo.root, "prune", "--json", env=machine.env)

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "step_failed"
    assert str(broken) in error["message"]
    assert other.is_dir()
    assert repo.branches() == {"main", "ticket-64", "ticket-65"}


def merged_into_main(repo: Repo, branch: str, number: int) -> tuple[str, dict[str, Any]]:
    """A branch merged with a merge commit, so its last commit is on main."""
    tip = repo.branch_with_commit(branch)
    repo.git("merge", "--quiet", "--no-ff", "--message", f"Merge #{number}", branch)
    return tip, pull_request(number, branch, [tip], repo.git("rev-parse", "HEAD"))


def test_an_open_pull_request_with_over_100_commits_keeps_a_branch_it_may_hold(
    aa_in, machine, tmp_path
):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    tip, pr = merged_into_main(repo, "ticket-64", 64)
    later = [f"{index:040x}" for index in range(1, 101)]
    machine.set_pull_requests([pr, pull_request(65, "stacked", [tip, *later], state="OPEN")])

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["ticket-64"] == [
        "keep",
        "ticket-64",
        "PR #65 open has over 100 commits, so aa can't tell if it holds this one",
    ]
    assert "ticket-64" in repo.branches()


def test_over_100_open_pull_requests_keep_every_branch_that_would_go(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    _, pr = merged_into_main(repo, "ticket-64", 64)
    others = [pull_request(1000 + n, f"other-{n}", [f"{n:040x}"], state="OPEN") for n in range(101)]
    machine.set_pull_requests([pr, *others])

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["ticket-64"] == [
        "keep",
        "ticket-64",
        "over 100 open pull requests, so aa can't check them all",
    ]
    assert "ticket-64" in repo.branches()


COMMIT_AS_SOMEONE = ["-c", "user.name=T", "-c", "user.email=t@example.com"]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            [*COMMIT_AS_SOMEONE, "commit", "--quiet", "--allow-empty", "--message", "wip"],
            "new commits since aa checked it",
        ),
        (
            ["switch", "--quiet", "--create", "other"],
            "worktree switched to another branch since aa checked it",
        ),
    ],
    ids=["new-commit", "switched-branch"],
)
def test_a_worktree_that_changes_while_gh_asks_github_is_kept(
    aa_in, machine, tmp_path, change, reason
):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    folder, pr = finished_worktree(repo, "ticket-64", 64)
    machine.set_pull_requests([pr])
    machine.change_repo_during_graphql(["-C", str(folder), *change])

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["ticket-64"] == ["keep", "ticket-64", reason]
    assert folder.is_dir()
    assert "ticket-64" in repo.branches()


def test_a_branch_that_moves_while_gh_asks_github_is_kept(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    pr = finished_branch(repo, "ticket-65", 65)
    machine.set_pull_requests([pr])
    machine.change_repo_during_graphql(
        ["-C", str(repo.root), "update-ref", "refs/heads/ticket-65", "main"]
    )

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["ticket-65"] == [
        "keep",
        "ticket-65",
        "new commits since aa checked it",
    ]
    assert "ticket-65" in repo.branches()


def test_a_removed_branch_leaves_no_branch_config_behind(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    pr = finished_branch(repo, "ticket-65", 65)
    repo.git("config", "branch.ticket-65.remote", "origin")
    repo.git("config", "branch.ticket-65.merge", "refs/heads/ticket-65")
    machine.set_pull_requests([pr])

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert repo.branches() == {"main"}
    assert "branch.ticket-65" not in repo.git("config", "--list", "--local")


def test_a_branch_another_run_removed_meanwhile_counts_as_removed(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    machine.set_pull_requests([finished_branch(repo, "ticket-65", 65)])
    machine.change_repo_during_graphql(["-C", str(repo.root), "branch", "-D", "ticket-65"])

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["ticket-65"] == [
        "removed",
        "ticket-65",
        "already removed by another program",
    ]


def test_a_branch_a_rebase_is_stopped_on_is_kept(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    folder, pr = finished_worktree(repo, "ticket-64", 64)
    machine.set_pull_requests([pr])
    # The rebase stops after replaying the commit and leaves the worktree detached.
    stopped = subprocess.run(
        ["git", "rebase", "--exec", "exit 1", "HEAD~1"],
        cwd=folder,
        env=repo._env,
        capture_output=True,
        text=True,
    )
    assert stopped.returncode != 0
    assert repo.git("branch", "--show-current", cwd=folder) == ""

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["ticket-64"] == [
        "keep",
        "ticket-64",
        f"a rebase or bisect in {folder} uses it",
    ]
    assert "ticket-64" in repo.branches()
    assert folder.is_dir()


def test_a_branch_checked_out_while_gh_asks_github_is_kept(aa_in, machine, tmp_path):
    machine = prune_machine(machine)
    repo = Repo(tmp_path, machine)
    machine.set_pull_requests([finished_branch(repo, "ticket-65", 65)])
    other = repo.parent / "wt-other"
    repo.git("worktree", "add", "--quiet", "--detach", str(other), "main")
    machine.change_repo_during_graphql(["-C", str(other), "switch", "--quiet", "ticket-65"])

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["ticket-65"] == [
        "keep",
        "ticket-65",
        f"checked out in {other} while aa ran",
    ]
    assert "ticket-65" in repo.branches()


def test_a_clean_worktree_with_a_submodule_is_kept_because_git_wont_remove_it(
    aa_in, machine, tmp_path
):
    machine = prune_machine(machine)
    library = tmp_path / "library"
    library.mkdir()
    lib = Repo(library, machine)
    repo = Repo(tmp_path, machine)
    folder = repo.worktree("ticket-64")
    add_submodule = ["-c", "protocol.file.allow=always", "submodule", "add", "--quiet"]
    repo.git(*add_submodule, str(lib.root), "lib", cwd=folder)
    tip = repo.commit("feat: add the library", cwd=folder)
    machine.set_pull_requests([pull_request(64, "ticket-64", [tip], repo.commit("feat (#64)"))])

    result = aa_in(repo.root, "prune", env=machine.env)

    assert result.exit_code == 0, result.output
    assert lines_by_branch(result.stdout)["ticket-64"] == [
        "keep",
        "ticket-64",
        "worktree has submodules, which git worktree remove won't remove",
    ]
    assert folder.is_dir()
