"""Settings validation errors without raw input values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import UnionType
from typing import TYPE_CHECKING, Annotated, TypedDict, Union, get_args, get_origin

from pydantic import AliasChoices, AliasPath, BaseModel
from pydantic import Secret as PydanticSecret

if TYPE_CHECKING:
    from pydantic import ValidationError
    from pydantic.fields import FieldInfo
    from pydantic_settings.exceptions import SettingsError as PydanticSettingsError


_SEQUENCE_ORIGINS = (list, tuple, set, frozenset, Sequence)


def _unwrap_types(annotation: object) -> list[object]:
    if annotation is None or annotation is type(None):
        return []
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        return _unwrap_types(args[0]) if args else []
    if origin is Union or origin is UnionType:
        result: list[object] = []
        for arg in get_args(annotation):
            result.extend(_unwrap_types(arg))
        return result
    if isinstance(origin, type) and issubclass(origin, PydanticSecret):
        args = get_args(annotation)
        return _unwrap_types(args[0]) if args else []
    return [annotation]


def _lookup_field(model_cls: type[BaseModel], key: int | str) -> tuple[str, FieldInfo] | None:
    if not isinstance(key, str):
        return None
    if key in model_cls.model_fields:
        return key, model_cls.model_fields[key]
    for name, field in model_cls.model_fields.items():
        if field.validation_alias == key or field.alias == key:
            return name, field
        val_alias = field.validation_alias
        if isinstance(val_alias, AliasPath) and val_alias.path and val_alias.path[0] == key:
            return name, field
        if isinstance(val_alias, AliasChoices):
            for choice in val_alias.choices:
                if choice == key or (
                    isinstance(choice, AliasPath) and choice.path and choice.path[0] == key
                ):
                    return name, field
    return None


def _sanitize_loc_from_candidates(
    loc: tuple[int | str, ...],
    idx: int,
    candidates: list[object],
) -> list[int | str]:
    if idx >= len(loc):
        return []
    part = loc[idx]

    for cand in candidates:
        if isinstance(cand, type) and issubclass(cand, BaseModel):
            found = _lookup_field(cand, part)
            if found is not None:
                _, field = found
                return [
                    part,
                    *_sanitize_loc_from_candidates(loc, idx + 1, _unwrap_types(field.annotation)),
                ]

    if isinstance(part, int):
        seq_elem_candidates: list[object] = []
        for cand in candidates:
            orig = get_origin(cand) or cand
            if (
                isinstance(orig, type)
                and issubclass(orig, _SEQUENCE_ORIGINS)
                and not issubclass(orig, (str, bytes))
            ):
                args = get_args(cand)
                if issubclass(orig, tuple):
                    if len(args) == 2 and args[1] is Ellipsis:
                        seq_elem_candidates.extend(_unwrap_types(args[0]))
                    elif 0 <= part < len(args):
                        seq_elem_candidates.extend(_unwrap_types(args[part]))
                elif args:
                    seq_elem_candidates.extend(_unwrap_types(args[0]))
                return [part, *_sanitize_loc_from_candidates(loc, idx + 1, seq_elem_candidates)]

    map_val_candidates: list[object] = []
    matched_mapping = False
    for cand in candidates:
        orig = get_origin(cand) or cand
        if isinstance(orig, type) and issubclass(orig, Mapping):
            matched_mapping = True
            args = get_args(cand)
            if len(args) >= 2:
                map_val_candidates.extend(_unwrap_types(args[1]))
    if matched_mapping:
        next_idx = idx + 1
        if next_idx < len(loc) and loc[next_idx] == "[key]":
            next_idx += 1
        return ["[key]", *_sanitize_loc_from_candidates(loc, next_idx, map_val_candidates)]

    return list(loc[idx:])


def _sanitize_loc(
    loc: tuple[int | str, ...],
    settings_cls: type[BaseModel] | None,
) -> tuple[int | str, ...]:
    if settings_cls is None:
        return loc
    return tuple(_sanitize_loc_from_candidates(loc, 0, [settings_cls]))


class SettingsProblem(TypedDict):
    """One validation problem on a Settings field, with no raw input value."""

    field: str
    type: str
    message: str


class SettingsError(ValueError):
    """Raised when Settings fail to load or validate, with no input values."""

    def __init__(self, message: str, problems: Sequence[SettingsProblem] = ()) -> None:
        super().__init__(message)
        self.problems: list[SettingsProblem] = [
            {"field": p["field"], "type": p["type"], "message": p["message"]} for p in problems
        ]


def _resolve_field_chain(
    loc: tuple[int | str, ...],
    settings_cls: type[BaseModel],
) -> list[tuple[str, FieldInfo]] | None:
    current_candidates: list[object] = [settings_cls]
    chain: list[tuple[str, FieldInfo]] = []
    for part in loc:
        found: tuple[str, FieldInfo] | None = None
        for cand in current_candidates:
            if isinstance(cand, type) and issubclass(cand, BaseModel):
                found = _lookup_field(cand, part)
                if found is not None:
                    break
        if found is None:
            return None
        chain.append(found)
        current_candidates = _unwrap_types(found[1].annotation)
    return chain


def _env_var_name(
    loc: tuple[int | str, ...],
    env_prefix: str,
    case_sensitive: bool,
    env_nested_delimiter: str | None,
    *,
    settings_cls: type[BaseModel] | None = None,
    env_prefix_target: str = "variable",
    validate_by_alias: bool = True,
) -> str | None:
    if not loc or (len(loc) > 1 and not env_nested_delimiter):
        return None

    apply_prefix = env_prefix_target in ("variable", "all")
    raw_parts = [str(part) for part in loc]

    if settings_cls is not None:
        chain = _resolve_field_chain(loc, settings_cls)
        if chain is not None:
            raw_parts = []
            for idx, (field_name, field) in enumerate(chain):
                alias_spec = (
                    field.validation_alias if field.validation_alias is not None else field.alias
                )
                if validate_by_alias and isinstance(alias_spec, (AliasChoices, AliasPath)):
                    return None
                if validate_by_alias and isinstance(alias_spec, str):
                    raw_parts.append(alias_spec)
                    if idx == 0:
                        apply_prefix = env_prefix_target in ("alias", "all")
                else:
                    raw_parts.append(field_name)
                    if idx == 0:
                        apply_prefix = env_prefix_target in ("variable", "all")

    raw_name = raw_parts[0] if len(raw_parts) == 1 else (env_nested_delimiter or "").join(raw_parts)
    full_name = f"{env_prefix}{raw_name}" if apply_prefix else raw_name
    return full_name if case_sensitive else full_name.upper()


def _format_problem_line(problem: SettingsProblem) -> str:
    if problem["field"]:
        return f"{problem['field']}: {problem['message']}"
    return problem["message"]


def build_settings_error_from_validation(
    exc: ValidationError,
    *,
    env_prefix: str = "",
    case_sensitive: bool = False,
    env_nested_delimiter: str | None = None,
    settings_cls: type[BaseModel] | None = None,
    env_prefix_target: str = "variable",
    validate_by_alias: bool = True,
) -> SettingsError:
    """Convert a pydantic ValidationError into a SettingsError with no input values."""
    problems: list[SettingsProblem] = []
    for err in exc.errors(include_url=False, include_input=False):
        raw_loc = err["loc"]
        safe_loc = _sanitize_loc(raw_loc, settings_cls)
        field = ".".join(str(part) for part in safe_loc)
        err_type = err["type"]
        if err_type == "missing":
            env_name = _env_var_name(
                raw_loc,
                env_prefix,
                case_sensitive,
                env_nested_delimiter,
                settings_cls=settings_cls,
                env_prefix_target=env_prefix_target,
                validate_by_alias=validate_by_alias,
            )
            if env_name is not None:
                message = f"missing. Set {env_name} in the environment or in .env"
            else:
                message = "missing"
        else:
            message = err["msg"]
        problems.append({"field": field, "type": err_type, "message": message})
    lines = [_format_problem_line(problem) for problem in problems]
    return SettingsError("\n".join(lines), problems)


def build_settings_error_from_source(exc: PydanticSettingsError) -> SettingsError:
    """Convert a pydantic-settings source parsing error into a SettingsError."""
    message = str(exc)
    problem: SettingsProblem = {"field": "", "type": "settings_error", "message": message}
    return SettingsError(message, [problem])
