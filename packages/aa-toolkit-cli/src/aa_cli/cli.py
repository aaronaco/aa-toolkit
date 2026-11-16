"""The aa command."""

__lazy_modules__ = {
    "aa_cli.add",
    "aa_cli.commands",
    "aa_cli.crash",
    "aa_cli.init",
    "aa_cli.redact",
    "aa_cli.secret",
    "aa_settings",
    "io",
    "shlex",
}

import contextlib
import io
import logging
import os
import re
import shlex
import sys
from collections.abc import Callable, Generator, Sequence
from pathlib import Path
from typing import Annotated, Any

import typer
from typer.core import TyperGroup

from aa_cli.add import AddError, add_piece
from aa_cli.choices import WITH_KINDS, WITHOUT_KINDS, Effect, License, Piece
from aa_cli.commands import describe_cli, format_commands
from aa_cli.crash import REDACTION_FAILED, crash_folder, save_report
from aa_cli.init import (
    NAME_RULE,
    Kind,
    StepFailed,
    commit_and_push_to_github,
    create_project,
    is_empty_folder_or_missing,
    is_valid_name,
    outer_workspace_taking_in,
    plan_project,
)
from aa_cli.output import (
    Aborted,
    ExitCode,
    JsonFlag,
    Output,
    VerboseFlag,
    configure_logging,
)
from aa_cli.redact import (
    FileError,
    UnknownKind,
    build_redactor,
    check_file,
    clean_text,
    find_all,
    redact_file,
)
from aa_cli.secret import NotUtf8, field_name, project_name, read_piped_value
from aa_settings import SecretStoreError, delete_secret, save_secret

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
        **extra: Any,  # noqa: ANN401  # mirrors TyperGroup.main
    ) -> Any:  # noqa: ANN401  # mirrors TyperGroup.main
        raw_args = sys.argv[1:] if args is None else list(args)
        out = Output.from_args(raw_args, os.environ)
        command = self._command_name(raw_args)
        configure_logging(out.verbose)
        if log.isEnabledFor(logging.DEBUG):
            log.debug("aa %s on Python %s", _package_version(), sys.version.split()[0])
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
                code = _report_unexpected_error(out, exc, command)
            else:
                code = _report_usage_error(out, exc)
        except Aborted as exc:
            code = _report_aborted(out, exc)
        except Exception as exc:
            code = _report_unexpected_error(out, exc, command)
        sys.exit(code if isinstance(code, int) else ExitCode.OK)

    def _command_name(self, args: Sequence[str]) -> str | None:
        """The subcommand's name, never its arguments, for a Crash report.

        The root takes only flags, so the first word that isn't a flag names the subcommand.
        Anything that isn't a known command name gives None.
        """
        first = next((arg for arg in args if not arg.startswith("-")), None)
        return first if first in self.commands else None

    # TyperGroup.invoke takes a Context type that Typer doesn't export; typer.Context subclasses it.
    def invoke(self, ctx: typer.Context) -> Any:  # noqa: ANN401  # ty: ignore[invalid-method-override]
        # Typer turns KeyboardInterrupt into a bare exit 130 with nothing on
        # stdout; catch it first so it is reported like any other failure.
        try:
            return super().invoke(ctx)
        except KeyboardInterrupt as exc:
            raise Aborted() from exc


@contextlib.contextmanager
def _help_as_envelope(out: Output) -> Generator[None]:
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
        # Usage errors carry show(), but Typer exports no type that declares it.
        exc.show()  # ty: ignore[unresolved-attribute]
    return ExitCode.USAGE


def _report_aborted(out: Output, exc: Aborted) -> ExitCode:
    out.failure("aborted", str(exc))
    return ExitCode.ABORTED


def _report_unexpected_error(out: Output, exc: Exception, command: str | None) -> ExitCode:
    log.debug("Unexpected error", exc_info=exc)
    detail = str(exc).splitlines()[0] if str(exc) else ""
    message = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    redact = _default_redactor()
    out.failure(
        "unexpected",
        _redact_message(redact, message),
        fix=_save_crash_report(exc, command, message, redact),
    )
    return ExitCode.UNEXPECTED


def _default_redactor() -> Callable[[str], str]:
    """The Redactor ``aa redact`` uses with its default kinds, or one that hides everything."""
    try:
        return build_redactor()
    except Exception:
        log.debug("Could not build the Redactor", exc_info=True)
        return _redaction_failed


def _redaction_failed(text: str) -> str:
    return REDACTION_FAILED


def _redact_message(redact: Callable[[str], str], message: str) -> str:
    try:
        return redact(message)
    except Exception:
        log.debug("Could not redact the error message", exc_info=True)
        return REDACTION_FAILED


def _save_crash_report(
    exc: Exception, command: str | None, message: str, redact: Callable[[str], str]
) -> str | None:
    """Save a Crash report and say where it is, or give None when it can't be saved."""
    try:
        path = save_report(
            exc,
            folder=crash_folder("aa"),
            app="aa",
            version=_package_version(),
            command=command,
            message=message,
            redact=redact,
        )
    except Exception:
        log.debug("Could not save a crash report", exc_info=True)
        return None
    return f"Attach {path} to a bug report"


