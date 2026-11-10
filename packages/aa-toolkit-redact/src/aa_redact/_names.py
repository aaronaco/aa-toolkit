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
# The user name in a URL isn't one, so `https://x-access-token:pw@host` keeps its host.
_NAME = (
    r"""(?<![\w.-])(?<!//)(?<!\\/)"""
    r"""(?P<name>[\w.-]{1,65536})(?:\\{0,32}["'])?"""  # with a closing quote
)
_SPACED_NAME_CHARACTER = r"(?:\\[^\r\n]|(?!(?P=quote))[^\\\r\n])"
_SPACED_NAME = (
    rf"""(?P<quote>\\{{0,32}}["'])(?P<spaced_name>{_SPACED_NAME_CHARACTER}{{1,256}}?)(?P=quote)"""
)
_SEPARATOR = r"[ \t]*[=:]{1,2}>?[ \t]*"  # =, :, :=, == or =>
_NAME_AND_SEPARATOR = re.compile(rf"(?:{_NAME}|{_SPACED_NAME}){_SEPARATOR}")
_QUOTE = r"""(?P<slashes>\\{0,32})(?P<quote>["'])"""
_OPENING_QUOTE = re.compile(rf"b?{_QUOTE}")
_OPENING_BRACKET = re.compile(r"[\w.]{0,256}[\[({]")
_OPENING_BRACKETS = ("[", "(", "{")
_BRACKET_OR_QUOTE = re.compile(rf"[\[\](){{}}]|{_QUOTE}")
_WHOLE_LINE = re.compile(r"[^\r\n]+")
_UNQUOTED = re.compile(r'[^\s"&]+')
_AROUND_A_VALUE = ",;:.)}]'\"\\ \t"  # punctuation after a value belongs to the text around it


def _words(name: str) -> tuple[str, ...]:
    words: list[str] = _WORD.findall(_CAMEL_CASE_BREAK.sub(" ", name).lower())
    return tuple(words)


def _closing_quote(text: str, opening: re.Match[str]) -> int:
    """Find where a quoted value ends. Quotes inside it have more backslashes than its own."""
    mark = opening["slashes"] + opening["quote"]
    escaped_backslash = 2 * (len(opening["slashes"]) + 1)
    closing = rf"(?<!\\)(?:\\{{{escaped_backslash}}})*{re.escape(mark)}"
    found = re.compile(closing).search(text, opening.end())
    return found.end() - len(mark) if found else len(text)


def _closing_bracket(text: str, start: int) -> int:
    depth = 0
    position = start
    while token := _BRACKET_OR_QUOTE.search(text, position):
        position = token.end()
        if token["quote"]:
            position = _closing_quote(text, token) + len(token[0])
        else:
            depth += 1 if token[0] in _OPENING_BRACKETS else -1
            if depth == 0:
                return position
    return len(text)


def _value_span(text: str, start: int, whole_line: bool) -> tuple[int, int]:
    """Return where the value starting at `start` begins and ends, without its quotes."""
    if opening := _OPENING_QUOTE.match(text, start):
        return opening.end(), _closing_quote(text, opening)
    end = start
    while bracket := _OPENING_BRACKET.match(text, end):
        end = _closing_bracket(text, bracket.end() - 1)
    rest = (_WHOLE_LINE if whole_line else _UNQUOTED).match(text, end)
    return start, end + len(rest[0].rstrip(_AROUND_A_VALUE)) if rest else end


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

    def is_sensitive(self, name: str) -> bool:
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
            name = pair["name"] or pair["spaced_name"]
            if self.is_sensitive(name):
                whole_line = _words(name)[-1] in _WHOLE_LINE_NAMES
                start, end = _value_span(text, pair.end(), whole_line)
                position = max(position, end)
                if start < end:
                    found.append(Finding(HIDDEN_KIND, start, end))
        return found
