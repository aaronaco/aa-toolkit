"""SettingsError on missing and invalid settings."""

import pytest

from aa_settings import BaseSettings, Secret, SettingsConfigDict, SettingsError


def test_missing_required_field_raises_settings_error_with_env_and_dotenv_hint(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)

    class Settings(BaseSettings):
        database_url: str

    with pytest.raises(SettingsError) as exc_info:
        Settings()

    err = exc_info.value
    assert isinstance(err, ValueError)
    assert err.__cause__ is None
    assert err.__context__ is None
    assert str(err) == "database_url: missing. Set DATABASE_URL in the environment or in .env"
    assert err.problems == [
        {
            "field": "database_url",
            "type": "missing",
            "message": "missing. Set DATABASE_URL in the environment or in .env",
        }
    ]


def test_invalid_secret_int_raises_settings_error_without_leaking_input(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PIN", "top-secret-not-a-number")

    class Settings(BaseSettings):
        pin: Secret[int]

    with pytest.raises(SettingsError) as exc_info:
        Settings()

    err = exc_info.value
    assert isinstance(err, ValueError)
    assert err.__cause__ is None
    assert err.__context__ is None
    assert "top-secret-not-a-number" not in str(err)
    assert "top-secret-not-a-number" not in repr(err.problems)
    assert len(err.problems) == 1
    assert err.problems[0]["field"] == "pin"
    assert err.problems[0]["type"] == "int_parsing"
    assert "integer" in err.problems[0]["message"].lower()


def test_multiple_problems_reported_together_one_line_each(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PORT", "wrong-port-value")

    class Settings(BaseSettings):
        database_url: str
        port: int
        api_key: Secret[str]

    with pytest.raises(SettingsError) as exc_info:
        Settings()

    err = exc_info.value
    lines = str(err).splitlines()
    assert len(lines) == 3
    assert lines[0] == "database_url: missing. Set DATABASE_URL in the environment or in .env"
    assert lines[1].startswith("port: ")
    assert "wrong-port-value" not in str(err)
    assert lines[2] == "api_key: missing. Set API_KEY in the environment or in .env"
    assert [p["field"] for p in err.problems] == ["database_url", "port", "api_key"]
    assert [p["type"] for p in err.problems] == ["missing", "int_parsing", "missing"]


def test_missing_field_hint_follows_prefix_and_case_settings(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    class PrefixedSettings(BaseSettings):
        model_config = SettingsConfigDict(env_prefix="my_app_")

        database_url: str

    class CaseSensitiveSettings(BaseSettings):
        model_config = SettingsConfigDict(env_prefix="app_", case_sensitive=True)

        database_url: str

    with pytest.raises(SettingsError) as prefixed_exc:
        PrefixedSettings()

    with pytest.raises(SettingsError) as sensitive_exc:
        CaseSensitiveSettings()

    assert (
        str(prefixed_exc.value)
        == "database_url: missing. Set MY_APP_DATABASE_URL in the environment or in .env"
    )
    assert (
        str(sensitive_exc.value)
        == "database_url: missing. Set app_database_url in the environment or in .env"
    )


def test_invalid_complex_env_value_raises_settings_error_with_no_cause_or_context(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PORTS", "secret-bad-json")

    class Settings(BaseSettings):
        ports: list[int]

    with pytest.raises(SettingsError) as exc_info:
        Settings()

    err = exc_info.value
    assert err.__cause__ is None
    assert err.__context__ is None
    assert "secret-bad-json" not in str(err)
    assert "secret-bad-json" not in repr(err.problems)


def test_dict_keys_are_redacted_from_error_locations(monkeypatch, tmp_path):
    import json

    from pydantic import BaseModel

    monkeypatch.chdir(tmp_path)

    class Endpoint(BaseModel):
        port: int

    class Settings(BaseSettings):
        tokens: dict[str, int]
        ports_by_int: dict[int, str]
        endpoints: dict[str, Endpoint]

    with pytest.raises(SettingsError) as exc_info:
        Settings(
            tokens={"sk-secret-key": "bad-val"},
            ports_by_int=json.loads('{"sk-bad-int-key": "ok"}'),
            endpoints={"sk-secret-host": {"port": "bad-port"}},
        )

    err = exc_info.value
    rendered = f"{err}\n{err.problems!r}"
    assert "sk-secret-key" not in rendered
    assert "sk-bad-int-key" not in rendered
    assert "sk-secret-host" not in rendered
    assert [p["field"] for p in err.problems] == [
        "tokens.[key]",
        "ports_by_int.[key]",
        "endpoints.[key].port",
    ]


def test_missing_field_hint_respects_alias_and_env_prefix_target(monkeypatch, tmp_path):
    from pydantic import AliasChoices, Field

    monkeypatch.chdir(tmp_path)

    class AliasDefaultSettings(BaseSettings):
        model_config = SettingsConfigDict(env_prefix="APP_")

        database_url: str = Field(validation_alias="CUSTOM_DB")

    class AliasPrefixedSettings(BaseSettings):
        model_config = SettingsConfigDict(env_prefix="APP_", env_prefix_target="alias")

        database_url: str = Field(validation_alias="CUSTOM_DB")

    class MultiAliasSettings(BaseSettings):
        model_config = SettingsConfigDict(env_prefix="APP_")

        database_url: str = Field(validation_alias=AliasChoices("DB_A", "DB_B"))

    with pytest.raises(SettingsError) as default_exc:
        AliasDefaultSettings()
    with pytest.raises(SettingsError) as prefixed_exc:
        AliasPrefixedSettings()
    with pytest.raises(SettingsError) as multi_exc:
        MultiAliasSettings()

    assert (
        str(default_exc.value) == "CUSTOM_DB: missing. Set CUSTOM_DB in the environment or in .env"
    )
    assert (
        str(prefixed_exc.value)
        == "CUSTOM_DB: missing. Set APP_CUSTOM_DB in the environment or in .env"
    )
    assert str(multi_exc.value) == "DB_A: missing"
