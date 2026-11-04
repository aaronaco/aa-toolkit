"""Reading git's own configuration."""

from aa_cli.process import run


def machine_config(key: str) -> str:
    """The value of ``key`` for the machine, ignoring the current repo's own config.

    A new project only sees machine-wide config, so a name set in the repo
    aa happens to run in must not count.
    """
    scoped = run("git", "config", "--get-all", "--show-scope", key)
    if scoped.returncode not in (0, 1):
        # Git before 2.26 has no --show-scope (exit 1 only means "not set").
        # Read the value as git would use it, repo config included.
        return run("git", "config", "--get", key).stdout.strip()
    values = [
        value
        for scope, _, value in (line.partition("\t") for line in scoped.stdout.splitlines())
        if scope not in ("local", "worktree")
    ]
    return values[-1].strip() if values else ""
