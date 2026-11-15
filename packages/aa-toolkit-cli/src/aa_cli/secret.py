"""``aa secret``: where a Secret goes and what its value is, never printed."""

import keyword
import sys
import tomllib
from pathlib import Path


def is_field_name(name: str) -> bool:
    """Whether ``name`` can be a field in a Settings class."""
    return name.isidentifier() and not keyword.iskeyword(name)


def project_name(folder: Path) -> str | None:
    """``[project].name`` from ``pyproject.toml`` in ``folder``, as written, or None."""
    try:
        data = tomllib.loads((folder / "pyproject.toml").read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, tomllib.TOMLDecodeError:
        return None
    project = data.get("project")
    name = project.get("name") if isinstance(project, dict) else None
    return name if isinstance(name, str) and name else None


class NotUtf8(Exception):
    """Piped standard input isn't UTF-8. The message never holds any of it."""


def read_piped_value() -> str:
    """Read standard input to the end, without one trailing line ending."""
    data: bytes = sys.stdin.buffer.read()
    try:
        text: str = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise NotUtf8("the piped value isn't UTF-8 text") from None
    for ending in ("\r\n", "\n"):
        if text.endswith(ending):
            return text.removesuffix(ending)
    return text
