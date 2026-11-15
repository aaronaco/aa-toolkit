"""Secret fields and secret_values helper."""

import json

from aa_settings import BaseSettings, Secret, secret_values


def test_secret_str_displays_redacted_and_keeps_real_value(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("API_KEY", "sk-live-secret-123")

    class Settings(BaseSettings):
        api_key: Secret[str]

    settings = Settings()

    assert str(settings.api_key) == "[REDACTED]"
    assert repr(settings.api_key) == "Secret('[REDACTED]')"
    assert json.loads(settings.model_dump_json()) == {"api_key": "[REDACTED]"}
    assert settings.model_dump() == {"api_key": settings.api_key}
    assert isinstance(settings.model_dump()["api_key"], Secret)
    assert settings.api_key.get_secret_value() == "sk-live-secret-123"


def test_secret_reads_from_dotenv_and_validates_inner_type(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("PIN=4242\n", encoding="utf-8")

    class Settings(BaseSettings):
        pin: Secret[int]

    settings = Settings()

    assert settings.pin.get_secret_value() == 4242
    assert str(settings.pin) == "[REDACTED]"


def test_printing_whole_settings_object_hides_every_secret_value(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("API_KEY", "sk-live-never-appear")
    monkeypatch.setenv("DB_PASSWORD", "hunter2-never-appear")

    class Settings(BaseSettings):
        database_url: str = "postgres://db.internal/app"
        api_key: Secret[str]
        db_password: Secret[str]
        optional_token: Secret[str] | None = None

    settings = Settings()

    rendered = f"{settings}\n{settings!r}"
    assert "sk-live-never-appear" not in rendered
    assert "hunter2-never-appear" not in rendered
    assert "[REDACTED]" in rendered
    assert "postgres://db.internal/app" in rendered


def test_secret_values_returns_text_for_populated_secrets_and_skips_empty_and_none(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)

    class Settings(BaseSettings):
        plain: str = "not-a-secret"
        api_key: Secret[str] = Secret("sk-123")
        pin: Secret[int] = Secret(9876)
        empty_secret: Secret[str] = Secret("")
        unset_optional: Secret[str] | None = None
        secret_none: Secret[str | None] = Secret(None)
        zero_pin: Secret[int] = Secret(0)

    settings = Settings()

    assert secret_values(settings) == ["sk-123", "9876", "0"]


def test_secret_values_collects_nested_models_and_containers(monkeypatch, tmp_path):
    from pydantic import BaseModel

    monkeypatch.chdir(tmp_path)

    class Database(BaseModel):
        dsn: Secret[str]
        optional_val: Secret[str | None] = Secret(None)
        empty: Secret[str] = Secret("")

    class Settings(BaseSettings):
        db: Database
        shared_db: Database
        tokens: list[Secret[str]]
        named: dict[str, Secret[str]]
        extra_pair: tuple[Secret[str], int]

    shared = Database(dsn="db-secret")
    settings = Settings(
        db=shared,
        shared_db=shared,
        tokens=[Secret("tok-1"), Secret("")],
        named={"primary": Secret("named-secret")},
        extra_pair=(Secret("tuple-secret"), 1),
    )

    assert secret_values(settings) == ["db-secret", "tok-1", "named-secret", "tuple-secret"]


def test_secret_values_collects_dataclass_fields(monkeypatch, tmp_path):
    from dataclasses import dataclass

    monkeypatch.chdir(tmp_path)

    @dataclass
    class ServiceAuth:
        api_key: Secret[str]
        nested_tokens: list[Secret[str]]
        plain: str = "visible"

    class Settings(BaseSettings):
        auth: ServiceAuth

    settings = Settings(
        auth=ServiceAuth(
            api_key=Secret("dc-api-secret"),
            nested_tokens=[Secret("dc-list-secret"), Secret("")],
        )
    )

    assert secret_values(settings) == ["dc-api-secret", "dc-list-secret"]
