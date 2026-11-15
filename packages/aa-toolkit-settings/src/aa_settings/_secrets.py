"""Secret field type that always displays as [REDACTED]."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel, SecretBytes, SecretStr
from pydantic import Secret as PydanticSecret

if TYPE_CHECKING:
    from aa_settings._settings import BaseSettings


class Secret[T](PydanticSecret[T]):
    """A Secret value whose display text is always `[REDACTED]`."""

    def _display(self) -> str:
        return "[REDACTED]"


def _collect_secrets(value: object, values: list[str], seen: set[int]) -> None:
    if isinstance(value, (PydanticSecret, SecretStr, SecretBytes)):
        raw = value.get_secret_value()
        if raw is None:
            return
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        if text:
            values.append(text)
        return

    obj_id = id(value)
    if isinstance(value, BaseModel):
        if obj_id in seen:
            return
        seen.add(obj_id)
        for name in type(value).model_fields:
            _collect_secrets(getattr(value, name), values, seen)
        return

    if isinstance(value, Mapping):
        if obj_id in seen:
            return
        seen.add(obj_id)
        for item in value.values():
            _collect_secrets(item, values, seen)
        return

    if isinstance(value, (list, tuple, set, frozenset)):
        if obj_id in seen:
            return
        seen.add(obj_id)
        for item in value:
            _collect_secrets(item, values, seen)


def secret_values(settings: BaseSettings) -> list[str]:
    """Return the real value of every populated Secret field on `settings` as text."""
    values: list[str] = []
    _collect_secrets(settings, values, set())
    return values
