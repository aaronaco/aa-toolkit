"""Deciding which field names are Sensitive names."""

import re
from collections.abc import Iterable

from aa_redact._finding import Finding

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

# These headers can hold several secrets separated by spaces or semicolons.
_WHOLE_LINE_NAMES = ("authorization", "cookie")

HIDDEN_KIND = "REDACTED"

_CAMEL_CASE_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[^\W_]+")

# A name can start only where a longer name can't have started, so a long run of name
# characters is tried once. A value is read in steps, so a name inside it isn't tried again.
_NAME_AND_SEPARATOR = re.compile(
    r"""
    (?<![\w.-])(?P<name>[\w.-]{1,256})
    (?:\\{0,32}["'])?                     # the quote that closes a quoted name
    [ \t]{0,8}[=:]{1,2}>?[ \t]{0,8}       # =, :, :=, == or =>
    """,
    re.VERBOSE,
)
_OPENING_QUOTE = re.compile(r"""b?(?P<slashes>\\{0,32})(?P<quote>["'])""")
_OPENING_BRACKETS = ("[", "(", "{")
_BRACKET = re.compile(r"[\[\](){}]")
_WHOLE_LINE = re.compile(r"[^\r\n]+")
_UNQUOTED = re.compile(r'[^\s"&]+')
_AROUND_A_VALUE = ",;:.)}'\"\\ \t"  # punctuation after a value belongs to the text around it


def _words(name: str) -> tuple[str, ...]:
    words: list[str] = _WORD.findall(_CAMEL_CASE_BREAK.sub(" ", name).lower())
    return tuple(words)


def _closing_quote(text: str, opening: re.Match[str]) -> int:
    """Find where a quoted value ends. Quotes inside it have more backslashes than its own."""
    closing = rf"(?<!\\){re.escape(opening['slashes'] + opening['quote'])}"
    found = re.compile(closing).search(text, opening.end())
    return found.start() if found else len(text)


def _closing_bracket(text: str, start: int) -> int:
    depth = 0
    for bracket in _BRACKET.finditer(text, start):
        depth += 1 if bracket[0] in _OPENING_BRACKETS else -1
        if depth == 0:
            return bracket.end()
    return len(text)


def _value_span(text: str, start: int, whole_line: bool) -> tuple[int, int]:
    """Return where the value starting at `start` begins and ends, without its quotes."""
    if opening := _OPENING_QUOTE.match(text, start):
        return opening.end(), _closing_quote(text, opening)
    if not whole_line and text.startswith(_OPENING_BRACKETS, start):
        return start, _closing_bracket(text, start)
    value = (_WHOLE_LINE if whole_line else _UNQUOTED).match(text, start)
    return start, start + len(value[0].rstrip(_AROUND_A_VALUE)) if value else start


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

    def find_values(self, text: str) -> list[Finding]:
        """Find the value of every `name=value` pair in text whose name must be hidden."""
        found: list[Finding] = []
        position = 0
        while pair := _NAME_AND_SEPARATOR.search(text, position):
            position = pair.end()
            if self.hide(pair["name"]):
                whole_line = _words(pair["name"])[-1] in _WHOLE_LINE_NAMES
                start, end = _value_span(text, pair.end(), whole_line)
                position = max(position, end)
                if start < end:
                    found.append(Finding(HIDDEN_KIND, start, end))
        return found
