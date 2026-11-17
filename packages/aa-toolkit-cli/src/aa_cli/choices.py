"""Cheap command choices and option values, kept free of heavy imports."""

from collections.abc import Sequence
from enum import StrEnum


class Piece(StrEnum):
    CI = "ci"
    LOG = "log"


class CiPart(StrEnum):
    TESTS = "tests"
    ZIZMOR = "zizmor"
    AUDIT = "audit"
    DEPENDABOT = "dependabot"


class UnknownChoice(ValueError):
    """A name given to a flag that takes a list of names is not one of its choices."""

    def __init__(self, name: str, allowed: Sequence[str]) -> None:
        super().__init__(name)
        self.name = name
        self.allowed = allowed


def parse_choices(values: Sequence[str], allowed: Sequence[str]) -> list[str]:
    """The choices named in ``values``, case-insensitively, given with commas or repetition.

    Each name comes back spelled as in ``allowed``, in the order given.
    """
    by_key = {choice.upper(): choice for choice in allowed}
    parsed: list[str] = []
    for entry in values:
        for raw in entry.split(","):
            name = raw.strip()
            choice = by_key.get(name.upper())
            if choice is None:
                raise UnknownChoice(name, allowed)
            parsed.append(choice)
    return parsed


class License(StrEnum):
    MIT = "MIT"
    NONE = "none"


class Effect(StrEnum):
    READ = "read"
    WRITE = "write"


WITH_KINDS: tuple[str, ...] = ("IP_ADDRESS", "PHONE")
WITHOUT_KINDS: tuple[str, ...] = (
    "AWS_ACCESS_KEY",
    "GITHUB_TOKEN",
    "API_KEY",
    "SLACK_TOKEN",
    "JWT",
    "BEARER_TOKEN",
    "PRIVATE_KEY",
    "URL_PASSWORD",
    "EMAIL",
    "CARD",
)
