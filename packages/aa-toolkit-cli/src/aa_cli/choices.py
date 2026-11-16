"""Cheap command choices and option values, kept free of heavy imports."""

from enum import StrEnum


class Piece(StrEnum):
    CI = "ci"
    LOG = "log"


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
