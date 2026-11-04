"""The aa command."""

import contextlib
import io
import logging
import os
import re
import sys
from collections.abc import Iterator, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

import typer
from typer.core import TyperGroup

from aa_cli.doctor import Status, machine_checks, preflight_checks, project_checks, render
from aa_cli.init import (
    Kind,
    License,
    StepFailed,
    create_project,
    is_empty_folder_or_missing,
    outer_workspace_taking_in,
)
from aa_cli.output import ExitCode, JsonFlag, Output, VerboseFlag, configure_logging

log = logging.getLogger("aa")

# ANSI escape sequences: CSI (colors, styles) and OSC (hyperlinks).
_TERMINAL_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


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
        configure_logging(out.verbose)
        log.debug("aa %s on Python %s", version("aa-cli"), sys.version.split()[0])
        try:
            with _help_as_envelope(out):
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
                code = _report_unexpected_error(out, exc)
            else:
                code = _report_usage_error(out, exc)
        except Exception as exc:
            code = _report_unexpected_error(out, exc)
        sys.exit(code if isinstance(code, int) else ExitCode.OK)


@contextlib.contextmanager
def _help_as_envelope(out: Output) -> Iterator[None]:
    """In JSON mode, wrap the help text in a success envelope.

    Envelopes bypass the capture (see ``Output.stdout``), so only help text
    lands in it. Nothing captured means help was never shown, for example
    because an earlier ``--version`` already answered. If the command fails,
    the captured text is dropped and the error handlers write their own envelope.
    """
    if not (out.json and out.help):
        yield
        return
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        yield
    if not captured.getvalue():
        return
    # Typer colors help when FORCE_COLOR, PY_COLORS or GITHUB_ACTIONS is set, even
    # into a buffer; JSON consumers get plain text.
    plain = _TERMINAL_ESCAPE.sub("", captured.getvalue())
    text = "\n".join(line.rstrip() for line in plain.splitlines()).strip("\n")
    out.success({"help": text}, human="")


def _report_usage_error(out: Output, exc: typer.TyperException) -> ExitCode:
    ctx = getattr(exc, "ctx", None)
    help_command = f"{ctx.command_path} --help" if ctx is not None else "aa --help"
    if out.json:
        out.failure("usage", exc.format_message(), fix=help_command)
    else:
        exc.show()  # type: ignore[attr-defined]  # usage errors carry Click's show()
    return ExitCode.USAGE


def _report_unexpected_error(out: Output, exc: Exception) -> ExitCode:
    log.debug("Unexpected error", exc_info=exc)
    detail = str(exc).splitlines()[0] if str(exc) else ""
    message = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    out.failure("unexpected", message)
    return ExitCode.UNEXPECTED


app = typer.Typer(cls=AaGroup, add_completion=False, pretty_exceptions_enable=False)


def _show_version(ctx: typer.Context, value: bool) -> None:
    if value:
        current = version("aa-cli")
        ctx.obj.success({"version": current}, human=current)
        raise typer.Exit()


@app.callback()
def root(
    json_output: JsonFlag = False,
    verbose: VerboseFlag = False,
    show_version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """A personal developer toolkit."""
    # The global flags are declared so the parser accepts them and --help
    # lists them; AaGroup.main reads them from the raw arguments.


@app.command()
def doctor(ctx: typer.Context, json_output: JsonFlag = False, verbose: VerboseFlag = False) -> None:
    """Check the machine and the project, and show the fix for each problem."""
    out: Output = ctx.obj
    machine = machine_checks()
    uv = next(check for check in machine if check.id == "uv")
    checks = machine + project_checks(Path.cwd(), uv)
    data = {"checks": [check.to_json() for check in checks]}
    failed = [check for check in checks if check.status is Status.FAIL]
    if not failed:
        out.success(data, human=render(checks))
        return
    noun = "check" if len(failed) == 1 else "checks"
    message = f"{len(failed)} {noun} failed: {', '.join(check.id for check in failed)}"
    out.failure("checks_failed", message, data=data, human=render(checks))
    raise typer.Exit(ExitCode.PROBLEMS)


@app.command()
def init(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The project name, also the folder it goes in.")],
    cli: Annotated[bool, typer.Option("--cli", help="Create a CLI project (the default).")] = False,
    lib: Annotated[bool, typer.Option("--lib", help="Create a typed library project.")] = False,
    license_choice: Annotated[
        License, typer.Option("--license", case_sensitive=False, help="The license to add.")
    ] = License.MIT,
    json_output: JsonFlag = False,
    verbose: VerboseFlag = False,
) -> None:
    """Create a project in a new or empty folder."""
    out: Output = ctx.obj
    if cli and lib:
        raise typer.BadParameter("use only one of them", ctx=ctx, param_hint="'--cli' / '--lib'")
    kind = Kind.LIB if lib else Kind.CLI
    target = (Path.cwd() / name).resolve()
    if not is_empty_folder_or_missing(target):
        out.failure("target_not_empty", f"{target} already exists and is not an empty folder")
        raise typer.Exit(ExitCode.PROBLEMS)
    outer = outer_workspace_taking_in(target)
    if outer is not None:
        message = f"{target} would become a member of the uv workspace at {outer.root}"
        out.failure("target_in_workspace", message, fix=outer.fix)
        raise typer.Exit(ExitCode.PROBLEMS)
    failed = [check for check in preflight_checks() if check.status is Status.FAIL]
    if failed:
        message = f"preflight failed: {', '.join(check.id for check in failed)}"
        fix = "; ".join(dict.fromkeys(check.fix for check in failed if check.fix)) or None
        data = {"checks": [check.to_json() for check in failed]}
        out.failure("preflight_failed", message, fix=fix, data=data, human=render(failed))
        raise typer.Exit(ExitCode.PROBLEMS)
    try:
        created = create_project(target, kind, license_choice)
    except StepFailed as exc:
        out.failure("step_failed", str(exc))
        raise typer.Exit(ExitCode.PROBLEMS) from exc
    data = {"path": str(target), "kind": str(kind), "files": created, "github_url": None}
    human = "\n".join([f"Created a {kind} project at {target}", *(f"  {f}" for f in created)])
    out.success(data, human=human)


@app.command(hidden=True)
def crash(json_output: JsonFlag = False, verbose: VerboseFlag = False) -> None:
    """Fail on purpose, to show how aa reports an unexpected error."""
    raise RuntimeError("aa crash was asked to fail")


def main() -> None:
    app()
