"""The output contract every aa command follows.

Human mode writes readable text. JSON mode writes exactly one envelope on
stdout: ``{"ok": true, "data": ...}`` on success and
``{"ok": false, "error": {"code", "message", "fix"}}`` on failure.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import typer


class ExitCode(IntEnum):
    OK = 0
    PROBLEMS = 1
    USAGE = 2
    UNEXPECTED = 3


@dataclass(frozen=True)
class Output:
    json: bool
    verbose: bool

    @classmethod
    def from_args(cls, args: Sequence[str], environ: Mapping[str, str]) -> "Output":
        """Read the global flags straight from the raw arguments.

        The flags are accepted before or after a subcommand, and they must
        still apply when parsing fails, so they are read before the parser runs.
        """
        flags = list(args)
        if "--" in flags:
            flags = flags[: flags.index("--")]
        return cls(
            json="--json" in flags or environ.get("AA_JSON") == "1",
            verbose="--verbose" in flags,
        )

    def success(self, data: dict[str, Any], human: str) -> None:
        if self.json:
            _write_json({"ok": True, "data": data})
        else:
            typer.echo(human)

    def failure(
        self,
        code: str,
        message: str,
        fix: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if self.json:
            envelope: dict[str, Any] = {
                "ok": False,
                "error": {"code": code, "message": message, "fix": fix},
            }
            if data is not None:
                envelope["data"] = data
            _write_json(envelope)
        else:
            typer.echo(f"Error: {message}", err=True)
            if fix:
                typer.echo(f"Fix: {fix}", err=True)


def _write_json(envelope: dict[str, Any]) -> None:
    typer.echo(json.dumps(envelope))
