"""What a Detector reports back."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Finding:
    """One place a Detector found a value: text[start:end], and what kind of value it is."""

    kind: str
    start: int
    end: int


type Detector = Callable[[str], Iterable[Finding]]

LONGEST_VALUE = 65536
"""The longest value a built-in Detector reads, as long as the text a Redactor reads, so a
long value is never cut short and its end left visible."""
