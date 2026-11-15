"""``aa commands``: machine-readable and human description of aa commands."""

import inspect
import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

import typer
from typer.core import TyperArgument, TyperGroup, TyperOption

from aa_cli.output import ExitCode


class Effect(StrEnum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class _TypeInfo:
    kind: str
    allows_none: bool = False
    items: str | None = None
    choices: list[str] | None = None


_SCALAR_TYPES: dict[object, str] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
}


def _scalar_kind(annotation: object) -> tuple[str, list[str] | None]:
    if annotation in _SCALAR_TYPES:
        return _SCALAR_TYPES[annotation], None
    if isinstance(annotation, type):
        if issubclass(annotation, StrEnum):
            return "string", [str(member.value) for member in annotation]
        if issubclass(annotation, Path):
            return "string", None
    raise TypeError(f"Unsupported parameter type annotation: {annotation!r}")


def _resolve_type(annotation: object) -> _TypeInfo:
    origin = get_origin(annotation)
    allows_none = False
    target = annotation
    if origin in (types.UnionType, Union):
        args = get_args(annotation)
        non_none = [arg for arg in args if arg is not type(None)]
        allows_none = len(non_none) < len(args)
        if len(non_none) != 1:
            raise TypeError(f"Unsupported union type annotation: {annotation!r}")
        target = non_none[0]
        origin = get_origin(target)
    if origin is list:
        item_args = get_args(target)
        item_kind, _ = _scalar_kind(item_args[0] if item_args else str)
        return _TypeInfo(kind="array", allows_none=allows_none, items=item_kind)
    kind, choices = _scalar_kind(target)
    return _TypeInfo(kind=kind, allows_none=allows_none, choices=choices)


def _callback_info(
    callback: Callable[..., object] | None,
) -> tuple[dict[str, Any], inspect.Signature]:
    if callback is None:
        return {}, inspect.Signature()
    return get_type_hints(callback), inspect.signature(callback)


def _param_details(
    param_name: str,
    required_by_parser: bool,
    hints: Mapping[str, Any],
    sig: inspect.Signature,
) -> tuple[_TypeInfo, bool, Any]:
    if param_name not in hints:
        raise TypeError(f"Missing type hint for parameter {param_name!r}")
    type_info = _resolve_type(hints[param_name])
    sig_param = sig.parameters[param_name]
    default = None if sig_param.default is inspect.Parameter.empty else sig_param.default
    if isinstance(default, StrEnum):
        default = str(default.value)
    required = (
        bool(required_by_parser)
        and not type_info.allows_none
        and sig_param.default is inspect.Parameter.empty
    )
    return type_info, required, default


def _describe_argument(
    param: TyperArgument, hints: Mapping[str, Any], sig: inspect.Signature
) -> dict[str, Any]:
    param_name = param.name or ""
    type_info, required, _ = _param_details(param_name, bool(param.required), hints, sig)
    entry: dict[str, Any] = {
        "name": param.metavar or param_name.upper(),
        "type": type_info.kind,
        "required": required,
        "help": param.help or "",
    }
    if type_info.items is not None:
        entry["items"] = type_info.items
    if type_info.choices is not None:
        entry["choices"] = type_info.choices
    return entry


def _describe_option(
    param: TyperOption, hints: Mapping[str, Any], sig: inspect.Signature
) -> dict[str, Any]:
    param_name = param.name or ""
    type_info, required, default = _param_details(param_name, bool(param.required), hints, sig)
    entry: dict[str, Any] = {
        "flag": param.opts[0],
        "type": type_info.kind,
    }
    if type_info.items is not None:
        entry["items"] = type_info.items
    entry.update(
        {
            "default": default,
            "choices": type_info.choices,
            "required": required,
            "repeatable": bool(param.multiple),
            "help": param.help or "",
        }
    )
    return entry


def describe_cli(app: typer.Typer, effects: Mapping[str, Effect]) -> dict[str, Any]:
    """Return the exit codes, global flags and visible commands of ``app``."""
    group = typer.main.get_command(app)
    if not isinstance(group, TyperGroup):
        raise TypeError(f"Expected root TyperGroup, got {type(group).__name__}")
    root_hints, root_sig = _callback_info(group.callback)
    global_options = [
        _describe_option(param, root_hints, root_sig)
        for param in group.params
        if isinstance(param, TyperOption) and not param.hidden
    ]
    global_flags = {opt["flag"] for opt in global_options}
    commands: list[dict[str, Any]] = []
    for name, cmd in group.commands.items():
        if cmd.hidden:
            continue
        if name not in effects:
            raise KeyError(f"Missing effect declaration for command {name!r}")
        cmd_hints, cmd_sig = _callback_info(cmd.callback)
        arguments = [
            _describe_argument(param, cmd_hints, cmd_sig)
            for param in cmd.params
            if isinstance(param, TyperArgument)
        ]
        options = [
            _describe_option(param, cmd_hints, cmd_sig)
            for param in cmd.params
            if isinstance(param, TyperOption)
            and not param.hidden
            and param.opts[0] not in global_flags
        ]
        summary = (cmd.help or "").splitlines()[0] if cmd.help else ""
        commands.append(
            {
                "name": name,
                "summary": summary,
                "effect": str(effects[name]),
                "arguments": arguments,
                "options": options,
            }
        )
    return {
        "exit_codes": [{"code": int(code), "meaning": code.meaning} for code in ExitCode],
        "global_options": global_options,
        "commands": commands,
    }


def format_commands(commands: Sequence[Mapping[str, Any]]) -> str:
    """Format visible commands and their summaries as a human-readable list."""
    if not commands:
        return ""
    width = max(len(str(cmd["name"])) for cmd in commands)
    return "\n".join(f"{cmd['name']:<{width}}  {cmd['summary']}" for cmd in commands)
