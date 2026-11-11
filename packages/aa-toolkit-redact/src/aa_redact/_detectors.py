"""Making Detectors, and the ones that come built in."""

import bisect
import ipaddress
import json
import re
import unicodedata
import urllib.parse
from collections.abc import Callable, Iterable, Iterator

from aa_redact._finding import LONGEST_VALUE, Detector, Finding


def pattern(kind: str, regex: str) -> Detector:
    """Make a Detector that finds every match of a regular expression."""
    compiled = re.compile(regex)

    def detect(text: str) -> list[Finding]:
        return [Finding(kind, *match.span()) for match in compiled.finditer(text) if match[0]]

    return detect


_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-f]{4})")


def _known_regex(part: str) -> str:
    """Escape one encoded character for regex, matching its hex escapes in either case."""
    escaped = _PERCENT_ESCAPE.sub(lambda match: f"(?i:{match[0]})", re.escape(part))
    return _UNICODE_ESCAPE.sub(r"\\u(?i:\1)", escaped)


def _json_escape(parts: Iterable[str], *, ensure_ascii: bool) -> list[str]:
    return [json.dumps(part, ensure_ascii=ensure_ascii)[1:-1] for part in parts]


def _known_forms(value: str) -> Iterator[tuple[int, str]]:
    """Yield `(length, regex)` for a Known value as written, URL-encoded and JSON-escaped."""
    for url_parts in (
        list(value),
        [urllib.parse.quote(character, safe="") for character in value],
        [urllib.parse.quote(character) for character in value],
        [urllib.parse.quote_plus(character) for character in value],
    ):
        for ensure_ascii in (True, False):
            escaped = _json_escape(url_parts, ensure_ascii=ensure_ascii)
            for parts in (
                url_parts,
                escaped,
                [part.replace("/", r"\/") for part in escaped],
                _json_escape(escaped, ensure_ascii=ensure_ascii),
            ):
                yield (
                    sum(len(part) for part in parts),
                    "".join(_known_regex(part) for part in parts),
                )


def known_values(kind: str, values: Iterable[str]) -> Detector:
    """Make a Detector that finds the exact values an app already holds."""
    if isinstance(values, str):
        raise TypeError(f"values takes a list, like [{values!r}]")
    forms = [
        regex
        for _, regex in sorted(
            {form for value in values if value for form in _known_forms(value)},
            reverse=True,
        )
    ]
    if not forms:
        return lambda text: ()
    compiled = re.compile("|".join(forms))

    def detect(text: str) -> Iterator[Finding]:
        position = 0
        end = 0
        while match := compiled.search(text, position):
            if match.end() > end:
                end = match.end()
                yield Finding(kind, *match.span())
            position = match.start() + 1

    return detect


def _kept(kind: str, regex: str, keep: Callable[[str], bool]) -> Detector:
    """Make a Detector for the matches whose `value` group `keep` agrees with."""
    compiled = re.compile(regex)

    def detect(text: str) -> list[Finding]:
        return [
            Finding(kind, *match.span())
            for match in compiled.finditer(text)
            if keep(match["value"])
        ]

    return detect


def _mark_ranges() -> str:
    """Return the combining marks, such as accents and vowel signs, as regex character ranges.

    A regex's word class leaves them out, so a name written with one would stop an email match.
    """
    ranges: list[list[int]] = []
    for code in range(0x300, 0x20000):
        if unicodedata.category(chr(code))[0] == "M":
            if ranges and ranges[-1][1] == code - 1:
                ranges[-1][1] = code
            else:
                ranges.append([code, code])
    return "".join(f"{chr(first)}-{chr(last)}" for first, last in ranges)


# Every repeat is bounded, so text written to be slow can't stall the app. A token starts only
# where a longer token can't have started, so a long run of token characters is tried once.

_MARK = _mark_ranges()
_LOCAL = rf"[\w{_MARK}.%+-]{{1,64}}"
_EMAIL = re.compile(
    # An apostrophe counts only inside a name, so the quotes around an email stay.
    rf"{_LOCAL}(?:(?<=\w)['’](?=\w){_LOCAL}){{0,3}}"
    rf"@(?:[\w{_MARK}-]{{1,63}}\.){{1,126}}"
    rf"(?:[xX][nN]--[A-Za-z0-9-]{{1,59}}|(?:[^\W\d_][{_MARK}]{{0,4}}){{2,24}})"
)

