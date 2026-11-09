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
