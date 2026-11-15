"""A small app that CI runs with only the Settings library installed."""

import os
from importlib.metadata import distributions

from aa_settings import BaseSettings, Secret

installed = {dist.name for dist in distributions()}
assert "aa-toolkit-settings" in installed, installed
assert "aa-toolkit-log" not in installed, installed
assert "aa-toolkit-redact" not in installed, installed
assert "aa-toolkit-cli" not in installed, installed

os.environ["DATABASE_URL"] = "postgres://db.internal/app"
os.environ["API_KEY"] = "sk-live-secret"


class Settings(BaseSettings):
    database_url: str
    api_key: Secret[str]


settings = Settings()
assert settings.database_url == "postgres://db.internal/app"
assert str(settings.api_key) == "[REDACTED]"
assert "sk-live-secret" not in str(settings)
print("ok")