# Tokens match on their prefix and a minimum length, so a longer format still matches.
_AWS = rf"(?<![A-Za-z0-9])(?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{{16,{LONGEST_VALUE}}}+"
_GITHUB = (
    rf"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{{36,{LONGEST_VALUE}}}+"
    rf"|github_pat_[A-Za-z0-9_]{{22,{LONGEST_VALUE}}}+)"
)
_OPENAI_STYLE = rf"(?<![A-Za-z0-9_-])sk-(?P<value>[A-Za-z0-9_-]{{20,{LONGEST_VALUE}}}+)"
_SLACK = (
    r"(?<![A-Za-z0-9_.-])(?:xox[abcdeprs](?:\.xox[abcdeprs])?|xapp)-"
    rf"[A-Za-z0-9%-]{{10,{LONGEST_VALUE}}}+"
)
_JWT_PART = rf"[A-Za-z0-9_-]{{5,{LONGEST_VALUE}}}+"
_JWT = rf"(?<![A-Za-z0-9_-])eyJ{_JWT_PART}\.eyJ{_JWT_PART}\.[A-Za-z0-9_-]{{0,{LONGEST_VALUE}}}+"
_BEARER = (
    r"(?<![A-Za-z0-9_-])(?i:bearer)[ \t]{1,16}+"
    rf"(?P<value>[A-Za-z0-9._~+/-]{{8,{LONGEST_VALUE}}}+={{0,8}}+)"
)

_KEY_LABEL = r"(?:[A-Z0-9]{1,20} ){0,4}PRIVATE KEY(?: BLOCK)?-----"
# A real line break, one escaped as \n, or none, as when a key's line breaks were taken out.
_KEY_LINE_BREAK = r"(?:\s|\\{1,4}[rn]){0,8}+"
_KEY_HEADER = r"[A-Za-z-]{1,32}+:[ \t]?[\w,.]{1,64}+(?:[ -][\w,.]{1,64}+){0,8}+"
_KEY_LINE = rf"(?:{_KEY_HEADER}|[A-Za-z0-9+/=.…]{{1,256}}+)"  # with ... where it was shortened
# A key cut off before its end line is hidden up to where its lines stop. A long line is read
# in pieces, so no part of it is left.
_PEM = (
    rf"-----BEGIN {_KEY_LABEL}(?:{_KEY_LINE_BREAK}{_KEY_LINE}){{0,{LONGEST_VALUE}}}+"
    rf"(?:{_KEY_LINE_BREAK}-----END {_KEY_LABEL})?"
)

# A password may hold an @ that wasn't encoded, so it runs to the last @ before the host.
_URL_PASSWORD = re.compile(
    r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]{0,31}+:\\?/\\?/"  # :// or JSON's :\/\/
    rf"[^\s:/?#@\[\]\"'<>\\]{{0,{LONGEST_VALUE}}}+"
    rf":(?P<password>[^\s/?#\"'<>\\]{{1,{LONGEST_VALUE}}})@"
)

# A card is written as one run of digits, or in the groups printed on it.
_CARD_SEPARATOR = "[ .-]"
_CARD = re.compile(
    r"(?<![0-9])(?:"
    r"[0-9]{13,19}+"
    rf"|(?P<main>[0-9]{{4}}{_CARD_SEPARATOR}[0-9]{{4}}{_CARD_SEPARATOR}[0-9]{{4}}"
    rf"{_CARD_SEPARATOR}[0-9]{{3,4}})(?P<tail>{_CARD_SEPARATOR}[0-9]{{1,3}})?"
    rf"|[0-9]{{4}}{_CARD_SEPARATOR}[0-9]{{6}}{_CARD_SEPARATOR}[0-9]{{4,5}}"
    r")(?![0-9])"
)
# Each issuer's first digits and the lengths its cards come in.
_CARD_ISSUER = re.compile(
    r"4(?:[0-9]{12}|[0-9]{15}|[0-9]{18})"  # Visa
    r"|(?:5[1-5][0-9]{2}|222[1-9]|22[3-9][0-9]|2[3-6][0-9]{2}|27[01][0-9]|2720)[0-9]{12}"
    r"|3[47][0-9]{13}"  # American Express
    r"|(?:6011|64[4-9][0-9]|65[0-9]{2})[0-9]{12,15}"  # Discover
    r"|62[0-9]{14,17}"  # UnionPay
    r"|35(?:2[89]|[3-8][0-9])[0-9]{12,15}"  # JCB
    r"|3(?:0[0-5][0-9]|095|[689][0-9]{2})[0-9]{10,15}"  # Diners Club
    r"|(?:5018|5020|5038|5893|6304|6759|676[1-3])[0-9]{9,15}"  # Maestro
)

_IPV4 = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?!\.?\d)", re.ASCII)
_IPV6 = re.compile(r"(?<![\w:.])[0-9A-Fa-f:.]{2,45}+(?![\w:])")
_HEX_DIGIT = re.compile(r"[0-9A-Fa-f]")