app = typer.Typer(cls=AaGroup, add_completion=False, pretty_exceptions_enable=False)


def _package_version() -> str:
    from importlib.metadata import version

    return version("aa-toolkit-cli")


def _show_version(ctx: typer.Context, value: bool) -> None:
    if value:
        current = _package_version()
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
def add(
    ctx: typer.Context,
    piece: Annotated[
        Piece,
        typer.Argument(help=f"The piece to add ({', '.join(Piece)})."),
    ],
    json_output: JsonFlag = False,
    verbose: VerboseFlag = False,
) -> None:
    """Add a piece to the project in the current folder."""
    out: Output = ctx.obj
    target = Path.cwd().resolve()
    try:
        added = add_piece(target, piece)
    except AddError as exc:
        out.failure(exc.code, str(exc), fix=exc.fix)
        raise typer.Exit(ExitCode.PROBLEMS) from exc
    except StepFailed as exc:
        out.failure("step_failed", str(exc), fix=exc.fix)
        raise typer.Exit(ExitCode.PROBLEMS) from exc
    data = {"piece": str(piece), "files": added.files, "next_steps": added.next_steps}
    if added.files:
        lines = [f"Added {piece} to {target}", *(f"  {f}" for f in added.files)]
    else:
        lines = [f"{piece} is already there in {target}"]
    if added.next_steps:
        lines.extend(["", "Next steps:", *(f"  {item}" for item in added.next_steps)])
    out.success(data, human="\n".join(lines))


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
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help=(
                "Show what would be created and run, without writing files or running setup"
                " commands (reads git config for MIT)."
            ),
        ),
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
    if dry_run:
        try:
            plan = plan_project(target, kind, license_choice, github=github, public=public)
        except StepFailed as exc:
            out.failure("step_failed", str(exc), fix=exc.fix)
            raise typer.Exit(ExitCode.PROBLEMS) from exc
        steps = [{"step": s.name, "command": list(s.command)} for s in plan.steps]
        data = {
            "dry_run": True,
            "path": str(target),
            "kind": str(kind),
            "files": plan.files,
            "github_url": None,
            "steps": steps,
        }
        lines = [
            f"Would create a {kind} project at {target}",
            *(f"  {f}" for f in plan.files),
            "Would run:",
            *(f"  {shlex.join(s['command'])}" for s in steps),
        ]
        out.success(data, human="\n".join(lines))
        return
    try:
        created = create_project(target, kind, license_choice)
        github_url = commit_and_push_to_github(target, public) if github else None
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


@app.command()
def redact(
    ctx: typer.Context,
    file: Annotated[
        Path | None,
        typer.Argument(metavar="FILE", help="The file to clean, or standard input when omitted."),
    ] = None,
    with_kinds: Annotated[
        list[str] | None,
        typer.Option(
            "--with",
            metavar="KIND",
            help=f"Also hide these off-by-default kinds: {', '.join(WITH_KINDS)}.",
        ),
    ] = None,
    without_kinds: Annotated[
        list[str] | None,
        typer.Option(
            "--without",
            metavar="KIND",
            help=f"Leave these built-in kinds visible: {', '.join(WITHOUT_KINDS)}.",
        ),
    ] = None,
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help="Report every Finding and exit 1 when any is found, without printing the text.",
        ),
    ] = False,
    json_output: JsonFlag = False,
    verbose: VerboseFlag = False,
) -> None:
    """Print a cleaned copy of a file or piped text."""
    out: Output = ctx.obj
    try:
        redactor = build_redactor(with_kinds or (), without_kinds or ())
    except UnknownKind as exc:
        raise typer.BadParameter(str(exc), ctx=ctx, param_hint=f"'{exc.flag}'") from exc
    if file is None and sys.stdin.isatty():
        raise typer.BadParameter(
            "give a file or pipe text in, e.g. 'aa redact app.log' or 'cmd | aa redact'",
            ctx=ctx,
            param_hint="'FILE'",
        )
    try:
        if check:
            if out.json:
                findings = find_all(file, redactor)
                out.success({"findings": findings}, human="")
                found = bool(findings)
            else:
                found = check_file(file, redactor)
            if found:
                raise typer.Exit(ExitCode.PROBLEMS)
        elif out.json:
            out.success({"text": clean_text(file, redactor)}, human="")
        else:
            redact_file(file, redactor)
    except FileError as exc:
        out.failure(exc.code, str(exc))
        raise typer.Exit(ExitCode.PROBLEMS) from exc


secret_app = typer.Typer(no_args_is_help=True)
app.add_typer(secret_app, name="secret")


@secret_app.callback()
def secret(json_output: JsonFlag = False, verbose: VerboseFlag = False) -> None:
    """Save or delete a Secret in the Secret store. No command prints one back."""


