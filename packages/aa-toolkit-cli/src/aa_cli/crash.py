"""Crash reports: the cleaned Markdown file an app saves when it fails with an unexpected error.

This module uses only the standard library. It never imports the redaction library, Typer or the
rest of ``aa_cli`` (an import-linter rule checks it), so it can move into the CLIs ``aa init``
creates, or into a library of its own, unchanged. The caller passes the cleaning step as a plain
function, like the log library's ``redact=`` (ADR 0005).
"""

import contextlib
import os
import platform
import re
import traceback
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

REVIEW_LINE = (
    "Review this before you post it."
    " Sensitive values were replaced, but no tool catches everything."
)
REDACTION_FAILED = "[REDACTION FAILED]"
KEEP = 10

_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2}-\d{6})(?:-(\d+))?\.md$")


def crash_folder(app: str, environ: Mapping[str, str] = os.environ) -> Path:
    """``%LOCALAPPDATA%\\<app>\\crash``, or ``AppData\\Local`` under the home folder without it.

    A relative LOCALAPPDATA is ignored too, so a report never lands in the current folder.
    """
    local = Path(environ.get("LOCALAPPDATA") or "")
    if not local.is_absolute():
        local = Path.home() / "AppData" / "Local"
    return local / app / "crash"


def save_report(
    exc: BaseException,
    *,
    folder: Path,
    app: str,
    version: str,
    command: str | None,
    message: str,
    redact: Callable[[str], str],
    now: datetime | None = None,
) -> Path:
    """Write a Crash report for ``exc`` into ``folder`` and return its path.

    ``command`` is the subcommand's name only, never its arguments. ``message`` and the
    traceback go through ``redact`` each on its own, after the home folder and computer name
    are replaced. Only the newest ``KEEP`` reports stay.
    """
    hide = _home_and_computer()
    details = traceback.format_exception(exc)
    lines = [
        f"# {app} crash report",
        REVIEW_LINE,
        "",
        f"{app} {version} · Python {platform.python_version()} · "
        f"{platform.system()} {platform.version()}",
        f"Command: {app} {command}" if command else f"Command: {app}",
        f"Error: {_clean(message, hide, redact)}",
        "",
        "```",
        _clean("".join(details).rstrip("\n"), hide, redact),
        "```",
        "",
    ]
    folder.mkdir(parents=True, exist_ok=True)
    path = _write_new(folder, (now or datetime.now()).strftime("%Y-%m-%d-%H%M%S"), "\n".join(lines))
    _keep_newest(folder)
    return path


def _home_and_computer() -> Callable[[str], str]:
    """Replace the home folder path with ``[HOME]`` and the computer name with ``[COMPUTER]``.

    Both match any letter case, and the home path matches with either slash. The whole home
    path is replaced, never the bare user name, which would break ordinary words if short.
    """
    parts = [re.escape(part) for part in re.split(r"[\\/]+", str(Path.home())) if part]
    home = re.compile(r"[\\/]+".join(parts) + r"(?![\w-])", re.IGNORECASE) if parts else None
    names = {name for name in (os.environ.get("COMPUTERNAME"), platform.node()) if name}
    computer = (
        re.compile(
            r"(?<![\w-])(?:"
            + "|".join(map(re.escape, sorted(names, key=len, reverse=True)))
            + r")(?![\w-])",
            re.IGNORECASE,
        )
        if names
        else None
    )

    def hide(text: str) -> str:
        if home is not None:
            text = home.sub("[HOME]", text)
        if computer is not None:
            text = computer.sub("[COMPUTER]", text)
        return text

    return hide


def _clean(text: str, hide: Callable[[str], str], redact: Callable[[str], str]) -> str:
    try:
        cleaned = redact(hide(text))
    except Exception:
        return REDACTION_FAILED
    return cleaned if isinstance(cleaned, str) else REDACTION_FAILED


def _write_new(folder: Path, stamp: str, text: str) -> Path:
    """Write ``text`` to a new file named by ``stamp``, adding -2, -3 and so on if it's taken."""
    for count in range(1, 1000):
        path = folder / (f"{stamp}.md" if count == 1 else f"{stamp}-{count}.md")
        try:
            with path.open("x", encoding="utf-8") as file:
                file.write(text)
        except FileExistsError:
            continue
        return path
    raise FileExistsError(f"too many crash reports named {stamp}")


def _keep_newest(folder: Path) -> None:
    reports: list[tuple[str, int, Path]] = []
    for path in folder.iterdir():
        match = _NAME.match(path.name)
        if match and path.is_file():
            reports.append((match[1], int(match[2] or 1), path))
    reports.sort()
    for *_, path in reports[:-KEEP]:
        # The new report is saved; an old one that can't be removed is left behind.
        with contextlib.suppress(OSError):
            path.unlink()
