"""Settings for apps, on top of pydantic-settings."""

from aa_settings._errors import SettingsError
from aa_settings._secrets import Secret, secret_values
from aa_settings._settings import BaseSettings, SettingsConfigDict
from aa_settings._store import SecretStoreError, delete_secret, save_secret

__all__ = [
    "BaseSettings",
    "Secret",
    "SecretStoreError",
    "SettingsConfigDict",
    "SettingsError",
    "delete_secret",
    "save_secret",
    "secret_values",
]