SecretName = Annotated[
    str,
    typer.Argument(
        metavar="NAME",
        help="The field name in the app's Settings class, such as api_key.",
        show_default=False,
    ),
]
AppOption = Annotated[
    str | None,
    typer.Option(
        "--app",
        help="The app name. Default: [project].name in pyproject.toml in the current folder.",
    ),
]


def _secret_target(ctx: typer.Context, name: str, app_name: str | None) -> tuple[str, str]:
    """Return the app name and the field name, or raise a usage error."""
    field = field_name(name)
    if field is None:
        # NAME isn't echoed: it may be a value given by mistake.
        raise typer.BadParameter(
            "not a name a Settings field can have, such as api_key", ctx=ctx, param_hint="'NAME'"
        )
    if app_name is not None:
        if not app_name:
            raise typer.BadParameter("must not be empty", ctx=ctx, param_hint="'--app'")
        return app_name, field
    found = project_name(Path.cwd())
    if found is None:
        raise typer.BadParameter(
            "give the app name, because no pyproject.toml here has a [project] name",
            ctx=ctx,
            param_hint="'--app'",
        )
    return found, field


_STDIN_HINT = "'standard input'"


def _secret_value(ctx: typer.Context, out: Output, name: str) -> str:
    """Read the value from a hidden prompt or from piped standard input."""
    if sys.stdin.isatty():
        if out.json:
            raise typer.BadParameter(
                "with --json, pipe the value in, e.g. 'cmd | aa secret set NAME --json'",
                ctx=ctx,
                param_hint=_STDIN_HINT,
            )
        try:
            value: str = typer.prompt(
                f"Value for {name}", default="", show_default=False, hide_input=True, err=True
            )
        except typer.Abort as exc:
            raise Aborted() from exc
    else:
        try:
            value = read_piped_value()
        except NotUtf8 as exc:
            raise typer.BadParameter(str(exc), ctx=ctx, param_hint=_STDIN_HINT) from None
    if not value:
        raise typer.BadParameter(
            "the value is empty, so nothing was saved", ctx=ctx, param_hint=_STDIN_HINT
        )
    return value


def _no_secret_store(out: Output, exc: SecretStoreError) -> typer.Exit:
    """Report a missing Secret store; any other store failure stays unexpected."""
    if not exc.no_store:
        raise exc
    out.failure("no_secret_store", str(exc))
    return typer.Exit(ExitCode.PROBLEMS)


@secret_app.command("set")
def secret_set(
    ctx: typer.Context,
    name: SecretName,
    app_name: AppOption = None,
    json_output: JsonFlag = False,
    verbose: VerboseFlag = False,
) -> None:
    """Save a Secret in the Secret store.

    The value comes from a hidden prompt, or from piped standard input without
    one trailing line ending. It's never an argument and never printed.
    """
    out: Output = ctx.obj
    target, name = _secret_target(ctx, name, app_name)
    value = _secret_value(ctx, out, name)
    try:
        replaced = save_secret(target, name, value)
    except SecretStoreError as exc:
        raise _no_secret_store(out, exc) from None
    except ValueError as exc:
        # NAME, the app name and the value are checked above, so only the size is left.
        out.failure("secret_too_large", str(exc))
        raise typer.Exit(ExitCode.PROBLEMS) from None
    verb = "Replaced" if replaced else "Saved"
    out.success(
        {"app": target, "name": name, "replaced": replaced},
        human=f"{verb} {name} for {target} in the Secret store.",
    )


@secret_app.command("delete")
def secret_delete(
    ctx: typer.Context,
    name: SecretName,
    app_name: AppOption = None,
    json_output: JsonFlag = False,
    verbose: VerboseFlag = False,
) -> None:
    """Delete a Secret from the Secret store."""
    out: Output = ctx.obj
    target, name = _secret_target(ctx, name, app_name)
    try:
        existed = delete_secret(target, name)
    except SecretStoreError as exc:
        raise _no_secret_store(out, exc) from None
    if not existed:
        out.failure("secret_not_found", f"No Secret {name} is saved for {target}; nothing changed")
        raise typer.Exit(ExitCode.PROBLEMS)
    out.success(
        {"app": target, "name": name},
        human=f"Deleted {name} for {target} from the Secret store.",
    )


COMMAND_EFFECTS: dict[str, Effect] = {
    "add": Effect.WRITE,
    "init": Effect.WRITE,
    "redact": Effect.READ,
    "commands": Effect.READ,
    "secret set": Effect.WRITE,
    "secret delete": Effect.WRITE,
}


@app.command()
def commands(
    ctx: typer.Context,
    json_output: JsonFlag = False,
    verbose: VerboseFlag = False,
) -> None:
    """List every command, its arguments, flags and exit codes."""
    out: Output = ctx.obj
    data = describe_cli(app, COMMAND_EFFECTS)
    out.success(data, human=format_commands(data["commands"]))


@app.command(hidden=True)
def crash(json_output: JsonFlag = False, verbose: VerboseFlag = False) -> None:
    """Fail on purpose, to show how aa reports an unexpected error."""
    raise RuntimeError("aa crash was asked to fail")


def main() -> None:
    app()
