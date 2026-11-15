"""Secret store source and helpers backed by keyring."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import keyring
from keyring.backends import null as null_keyring
from keyring.errors import NoKeyringError, PasswordDeleteError
from pydantic import AliasChoices, AliasPath
from pydantic_settings import PydanticBaseSettingsSource

from aa_settings._errors import SettingsError, SettingsProblem
from aa_settings._secrets import is_secret_annotation

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo
    from pydantic_settings import BaseSettings as PydanticBaseSettings

MAX_SECRET_BYTES = 2560


class SecretStoreError(Exception):
    """Raised when the OS Secret store is unavailable or fails, with no Secret value."""

    def __init__(self, message: str, *, no_store: bool = False) -> None:
        super().__init__(message)
        self.no_store = no_store


def _alias_path(alias: object) -> tuple[str, ...] | None:
    if isinstance(alias, str):
        return (alias,)
    if isinstance(alias, AliasPath) and all(isinstance(part, str) for part in alias.path):
        return tuple(str(part) for part in alias.path)
    return None


def _validation_path(
    field: FieldInfo, field_name: str, config: Mapping[str, Any]
) -> tuple[str, ...]:
    """The key path pydantic expects when populating `field`."""
    if not config.get("validate_by_alias", True):
        return (field_name,)
    alias = field.validation_alias
    if isinstance(alias, AliasChoices):
        for choice in alias.choices:
            resolved = _alias_path(choice)
            if resolved is not None:
                return resolved
        return (field_name,)
    resolved = _alias_path(alias)
    return resolved if resolved is not None else (field_name,)


def _assign_path(data: dict[str, Any], path: tuple[str, ...], value: str) -> None:
    cursor = data
    for part in path[:-1]:
        nested = cursor.get(part)
        if not isinstance(nested, dict):
            nested = {}
            cursor[part] = nested
        cursor = nested
    cursor[path[-1]] = value


def _read_secret(app_name: str, field_name: str) -> tuple[str | None, SettingsProblem | None, bool]:
    """Read one Secret entry, returning `(value, problem, store_missing)`."""
    try:
        return keyring.get_password(app_name, field_name), None, False
    except NoKeyringError:
        return None, None, True
    except Exception as exc:
        message = f"could not read from Secret store ({type(exc).__name__})"
        return None, {"field": field_name, "type": "secret_store_error", "message": message}, False


class SecretStoreSettingsSource(PydanticBaseSettingsSource):
    """Read `Secret[...]` fields from the OS Secret store when `app_name` is configured."""

    def __init__(self, settings_cls: type[PydanticBaseSettings]) -> None:
        super().__init__(settings_cls)
        self.app_name = self.config.get("app_name")

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        path = _validation_path(field, field_name, self.config)
        if not self.app_name or not is_secret_annotation(field.annotation):
            return None, path[0], False
        value, problem, _ = _read_secret(self.app_name, field_name)
        if problem is not None:
            raise SettingsError(f"{problem['field']}: {problem['message']}", [problem])
        if value is None or len(path) == 1:
            return value, path[0], False
        nested: Any = value
        for part in reversed(path[1:]):
            nested = {part: nested}
        return nested, path[0], False

    def __call__(self) -> dict[str, Any]:
        if not self.app_name:
            return {}
        data: dict[str, Any] = {}
        problems: list[SettingsProblem] = []
        for field_name, field in self.settings_cls.model_fields.items():
            if not is_secret_annotation(field.annotation):
                continue
            value, problem, store_missing = _read_secret(self.app_name, field_name)
            if store_missing:
                return {}
            if problem is not None:
                problems.append(problem)
                continue
            if value is not None:
                _assign_path(data, _validation_path(field, field_name, self.config), value)
        if problems:
            lines = [f"{p['field']}: {p['message']}" for p in problems]
            raise SettingsError("\n".join(lines), problems)
        return data


def _require_store() -> None:
    if isinstance(keyring.get_keyring(), null_keyring.Keyring):
        raise SecretStoreError("No Secret store is available on this machine", no_store=True)


def _store_error(exc: Exception) -> SecretStoreError:
    if isinstance(exc, NoKeyringError):
        return SecretStoreError("No Secret store is available on this machine", no_store=True)
    return SecretStoreError(f"Secret store failed ({type(exc).__name__})", no_store=False)


def save_secret(app_name: str, name: str, value: str) -> bool:
    """Save a Secret in the OS Secret store and return whether it replaced an existing entry."""
    if not app_name:
        raise ValueError("app_name must not be empty")
    if not name:
        raise ValueError("name must not be empty")
    if not value:
        raise ValueError(
            f"Secret value must not be empty (0 bytes; limit is {MAX_SECRET_BYTES} UTF-16 bytes)"
        )
    size = len(value.encode("utf-16-le"))
    if size > MAX_SECRET_BYTES:
        raise ValueError(
            f"Secret value is {size} bytes in UTF-16, over the {MAX_SECRET_BYTES} byte limit"
        )

    _require_store()
    error: SecretStoreError | None = None
    replaced = False
    try:
        replaced = keyring.get_password(app_name, name) is not None
        keyring.set_password(app_name, name, value)
    except Exception as exc:
        error = _store_error(exc)
    if error is not None:
        raise error
    return replaced


def delete_secret(app_name: str, name: str) -> bool:
    """Remove a Secret from the OS Secret store and return whether one existed."""
    if not app_name:
        raise ValueError("app_name must not be empty")
    if not name:
        raise ValueError("name must not be empty")

    _require_store()
    error: SecretStoreError | None = None
    try:
        keyring.delete_password(app_name, name)
    except PasswordDeleteError:
        return False
    except Exception as exc:
        error = _store_error(exc)
    if error is not None:
        raise error
    return True
