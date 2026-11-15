"""Settings validation errors without raw input values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from types import UnionType
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict, Union, get_args, get_origin

from pydantic import AliasChoices, AliasPath, BaseModel

from aa_settings._secrets import is_secret_annotation

if TYPE_CHECKING:
    from pydantic import ValidationError
    from pydantic.fields import FieldInfo
    from pydantic_settings.exceptions import SettingsError as PydanticSettingsError

    from aa_settings._settings import SettingsConfigDict

KEY_PLACEHOLDER = "[key]"


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


def _alias_names(alias: object) -> set[str]:
    if isinstance(alias, str):
        return {alias}
    if isinstance(alias, AliasPath):
        return {part for part in alias.path if isinstance(part, str)}
    if isinstance(alias, AliasChoices):
        return {name for choice in alias.choices for name in _alias_names(choice)}
    return set()


def _own_fields(annotation: object) -> list[tuple[set[str], object]]:
    """The names and type of each field when `annotation` is a model or dataclass."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [
            (
                {name} | _alias_names(field.alias) | _alias_names(field.validation_alias),
                field.annotation,
            )
            for name, field in annotation.model_fields.items()
        ]
    if isinstance(annotation, type) and is_dataclass(annotation):
        return [({field.name}, field.type) for field in dataclass_fields(annotation)]
    return []


def _declared_names(settings_cls: type[BaseModel]) -> set[str]:
    """Every name written in the Settings types: fields, aliases and Literal values.

    These come from code, so they are safe to show. Anything else in an error
    location, such as a dict key, came from the input.
    """
    names: set[str] = set()
    seen: set[int] = set()
    pending: list[object] = [settings_cls]
    while pending:
        annotation = pending.pop()
        if id(annotation) in seen:
            continue
        seen.add(id(annotation))
        for field_names, field_type in _own_fields(annotation):
            names |= field_names
            pending.append(field_type)
        if get_origin(annotation) is Literal:
            names |= {arg for arg in get_args(annotation) if isinstance(arg, str)}
        pending.extend(get_args(annotation))
    return names


def _safe_location(loc: tuple[int | str, ...], declared: set[str]) -> str:
    parts: list[str] = []
    for part in loc:
        text = str(part) if isinstance(part, int) or part in declared else KEY_PLACEHOLDER
        if not (text == KEY_PLACEHOLDER and parts and parts[-1] == KEY_PLACEHOLDER):
            parts.append(text)
    return ".".join(parts)


def _single_model(annotation: object) -> type[BaseModel] | None:
    """The model class behind `Model`, `Model | None` or `Annotated[Model, ...]`, if any."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return _single_model(get_args(annotation)[0])
    if origin is Union or origin is UnionType:
        branches = [arg for arg in get_args(annotation) if arg is not type(None)]
        return _single_model(branches[0]) if len(branches) == 1 else None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _alias(field: FieldInfo) -> object:
    return field.validation_alias if field.validation_alias is not None else field.alias


def _find_field(model: type[BaseModel] | None, part: int | str) -> tuple[str, FieldInfo] | None:
    fields = model.model_fields.items() if model is not None else ()
    return next(((name, field) for name, field in fields if part in (name, _alias(field))), None)


def _env_name_part(name: str, field: FieldInfo, by_alias: bool) -> tuple[str, bool] | None:
    """The name pydantic-settings reads for one field, and whether it's an alias."""
    alias = _alias(field)
    if not by_alias or alias is None:
        return name, False
    return (alias, True) if isinstance(alias, str) else None


def _env_var_name(
    loc: tuple[int | str, ...],
    settings_cls: type[BaseModel],
    config: SettingsConfigDict,
) -> str | None:
    """The environment variable that sets the missing field, or None when unsure."""
    delimiter = config.get("env_nested_delimiter")
    if len(loc) > 1 and not delimiter:
        return None
    parts: list[tuple[str, bool]] = []
    model: type[BaseModel] | None = settings_cls
    for loc_part in loc:
        found = _find_field(model, loc_part)
        part = _env_name_part(*found, config.get("validate_by_alias", True)) if found else None
        if found is None or part is None:
            return None
        parts.append(part)
        model = _single_model(found[1].annotation)
    target = config.get("env_prefix_target", "variable")
    prefixed = target == "all" or target == ("alias" if parts[0][1] else "variable")
    prefix = config.get("env_prefix", "") if prefixed else ""
    full_name = prefix + (delimiter or "").join(name for name, _ in parts)
    return full_name if config.get("case_sensitive", False) else full_name.upper()


def _secret_store_field_name(
    loc: tuple[int | str, ...],
    settings_cls: type[BaseModel],
    config: SettingsConfigDict,
) -> str | None:
    """The Python field name when `loc` is a top-level Secret on a class with `app_name`."""
    if not config.get("app_name") or len(loc) != 1:
        return None
    part = loc[0]
    for name, field in settings_cls.model_fields.items():
        alias = _alias(field)
        matches_alias = part == alias or (
            isinstance(alias, AliasChoices) and part in _alias_names(alias)
        )
        if (part == name or matches_alias) and is_secret_annotation(field.annotation):
            return name
    return None


def _safe_message(
    err: Mapping[str, object],
    settings_cls: type[BaseModel],
    config: SettingsConfigDict,
) -> str:
    if err["type"] == "missing":
        loc = err["loc"]
        env_name = _env_var_name(loc, settings_cls, config) if isinstance(loc, tuple) else None
        secret_name = (
            _secret_store_field_name(loc, settings_cls, config) if isinstance(loc, tuple) else None
        )
        if env_name and secret_name:
            return (
                f"missing. Set {env_name} in the environment or in .env, "
                f"or run aa secret set {secret_name}"
            )
        if env_name:
            return f"missing. Set {env_name} in the environment or in .env"
        if secret_name:
            return f"missing. Run aa secret set {secret_name}"
        return "missing"
    if err["type"] == "union_tag_invalid":
        # pydantic's message repeats the tag from the input.
        ctx = err.get("ctx")
        expected = ctx.get("expected_tags") if isinstance(ctx, Mapping) else None
        return f"Input tag does not match any of the expected tags: {expected}"
    return str(err["msg"])


def build_settings_error_from_validation(
    exc: ValidationError,
    settings_cls: type[BaseModel],
    config: SettingsConfigDict,
) -> SettingsError:
    """Convert a pydantic ValidationError into a SettingsError with no input values."""
    declared = _declared_names(settings_cls)
    problems: list[SettingsProblem] = [
        {
            "field": _safe_location(err["loc"], declared),
            "type": err["type"],
            "message": _safe_message(err, settings_cls, config),
        }
        for err in exc.errors(include_url=False, include_input=False)
    ]
    lines = [f"{p['field']}: {p['message']}" if p["field"] else p["message"] for p in problems]
    return SettingsError("\n".join(lines), problems)


def build_settings_error_from_source(exc: PydanticSettingsError) -> SettingsError:
    """Convert a pydantic-settings source parsing error into a SettingsError."""
    message = str(exc)
    problem: SettingsProblem = {"field": "", "type": "settings_error", "message": message}
    return SettingsError(message, [problem])
