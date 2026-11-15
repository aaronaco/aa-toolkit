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


type _Path = tuple[str | int, ...]


def _alias_path(alias: object) -> _Path | None:
    if isinstance(alias, str):
        return (alias,)
    if isinstance(alias, AliasPath) and alias.path and isinstance(alias.path[0], str):
        return tuple(alias.path)
    return None


def _validate_by_name(config: Mapping[str, Any]) -> bool:
    """Resolve `validate_by_name` the way pydantic does, including `populate_by_name`."""
    for key in ("validate_by_name", "populate_by_name"):
        value = config.get(key)
        if value is not None:
            return bool(value)
    return config.get("validate_by_alias") is False


def _accepted_paths(field: FieldInfo, field_name: str, config: Mapping[str, Any]) -> list[_Path]:
    """Every key path pydantic accepts for `field`, in the order it tries them."""
    paths: list[_Path] = []
    alias = field.validation_alias
    if alias is not None and config.get("validate_by_alias") is not False:
        choices = alias.choices if isinstance(alias, AliasChoices) else [alias]
        paths = [path for path in map(_alias_path, choices) if path is not None]
    if not paths or _validate_by_name(config):
        paths.append((field_name,))
    return paths


def _validation_path(field: FieldInfo, field_name: str, config: Mapping[str, Any]) -> _Path:
    """The key path pydantic expects when populating `field`."""
    return _accepted_paths(field, field_name, config)[0]


def _has_path(data: object, path: _Path) -> bool:
    for part in path:
        if isinstance(part, str) and isinstance(data, dict) and part in data:
            data = data[part]
        elif isinstance(part, int) and isinstance(data, list) and -len(data) <= part < len(data):
            data = data[part]
        else:
            return False
    return True


def _nest(path: _Path, value: str) -> object:
    """Wrap `value` so it sits at `path` below its first key."""
    nested: object = value
    for part in reversed(path[1:]):
        if isinstance(part, int):
            items: list[object] = [None] * (part + 1 if part >= 0 else -part)
            items[part] = nested
            nested = items
        else:
            nested = {part: nested}
    return nested


def _merge(data: dict[str, Any], key: str, value: object) -> None:
    current = data.get(key)
    if isinstance(current, dict) and isinstance(value, dict):
        for sub_key, sub_value in value.items():
            _merge(current, sub_key, sub_value)
    else:
        data[key] = value


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
            return None, str(path[0]), False
        value, problem, _ = _read_secret(self.app_name, field_name)
        if problem is not None:
            raise SettingsError(f"{problem['field']}: {problem['message']}", [problem])
        return (None if value is None else _nest(path, value)), str(path[0]), False

    def __call__(self) -> dict[str, Any]:
        if not self.app_name:
            return {}
        data: dict[str, Any] = {}
        problems: list[SettingsProblem] = []
        for field_name, field in self.settings_cls.model_fields.items():
            if not is_secret_annotation(field.annotation):
                continue
            paths = _accepted_paths(field, field_name, self.config)
            if any(_has_path(self.current_state, path) for path in paths):
                # A source with higher priority already set this field.
                continue
            value, problem, store_missing = _read_secret(self.app_name, field_name)
            if store_missing:
                return {}
            if problem is not None:
                problems.append(problem)
                continue
            if value is not None:
                _merge(data, str(paths[0][0]), _nest(paths[0], value))
        if problems:
            lines = [f"{p['field']}: {p['message']}" for p in problems]
            raise SettingsError("\n".join(lines), problems)
        return data


def _require_store() -> None:
    error: SecretStoreError | None = None
    backend: object = None
    try:
        backend = keyring.get_keyring()
    except Exception as exc:
        error = _store_error(exc)
    if error is not None:
        raise error
    if isinstance(backend, null_keyring.Keyring):
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
    existed = True
    try:
        keyring.delete_password(app_name, name)
    except PasswordDeleteError:
        existed = False
    except Exception as exc:
        error = _store_error(exc)
    if not existed:
        # Some backends raise PasswordDeleteError for failures other than a missing
        # entry, so only report "not there" once a read confirms it.
        try:
            if keyring.get_password(app_name, name) is not None:
                error = SecretStoreError("Secret store failed (PasswordDeleteError)")
        except Exception as exc:
            error = _store_error(exc)
    if error is not None:
        raise error
    return existed