_PHONE = re.compile(
    r"(?<![\w+.-])(?:"
    r"\+[0-9]{1,3}[ -]?(?:\([0-9]{1,4}\)[ -]?)?(?:[0-9][ -]?){5,13}[0-9]"  # +44 20 7946 0958
    r"|\([0-9]{2,5}\)[ -]?(?:[0-9][ -]?){5,11}[0-9]"  # (555) 123-4567
    r"|[0-9]{3}(?P<sep>[ .-])[0-9]{3}(?P=sep)[0-9]{4}"  # 555-123-4567
    r"|0[0-9]{1,4}[ -][0-9]{3,4}[ -][0-9]{3,4}"  # 020 7946 0958
    r")(?!\w)"
)
_NOT_A_DIGIT = re.compile(r"\D", re.ASCII)


def _looks_random(value: str) -> bool:
    """Say whether a key has a digit or both cases, as a random one does and `sk-learn` doesn't."""
    return any(character.isdigit() for character in value) or (
        any(character.isupper() for character in value)
        and any(character.islower() for character in value)
    )


_LONGEST_WORD = 24  # past any English word, so a longer run of letters is a token


def _is_plain_word(word: str) -> bool:
    return (
        len(word) <= _LONGEST_WORD
        and word.isalpha()
        and (word.islower() or word.isupper() or word.istitle())
    )


def _is_not_plain_words(value: str) -> bool:
    """Say whether a value isn't just words, like `authentication.` or `token-based`."""
    return not all(_is_plain_word(word) for word in value.replace("-", ".").split(".") if word)


def _url_password(text: str) -> list[Finding]:
    return [
        Finding("URL_PASSWORD", *match.span("password")) for match in _URL_PASSWORD.finditer(text)
    ]


def _email(text: str) -> Iterator[Finding]:
    """Find emails, leaving out a URL's `password@host`, which only looks like one."""
    passwords = [match.span("password") for match in _URL_PASSWORD.finditer(text)]
    starts = [start for start, _ in passwords]
    for match in _EMAIL.finditer(text):
        before = bisect.bisect_right(starts, match.start()) - 1
        if before < 0 or not match.start() < passwords[before][1] < match.end():
            yield Finding("EMAIL", *match.span())


def _is_card(digits: str) -> bool:
    """Say whether the digits start like a real card and pass the Luhn check."""
    if not _CARD_ISSUER.fullmatch(digits):
        return False
    total = 0
    for position, digit in enumerate(reversed(digits)):
        value = int(digit) * (2 if position % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0


def _card(text: str) -> Iterator[Finding]:
    position = 0
    while match := _CARD.search(text, position):
        start = match.start()
        # Digits after a grouped card, like an expiry date, may not be part of it.
        ends = [match.end(), match.end("main")] if match["tail"] else [match.end()]
        end = next((end for end in ends if _is_card(_NOT_A_DIGIT.sub("", text[start:end]))), None)
        if end is None:
            position = start + 1  # a card can still start at a later group of digits
        else:
            yield Finding("CARD", start, end)
            position = end


def ip_address(text: str) -> list[Finding]:
    """Find IPv4 and IPv6 addresses. Built in, and off until an app passes it in `detectors=`."""
    found: list[Finding] = []
    for match in _IPV4.finditer(text):
        try:
            ipaddress.IPv4Address(match[0])
        except ValueError:
            continue
        found.append(Finding("IP_ADDRESS", *match.span()))
    for match in _IPV6.finditer(text):
        address = match[0].rstrip(".")
        if not _is_ipv6(address) and address.endswith(":"):
            address = address[:-1]  # a colon after the address, as in `peer ::1: down`
        if _is_ipv6(address):
            found.append(Finding("IP_ADDRESS", match.start(), match.start() + len(address)))
    return found


def _is_ipv6(address: str) -> bool:
    if ":" not in address or not _HEX_DIGIT.search(address):
        return False
    try:
        ipaddress.IPv6Address(address)
    except ValueError:
        return False
    return True


def phone_number(text: str) -> list[Finding]:
    """Find phone numbers. Built in, and off until an app passes it in `detectors=`."""
    return [
        Finding("PHONE", *match.span())
        for match in _PHONE.finditer(text)
        if 7 <= len(_NOT_A_DIGIT.sub("", match[0])) <= 15
    ]


BUILT_IN: dict[str, Detector] = {
    "AWS_ACCESS_KEY": pattern("AWS_ACCESS_KEY", _AWS),
    "GITHUB_TOKEN": pattern("GITHUB_TOKEN", _GITHUB),
    "API_KEY": _kept("API_KEY", _OPENAI_STYLE, _looks_random),
    "SLACK_TOKEN": pattern("SLACK_TOKEN", _SLACK),
    "JWT": pattern("JWT", _JWT),
    "BEARER_TOKEN": _kept("BEARER_TOKEN", _BEARER, _is_not_plain_words),
    "PRIVATE_KEY": pattern("PRIVATE_KEY", _PEM),
    "URL_PASSWORD": _url_password,
    "EMAIL": _email,
    "CARD": _card,
}
