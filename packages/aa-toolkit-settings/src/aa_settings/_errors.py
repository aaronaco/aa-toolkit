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


def _alias_matches_key(alias_spec: object, key: str) -> bool:
    if alias_spec == key:
        return True
    if isinstance(alias_spec, AliasPath):
        return bool(alias_spec.path) and alias_spec.path[0] == key
    if isinstance(alias_spec, AliasChoices):
        return any(_alias_matches_key(choice, key) for choice in alias_spec.choices)
    return False


def _lookup_field(model_cls: type[BaseModel], key: int | str) -> tuple[str, FieldInfo] | None:
    if not isinstance(key, str):
        return None
    if key in model_cls.model_fields:
        return key, model_cls.model_fields[key]
    for name, field in model_cls.model_fields.items():
        if _alias_matches_key(field.validation_alias, key) or field.alias == key:
            return name, field
    return None


def _match_model_field(candidates: list[object], part: int | str) -> list[object] | None:
    for cand in candidates:
        if isinstance(cand, type) and issubclass(cand, BaseModel):
            found = _lookup_field(cand, part)
            if found is not None:
                return _unwrap_types(found[1].annotation)
    return None


def _tuple_element_types(args: tuple[object, ...], index: int) -> list[object]:
    if len(args) == 2 and args[1] is Ellipsis:
        return _unwrap_types(args[0])
    if 0 <= index < len(args):
        return _unwrap_types(args[index])
    return []


def _match_sequence_element(candidates: list[object], index: int) -> list[object] | None:
    for cand in candidates:
        orig = get_origin(cand) or cand
        if not (
            isinstance(orig, type)
            and issubclass(orig, _SEQUENCE_ORIGINS)
            and not issubclass(orig, (str, bytes))
        ):
            continue
        args = get_args(cand)
        if issubclass(orig, tuple):
            return _tuple_element_types(args, index)
        return _unwrap_types(args[0]) if args else []
    return None


def _match_mapping_value(candidates: list[object]) -> list[object] | None:
    map_val_candidates: list[object] = []
    matched_mapping = False
    for cand in candidates:
        orig = get_origin(cand) or cand
        if isinstance(orig, type) and issubclass(orig, Mapping):
            matched_mapping = True
            args = get_args(cand)
            if len(args) >= 2:
                map_val_candidates.extend(_unwrap_types(args[1]))
    return map_val_candidates if matched_mapping else None


def _sanitize_loc_from_candidates(
    loc: tuple[int | str, ...],
    idx: int,
    candidates: list[object],
) -> list[int | str]:
    if idx >= len(loc):
        return []
    part = loc[idx]

    next_candidates = _match_model_field(candidates, part)
    if next_candidates is not None:
        return [part, *_sanitize_loc_from_candidates(loc, idx + 1, next_candidates)]

    if isinstance(part, int):
        elem_candidates = _match_sequence_element(candidates, part)
        if elem_candidates is not None:
            return [part, *_sanitize_loc_from_candidates(loc, idx + 1, elem_candidates)]

    map_candidates = _match_mapping_value(candidates)
    if map_candidates is not None:
        next_idx = idx + 1
        if next_idx < len(loc) and loc[next_idx] == "[key]":
            next_idx += 1
        return ["[key]", *_sanitize_loc_from_candidates(loc, next_idx, map_candidates)]

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


def _resolve_env_parts(
    chain: list[tuple[str, FieldInfo]],
    env_prefix_target: str,
    validate_by_alias: bool,
) -> tuple[list[str], bool] | None:
    raw_parts: list[str] = []
    apply_prefix = env_prefix_target in ("variable", "all")
    for idx, (field_name, field) in enumerate(chain):
        alias_spec = field.validation_alias if field.validation_alias is not None else field.alias
        if validate_by_alias and isinstance(alias_spec, (AliasChoices, AliasPath)):
            return None
        use_alias = validate_by_alias and isinstance(alias_spec, str)
        raw_parts.append(str(alias_spec) if use_alias else field_name)
        if idx == 0:
            target = ("alias", "all") if use_alias else ("variable", "all")
            apply_prefix = env_prefix_target in target
    return raw_parts, apply_prefix


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
        if chain is None:
            return None
        resolved = _resolve_env_parts(chain, env_prefix_target, validate_by_alias)
        if resolved is None:
            return None
        raw_parts, apply_prefix = resolved

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
