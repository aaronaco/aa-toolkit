"""``aa secret``: where a Secret goes and what its value is, never printed."""

import keyword
import sys
import tomllib
import unicodedata
import warnings
from pathlib import Path

from aa_settings import BaseSettings


def field_name(name: str) -> str | None:
    """``name`` as a Settings class field would spell it, or None when no field can have it.

    Python reads identifiers in NFKC form, and pydantic refuses or hides some names,
    such as ``_private`` or ``model_config``, so pydantic itself is asked.
    """
    name = unicodedata.normalize("NFKC", name)
    if not name.isidentifier() or keyword.iskeyword(name):
        return None
    namespace = {"__annotations__": {name: str}, "__module__": __name__}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter(
                "ignore"
            )  # a name that shadows an inherited attribute still works
            probe = type("Probe", (BaseSettings,), namespace)
    except Exception:
        return None
    return name if name in probe.model_fields else None


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
