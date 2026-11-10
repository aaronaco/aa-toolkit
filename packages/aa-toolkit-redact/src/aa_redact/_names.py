"""Deciding which field names are Sensitive names."""

import re
from collections.abc import Iterable

_ANYWHERE = ("password", "passwd", "secret", "credential")
_LAST_WORDS = (
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "authorization",
    "cookie",
    "pwd",
    "passphrase",
)

_CAMEL_CASE_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[^\W_]+")


def _words(name: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(_CAMEL_CASE_BREAK.sub(" ", name).lower()))


class SensitiveNames:
    """The words an app's Redactor hides values for, and the exact names it leaves visible."""

    __slots__ = ("_allowed", "_endings")

    def __init__(self, names: Iterable[str], allow_names: Iterable[str]) -> None:
        added = [_words(name) for name in names]
        for name, words in zip(names, added, strict=True):
            if not words:
                raise ValueError(f"names= takes words with letters or digits, not {name!r}")
        self._endings = (*(_words(word) for word in _LAST_WORDS), *added)
        self._allowed = {_words(name) for name in allow_names}

    def hide(self, name: str) -> bool:
        """Say whether the value under this field name must be hidden."""
        words = _words(name)
        if words in self._allowed:
            return False
        joined = "".join(words)
        return any(word in joined for word in _ANYWHERE) or any(
            words[-len(ending) :] == ending for ending in self._endings
        )
