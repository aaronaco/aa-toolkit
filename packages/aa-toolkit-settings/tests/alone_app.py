"""A small app that CI runs with only the Settings library installed."""

import os
from importlib.metadata import distributions

import keyring
from keyring.backends import fail

from aa_settings import BaseSettings, Secret, SecretStoreError, SettingsConfigDict, save_secret

installed = {dist.name for dist in distributions()}
assert "aa-toolkit-settings" in installed, installed
assert "keyring" in installed, installed
assert "aa-toolkit-log" not in installed, installed
assert "aa-toolkit-redact" not in installed, installed
assert "aa-toolkit-cli" not in installed, installed

keyring.set_keyring(fail.Keyring())
os.environ["DATABASE_URL"] = "postgres://db.internal/app"
os.environ["API_KEY"] = "sk-live-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(app_name="alone-app")

    database_url: str
    api_key: Secret[str]


settings = Settings()
assert settings.database_url == "postgres://db.internal/app"
assert str(settings.api_key) == "[REDACTED]"
assert "sk-live-secret" not in str(settings)

try:
    save_secret("alone-app", "api_key", "val")
except SecretStoreError as err:
    assert err.no_store is True
else:
    raise AssertionError("expected SecretStoreError")

print("ok")
