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


def test_missing_nested_field_under_dict_key_omits_hint_and_redacts_key(monkeypatch, tmp_path):
    import json

    from pydantic import BaseModel

    monkeypatch.chdir(tmp_path)

    class Endpoint(BaseModel):
        port: int

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_nested_delimiter="__", case_sensitive=True)

        endpoints: dict[str, Endpoint]

    with pytest.raises(SettingsError) as exc_info:
        Settings(endpoints=json.loads('{"sk-secret-host": {}}'))

    err = exc_info.value
    rendered = f"{err}\n{err.problems!r}"
    assert "sk-secret-host" not in rendered
    assert str(err) == "endpoints.[key].port: missing"
    assert err.problems == [
        {"field": "endpoints.[key].port", "type": "missing", "message": "missing"}
    ]


def test_only_names_written_in_the_settings_types_appear_in_error_locations(monkeypatch, tmp_path):
    import json
    from dataclasses import dataclass
    from typing import Annotated, Literal

    from pydantic import AliasPath, BaseModel, Field

    monkeypatch.chdir(tmp_path)

    class Endpoint(BaseModel):
        port: int

    class TaggedMap(BaseModel):
        kind: Literal["map"]
        tokens: dict[str, int]

    class TaggedList(BaseModel):
        kind: Literal["list"]
        items: list[int]

    @dataclass
    class Credentials:
        tokens: dict[str, int]

    class Settings(BaseSettings):
        tokens: dict[str, int] = {}
        by_int: dict[int, str] = {}
        endpoints: dict[str, Endpoint] = {}
        items: list[Endpoint] = []
        pair: tuple[int, Endpoint] = (1, Endpoint(port=1))
        aliased: dict[str, int] = Field(default={}, validation_alias=AliasPath("payload", "tokens"))
        either: dict[str, int] | list[int] = []
        tagged: Annotated[TaggedMap | TaggedList, Field(discriminator="kind")] | None = None
        creds: Credentials | None = None

    payload = {
        "tokens": {"sk-1": "bad"},
        "by_int": {"sk-2": "x"},
        "endpoints": {"sk-3": {"port": "bad"}},
        "items": [{"port": "bad"}],
        "pair": [1, {"port": "bad"}],
        "payload": {"tokens": {"sk-4": "bad"}},
        "either": {"sk-5": "bad"},
        "tagged": {"kind": "map", "tokens": {"sk-6": "bad"}},
        "creds": {"tokens": {"sk-7": "bad"}},
    }

    with pytest.raises(SettingsError) as exc_info:
        Settings(**json.loads(json.dumps(payload)))

    err = exc_info.value
    assert "sk-" not in f"{err}\n{err.problems!r}"
    assert [p["field"] for p in err.problems] == [
        "tokens.[key]",
        "by_int.[key]",
        "endpoints.[key].port",
        "items.0.port",
        "pair.1.port",
        "payload.tokens.[key]",
        "either.[key]",
        "either.[key]",
        "tagged.map.tokens.[key]",
        "creds.tokens.[key]",
    ]


def test_invalid_discriminator_tag_is_not_repeated(monkeypatch, tmp_path):
    from typing import Annotated, Literal

    from pydantic import BaseModel, Field

    monkeypatch.chdir(tmp_path)

    class TaggedMap(BaseModel):
        kind: Literal["map"]

    class TaggedList(BaseModel):
        kind: Literal["list"]

    class Settings(BaseSettings):
        tagged: Annotated[TaggedMap | TaggedList, Field(discriminator="kind")]

    with pytest.raises(SettingsError) as exc_info:
        Settings(tagged={"kind": "sk-tag-secret"})

    err = exc_info.value
    assert str(err) == "tagged: Input tag does not match any of the expected tags: 'map', 'list'"
    assert "sk-tag-secret" not in repr(err.problems)


def test_missing_field_hints_for_nested_models_runtime_prefix_and_by_name(monkeypatch, tmp_path):
    import json

    from pydantic import AliasPath, BaseModel, Field

    monkeypatch.chdir(tmp_path)

    class Endpoint(BaseModel):
        port: int

    class NestedSettings(BaseSettings):
        model_config = SettingsConfigDict(env_prefix="APP_", env_nested_delimiter="__")

        db: Endpoint
        path_field: str = Field(validation_alias=AliasPath("nested", "key"))

    class ByNameSettings(BaseSettings):
        model_config = SettingsConfigDict(env_prefix="APP_", validate_by_alias=False)

        by_name_only: str = Field(validation_alias="IGNORED_ALIAS")

    class PlainSettings(BaseSettings):
        database_url: str

    with pytest.raises(SettingsError) as nested_exc:
        NestedSettings(db=json.loads("{}"))
    with pytest.raises(SettingsError) as by_name_exc:
        ByNameSettings()
    with pytest.raises(SettingsError) as runtime_exc:
        PlainSettings(_env_prefix="rt_")

    assert nested_exc.value.problems == [
        {
            "field": "db.port",
            "type": "missing",
            "message": "missing. Set APP_DB__PORT in the environment or in .env",
        },
        {"field": "nested.key", "type": "missing", "message": "missing"},
    ]
    assert (
        str(by_name_exc.value)
        == "by_name_only: missing. Set APP_BY_NAME_ONLY in the environment or in .env"
    )
    assert (
        str(runtime_exc.value)
        == "database_url: missing. Set RT_DATABASE_URL in the environment or in .env"
    )


def test_model_validator_error_has_no_field(monkeypatch, tmp_path):
    from typing import Self

    from pydantic import model_validator

    monkeypatch.chdir(tmp_path)

    class RootFailSettings(BaseSettings):
        value: int = 1

        @model_validator(mode="after")
        def check_root(self) -> Self:
            if self.value == 1:
                raise ValueError("invalid root combination")
            return self

    with pytest.raises(SettingsError) as exc_info:
        RootFailSettings()

    assert str(exc_info.value) == "Value error, invalid root combination"
    assert exc_info.value.problems[0]["field"] == ""
