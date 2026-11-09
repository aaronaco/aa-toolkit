"""Making Detectors, and the ones that come built in."""

import re
import unicodedata

from aa_redact._finding import Detector, Finding


def pattern(kind: str, regex: str) -> Detector:
    """Make a Detector that finds every match of a regular expression."""
    compiled = re.compile(regex)

    def detect(text: str) -> list[Finding]:
        return [Finding(kind, *match.span()) for match in compiled.finditer(text) if match[0]]

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


_MARK = _mark_ranges()
_LOCAL = rf"[\w{_MARK}.%+-]{{1,64}}"
_EMAIL = (
    # An apostrophe counts only inside a name, so the quotes around an email stay.
    rf"{_LOCAL}(?:(?<=\w)['’](?=\w){_LOCAL}){{0,3}}"
    rf"@(?:[\w{_MARK}-]{{1,63}}\.){{1,126}}"
    rf"(?:[xX][nN]--[A-Za-z0-9-]{{1,59}}|(?:[^\W\d_][{_MARK}]{{0,4}}){{2,24}})"
)

# Every repeat is bounded, so text written to be slow can't stall the app.
BUILT_IN: dict[str, Detector] = {
    "EMAIL": pattern("EMAIL", _EMAIL),
}
