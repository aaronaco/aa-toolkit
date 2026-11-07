"""Running the external tools aa wraps (uv, git, gh)."""

import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("aa")

# Git sets these while it runs a hook, for example. They point at that repo, so a tool
# aa runs would change it instead of the project in the folder aa asked for.
_REPO_VARIABLES = {
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_WORK_TREE",
}


def run(tool: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a tool found on PATH, capture its output and log the command and exit code."""
    command_line = " ".join([tool, *args])
    executable = shutil.which(tool)
    if executable is None:
        raise FileNotFoundError(f"{tool} not found on PATH")
    log.debug("Running %s (%s)", command_line, executable)
    result = subprocess.run(  # noqa: S603  # argument list, no shell, full tool path
        [executable, *args],
        cwd=cwd,
        env={key: value for key, value in os.environ.items() if key not in _REPO_VARIABLES},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log.debug("%s: exit %d", command_line, result.returncode)
    return result
