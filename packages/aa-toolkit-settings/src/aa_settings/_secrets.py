"""Secret field type that always displays as [REDACTED]."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from types import UnionType
from typing import TYPE_CHECKING, Annotated, Union, get_args, get_origin

from pydantic import BaseModel, SecretBytes, SecretStr
from pydantic import Secret as PydanticSecret

if TYPE_CHECKING:
    from aa_settings._settings import BaseSettings


class Secret[T](PydanticSecret[T]):
    """A Secret value whose display text is always `[REDACTED]`."""

    def _display(self) -> str:
        return "[REDACTED]"


def is_secret_annotation(annotation: object) -> bool:
    """Whether `annotation` is `Secret[...]` (or `Secret[...] | None`)."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return is_secret_annotation(get_args(annotation)[0])
    if origin is Union or origin is UnionType:
        branches = [arg for arg in get_args(annotation) if arg is not type(None)]
        return bool(branches) and all(is_secret_annotation(branch) for branch in branches)
    target = origin if origin is not None else annotation
    return isinstance(target, type) and issubclass(target, Secret)


def _extract_secret_text(secret: PydanticSecret[object] | SecretStr | SecretBytes) -> str:
    raw = secret.get_secret_value()
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)


def _iter_children(value: object) -> Iterable[object]:
    if isinstance(value, BaseModel):
        return (getattr(value, name) for name in type(value).model_fields)
    if is_dataclass(value) and not isinstance(value, type):
        return (getattr(value, field.name) for field in dataclass_fields(value))
    if isinstance(value, Mapping):
        return value.values()
    if isinstance(value, (list, tuple, set, frozenset)):
        return value
    return ()


def _collect_secrets(value: object, values: list[str], seen: set[int]) -> None:
    if isinstance(value, (PydanticSecret, SecretStr, SecretBytes)):
        text = _extract_secret_text(value)
        if text:
            values.append(text)
        return

    obj_id = id(value)
    if obj_id in seen:
        return
    seen.add(obj_id)

    for item in _iter_children(value):
        _collect_secrets(item, values, seen)


def secret_values(settings: BaseSettings) -> list[str]:
    """Return the real value of every populated Secret field on `settings` as text."""
    values: list[str] = []
    _collect_secrets(settings, values, set())
    return values
