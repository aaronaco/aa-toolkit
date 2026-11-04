"""Running the external tools aa wraps (uv, git, gh)."""

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("aa")


def run(tool: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a tool found on PATH, capture its output and log the command and exit code."""
    command_line = " ".join([tool, *args])
    executable = shutil.which(tool) or tool
    log.debug("Running %s (%s)", command_line, executable)
    result = subprocess.run(
        [executable, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log.debug("%s: exit %d", command_line, result.returncode)
    return result
