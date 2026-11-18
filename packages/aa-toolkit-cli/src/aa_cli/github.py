"""What gh says about the signed-in account and the GitHub repo of a folder."""

__lazy_modules__ = {"aa_cli.process"}

from pathlib import Path

from aa_cli.process import error_line, run


class GitHubError(Exception):
    """gh can't answer what aa needs to know from GitHub."""

    def __init__(self, code: str, message: str, fix: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.fix = fix


def check_signed_in(cwd: Path) -> None:
    """Fail unless gh is signed in to github.com."""
    auth = run("gh", "auth", "status", "--hostname", "github.com", cwd=cwd)
    if auth.returncode != 0:
        raise GitHubError("gh_signed_out", "gh is not signed in to github.com", fix="gh auth login")


def folder_repo(cwd: Path, *, fix: str) -> tuple[str, str]:
    """The owner and name of the GitHub repo gh finds for ``cwd``, or ``fix`` when it finds none.

    gh decides it from the git remotes, or from ``gh repo set-default`` for a fork.
    """
    view = run("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner", cwd=cwd)
    owner, _, name = view.stdout.strip().partition("/")
    if view.returncode != 0 or not name:
        raise GitHubError(
            "no_github_remote", f"gh found no GitHub repo for {cwd}: {error_line(view)}", fix=fix
        )
    return owner, name
