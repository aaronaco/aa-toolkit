"""The aa command."""

import os
import sys
from collections.abc import Sequence
from importlib.metadata import version
from typing import Annotated, Any

import typer
from typer.core import TyperGroup

from aa_cli.output import ExitCode, Output


class AaGroup(TyperGroup):
    """Root group that applies the output contract to every invocation."""

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        out = Output.from_args(sys.argv[1:] if args is None else args, os.environ)
        try:
            code = super().main(
                args,
                prog_name,
                complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                obj=out,
                **extra,
            )
        except typer.TyperException as exc:
            # Typer gives every usage error (bad flag, missing argument) exit code 2.
            if exc.exit_code != ExitCode.USAGE:
                raise
            _report_usage_error(out, exc)
            code = ExitCode.USAGE
        sys.exit(code if isinstance(code, int) else ExitCode.OK)


def _report_usage_error(out: Output, exc: typer.TyperException) -> None:
    ctx = getattr(exc, "ctx", None)
    help_command = f"{ctx.command_path} --help" if ctx is not None else "aa --help"
    if out.json:
        out.failure("usage", exc.format_message(), fix=help_command)
    else:
        exc.show()  # type: ignore[attr-defined]  # usage errors carry Click's show()


app = typer.Typer(cls=AaGroup, add_completion=False, pretty_exceptions_enable=False)


def _show_version(ctx: typer.Context, value: bool) -> None:
    if value:
        current = version("aa-cli")
        ctx.obj.success({"version": current}, human=current)
        raise typer.Exit()


@app.callback()
def root(
    json_output: Annotated[
        bool, typer.Option("--json", help="Print one JSON object on stdout. Same as AA_JSON=1.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Log debug details to stderr.")] = False,
    show_version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Show the version and exit."),
    ] = False,
) -> None:
    """A personal developer toolkit."""
    # --json and --verbose are declared so the parser accepts them and --help
    # lists them; AaGroup.main reads them from the raw arguments.


def main() -> None:
    app()
