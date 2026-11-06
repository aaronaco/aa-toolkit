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

from aa_cli.init import (
    NAME_RULE,
    Kind,
    License,
    StepFailed,
    create_github_repo,
    create_project,
    is_empty_folder_or_missing,
    is_valid_name,
    outer_workspace_taking_in,
)
from aa_cli.output import (
    Aborted,
    ExitCode,
    JsonFlag,
    Output,
    VerboseFlag,
    configure_logging,
)

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
        except Aborted as exc:
            code = _report_aborted(out, exc)
        except Exception as exc:
            code = _report_unexpected_error(out, exc)
        sys.exit(code if isinstance(code, int) else ExitCode.OK)

    def invoke(self, ctx: typer.Context) -> Any:
        # Typer turns KeyboardInterrupt into a bare exit 130 with nothing on
        # stdout; catch it first so it is reported like any other failure.
        try:
            return super().invoke(ctx)
        except KeyboardInterrupt as exc:
            raise Aborted() from exc


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


def _report_aborted(out: Output, exc: Aborted) -> ExitCode:
    out.failure("aborted", str(exc))
    return ExitCode.ABORTED


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
def init(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The project name, also the folder it goes in.")],
    cli: Annotated[bool, typer.Option("--cli", help="Create a CLI project (the default).")] = False,
    lib: Annotated[bool, typer.Option("--lib", help="Create a typed library project.")] = False,
    license_choice: Annotated[
        License, typer.Option("--license", case_sensitive=False, help="The license to add.")
    ] = License.MIT,
    github: Annotated[
        bool, typer.Option("--github", help="Also create a private GitHub repo and push to it.")
    ] = False,
    public: Annotated[
        bool, typer.Option("--public", help="Make the GitHub repo public. Needs --github.")
    ] = False,
    json_output: JsonFlag = False,
    verbose: VerboseFlag = False,
) -> None:
    """Create a project in a new or empty folder."""
    out: Output = ctx.obj
    if cli and lib:
        raise typer.BadParameter("use only one of them", ctx=ctx, param_hint="'--cli' / '--lib'")
    if public and not github:
        raise typer.BadParameter("only works with '--github'", ctx=ctx, param_hint="'--public'")
    _refuse_bad_name(ctx, name)
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
    try:
        created = create_project(target, kind, license_choice)
        github_url = create_github_repo(target, public) if github else None
    except StepFailed as exc:
        out.failure("step_failed", str(exc), fix=exc.fix)
        raise typer.Exit(ExitCode.PROBLEMS) from exc
    except KeyboardInterrupt as exc:
        raise Aborted(f"Aborted; the folder {target} was left as it is") from exc
    data = {"path": str(target), "kind": str(kind), "files": created, "github_url": github_url}
    lines = [f"Created a {kind} project at {target}", *(f"  {f}" for f in created)]
    if github_url:
        lines.append(f"GitHub repo: {github_url}")
    out.success(data, human="\n".join(lines))


def _refuse_bad_name(ctx: typer.Context, name: str) -> None:
    """Refuse a name uv can't build a project from, before anything is written.

    ``.`` means the current folder, so its own name must follow the rule.
    """
    project_name = Path.cwd().name if name == "." else name
    if is_valid_name(project_name):
        return
    label = f"the current folder's name '{project_name}'" if name == "." else f"'{name}'"
    raise typer.BadParameter(f"{label} breaks the rule: {NAME_RULE}", ctx=ctx, param_hint="'NAME'")


@app.command(hidden=True)
def crash(json_output: JsonFlag = False, verbose: VerboseFlag = False) -> None:
    """Fail on purpose, to show how aa reports an unexpected error."""
    raise RuntimeError("aa crash was asked to fail")


def main() -> None:
    app()
