"""Making Detectors, and the ones that come built in."""

import re

from aa_redact._finding import Detector, Finding


def pattern(kind: str, regex: str) -> Detector:
    """Make a Detector that finds every match of a regular expression."""
    compiled = re.compile(regex)

    def detect(text: str) -> list[Finding]:
        return [Finding(kind, *match.span()) for match in compiled.finditer(text) if match[0]]

    return detect


# Every repeat is bounded, so text written to be slow can't stall the app.
BUILT_IN: dict[str, Detector] = {
    "EMAIL": pattern(
        "EMAIL",
        r"[\w.%+-]{1,64}@(?:[\w-]{1,63}\.){1,126}(?:[xX][nN]--[A-Za-z0-9-]{1,59}|[^\W\d_]{2,24})",
    ),
}
