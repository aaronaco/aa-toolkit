"""Settings validation errors without raw input values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Literal,
    TypedDict,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import AliasChoices, AliasPath, BaseModel
from pydantic import Secret as PydanticSecret

if TYPE_CHECKING:
    from _typeshed import DataclassInstance
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


def _dedup_objects(items: list[object]) -> list[object]:
    result: list[object] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def _is_multi_branch_union(annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin is Annotated or (isinstance(origin, type) and issubclass(origin, PydanticSecret)):
        args = get_args(annotation)
        return _is_multi_branch_union(args[0]) if args else False
    if origin is Union or origin is UnionType:
        non_none = [arg for arg in get_args(annotation) if arg is not type(None)]
        return len(non_none) >= 2
    return False


def _expand_step_types(raw_types: list[object]) -> tuple[list[object], bool]:
    expanded: list[object] = []
    for item in raw_types:
        expanded.extend(_unwrap_types(item))
    in_union = any(_is_multi_branch_union(item) for item in raw_types)
    return _dedup_objects(expanded), in_union


def _match_alias_choice(choice: object, loc: tuple[int | str, ...], idx: int) -> int:
    if isinstance(choice, AliasPath):
        size = len(choice.path)
        if size > 0 and tuple(loc[idx : idx + size]) == tuple(choice.path):
            return size
        return 0
    return 1 if isinstance(loc[idx], str) and choice == loc[idx] else 0


def _field_alias_consume_len(
    field: FieldInfo,
    loc: tuple[int | str, ...],
    idx: int,
) -> int:
    val_alias = field.validation_alias
    if isinstance(val_alias, AliasChoices):
        for choice in val_alias.choices:
            if consumed := _match_alias_choice(choice, loc, idx):
                return consumed
        return 0
    if val_alias is not None:
        return _match_alias_choice(val_alias, loc, idx)
    return 1 if isinstance(loc[idx], str) and field.alias == loc[idx] else 0


def _lookup_field_step(
    model_cls: type[BaseModel],
    loc: tuple[int | str, ...],
    idx: int,
) -> tuple[str, FieldInfo, int] | None:
    part = loc[idx]
    if isinstance(part, str) and part in model_cls.model_fields:
        return part, model_cls.model_fields[part], 1
    for name, field in model_cls.model_fields.items():
        consumed = _field_alias_consume_len(field, loc, idx)
        if consumed > 0:
            return name, field, consumed
    return None


def _dataclass_field_type(dc_cls: type[object], field_name: str) -> object | None:
    dc_type = cast("type[DataclassInstance]", dc_cls)
    names = {field.name: field.type for field in dataclass_fields(dc_type)}
    if field_name not in names:
        return None
    try:
        hints = get_type_hints(dc_cls, include_extras=True)
    except NameError, TypeError:
        return names[field_name]
    return hints.get(field_name, names[field_name])


def _match_model_field(
    candidates: list[object],
    loc: tuple[int | str, ...],
    idx: int,
) -> tuple[int, list[object]] | None:
    part = loc[idx]
    for cand in candidates:
        if isinstance(cand, type) and issubclass(cand, BaseModel):
            found = _lookup_field_step(cand, loc, idx)
            if found is not None:
                return found[2], [found[1].annotation]
        if isinstance(cand, type) and is_dataclass(cand) and isinstance(part, str):
            dc_type = _dataclass_field_type(cand, part)
            if dc_type is not None:
                return 1, [dc_type]
    return None


def _model_has_literal_tag(model_cls: type[BaseModel], tag: str) -> bool:
    for field in model_cls.model_fields.values():
        for arg in _unwrap_types(field.annotation):
            if get_origin(arg) is Literal and tag in get_args(arg):
                return True
    return False


def _annotation_label(annotation: object) -> str:
    orig = get_origin(annotation) or annotation
    if orig is Annotated:
        args = get_args(annotation)
        return _annotation_label(args[0]) if args else str(annotation)
    if orig is Union or orig is UnionType:
        return " | ".join(_annotation_label(arg) for arg in get_args(annotation))
    if not isinstance(orig, type):
        return str(annotation)
    args = get_args(annotation)
    if not args:
        return orig.__name__
    if issubclass(orig, tuple) and len(args) == 2 and args[1] is Ellipsis:
        return f"tuple[{_annotation_label(args[0])}, ...]"
    return f"{orig.__name__}[{','.join(_annotation_label(arg) for arg in args)}]"


def _branch_matches_label(cand: object, label: str) -> bool:
    orig = get_origin(cand) or cand
    if isinstance(orig, type):
        type_prefix = label.split("[", 1)[0]
        if orig.__name__ == type_prefix:
            return True
        if issubclass(orig, BaseModel):
            return _model_has_literal_tag(orig, label)
    return False


def _select_union_branches(branches: list[object], label: int | str) -> list[object]:
    if not isinstance(label, str):
        return branches
    exact = [cand for cand in branches if _annotation_label(cand) == label]
    if exact:
        return exact
    matched = [cand for cand in branches if _branch_matches_label(cand, label)]
    return matched or branches


def _tuple_element_types(args: tuple[object, ...], index: int) -> list[object]:
    if len(args) == 2 and args[1] is Ellipsis:
        return [args[0]]
    if 0 <= index < len(args):
        return [args[index]]
    return []


def _sequence_candidate_elements(cand: object, orig: type[object], index: int) -> list[object]:
    args = get_args(cand)
    if issubclass(orig, tuple):
        return _tuple_element_types(args, index)
    return [args[0]] if args else []


def _match_sequence_element(candidates: list[object], index: int) -> list[object] | None:
    elem_candidates: list[object] = []
    matched = False
    for cand in candidates:
        orig = get_origin(cand) or cand
        if (
            isinstance(orig, type)
            and issubclass(orig, _SEQUENCE_ORIGINS)
            and not issubclass(orig, (str, bytes))
        ):
            matched = True
            elem_candidates.extend(_sequence_candidate_elements(cand, orig, index))
    return elem_candidates if matched else None


def _match_mapping_value(candidates: list[object]) -> list[object] | None:
    map_val_candidates: list[object] = []
    matched_mapping = False
    for cand in candidates:
        orig = get_origin(cand) or cand
        if isinstance(orig, type) and issubclass(orig, Mapping):
            matched_mapping = True
            args = get_args(cand)
            if len(args) >= 2:
                map_val_candidates.append(args[1])
    return map_val_candidates if matched_mapping else None


def _sanitize_loc_from_candidates(
    loc: tuple[int | str, ...],
    idx: int,
    candidates: list[object],
    *,
    in_union: bool = False,
) -> list[int | str]:
    if idx >= len(loc):
        return []
    part = loc[idx]

    if in_union:
        branches = _select_union_branches(candidates, part)
        return [part, *_sanitize_loc_from_candidates(loc, idx + 1, branches, in_union=False)]

    field_match = _match_model_field(candidates, loc, idx)
    if field_match is not None:
        consumed, raw_next = field_match
        next_candidates, next_union = _expand_step_types(raw_next)
        kept = list(loc[idx : idx + consumed])
        tail = _sanitize_loc_from_candidates(
            loc, idx + consumed, next_candidates, in_union=next_union
        )
        return [*kept, *tail]

    if isinstance(part, int):
        raw_elems = _match_sequence_element(candidates, part)
        if raw_elems is not None:
            elem_candidates, elem_union = _expand_step_types(raw_elems)
            tail = _sanitize_loc_from_candidates(loc, idx + 1, elem_candidates, in_union=elem_union)
            return [part, *tail]

    raw_maps = _match_mapping_value(candidates)
    if raw_maps is not None:
        map_candidates, map_union = _expand_step_types(raw_maps)
        next_idx = idx + 1
        if next_idx < len(loc) and loc[next_idx] == "[key]":
            next_idx += 1
        tail = _sanitize_loc_from_candidates(loc, next_idx, map_candidates, in_union=map_union)
        return ["[key]", *tail]

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
    idx = 0
    while idx < len(loc):
        step: tuple[str, FieldInfo, int] | None = None
        for cand in current_candidates:
            if isinstance(cand, type) and issubclass(cand, BaseModel):
                step = _lookup_field_step(cand, loc, idx)
                if step is not None:
                    break
        if step is None:
            return None
        name, field, consumed = step
        chain.append((name, field))
        current_candidates = _unwrap_types(field.annotation)
        idx += consumed
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


def _safe_non_missing_message(err_type: str, err: Mapping[str, object]) -> str:
    if err_type == "union_tag_invalid":
        ctx = err.get("ctx")
        if isinstance(ctx, Mapping):
            disc = ctx.get("discriminator")
            expected = ctx.get("expected_tags")
            if disc is not None and expected is not None:
                return (
                    f"Input tag found using {disc} does not match any of the expected tags: "
                    f"{expected}"
                )
        return "Invalid union tag"
    return str(err["msg"])


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
            message = _safe_non_missing_message(err_type, err)
        problems.append({"field": field, "type": err_type, "message": message})
    lines = [_format_problem_line(problem) for problem in problems]
    return SettingsError("\n".join(lines), problems)


def build_settings_error_from_source(exc: PydanticSettingsError) -> SettingsError:
    """Convert a pydantic-settings source parsing error into a SettingsError."""
    message = str(exc)
    problem: SettingsProblem = {"field": "", "type": "settings_error", "message": message}
    return SettingsError(message, [problem])
