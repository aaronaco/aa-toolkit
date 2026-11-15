"""Secret field type that always displays as [REDACTED]."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Secret as PydanticSecret
from pydantic import SecretBytes, SecretStr

if TYPE_CHECKING:
    from aa_settings._settings import BaseSettings


class Secret[T](PydanticSecret[T]):
    """A Secret value whose display text is always `[REDACTED]`."""

    def _display(self) -> str:
        return "[REDACTED]"


def secret_values(settings: BaseSettings) -> list[str]:
    """Return the real value of every populated Secret field on `settings` as text."""
    values: list[str] = []
    for name in type(settings).model_fields:
        field_value = getattr(settings, name)
        if not isinstance(field_value, (PydanticSecret, SecretStr, SecretBytes)):
            continue
        raw = field_value.get_secret_value()
        if raw is None:
            continue
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        if text:
            values.append(text)
    return values
