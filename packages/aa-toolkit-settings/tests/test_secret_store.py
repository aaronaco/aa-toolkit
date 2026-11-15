"""Reading, saving, and deleting Secrets in the Secret store."""

from __future__ import annotations

import sys

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from aa_settings import BaseSettings, Secret, SettingsConfigDict


class _MemoryKeyring(KeyringBackend):
    """In-memory keyring backend for testing without touching an OS Secret store."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.entries:
            raise PasswordDeleteError(f"{service}:{username}")
        del self.entries[(service, username)]


@pytest.fixture
def memory_keyring():
    previous = keyring.get_keyring()
    backend = _MemoryKeyring()
    keyring.set_keyring(backend)
    try:
        yield backend
    finally:
        keyring.set_keyring(previous)


def test_reads_secret_from_secret_store_when_app_name_is_set(
    memory_keyring, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    memory_keyring.set_password("my-app", "api_key", "sk-from-store")

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name="my-app")

        api_key: Secret[str]

    settings = Settings()

    assert settings.api_key.get_secret_value() == "sk-from-store"


def test_source_precedence_includes_secret_store_between_dotenv_and_secrets_dir(
    memory_keyring, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    for name in ("from_code", "from_env", "from_dotenv", "from_store", "from_secrets_dir"):
        (secrets_dir / name).write_text("secrets-dir", encoding="utf-8")
        memory_keyring.set_password("my-app", name, "store")

    (tmp_path / ".env").write_text(
        "FROM_CODE=dotenv\nFROM_ENV=dotenv\nFROM_DOTENV=dotenv\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FROM_CODE", "env")
    monkeypatch.setenv("FROM_ENV", "env")

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name="my-app", secrets_dir=secrets_dir)

        from_code: Secret[str] = Secret("default")
        from_env: Secret[str] = Secret("default")
        from_dotenv: Secret[str] = Secret("default")
        from_store: Secret[str] = Secret("default")
        from_secrets_dir: str = "default"
        from_default: Secret[str] = Secret("default")

    settings = Settings(from_code="code")

    assert settings.from_code.get_secret_value() == "code"
    assert settings.from_env.get_secret_value() == "env"
    assert settings.from_dotenv.get_secret_value() == "dotenv"
    assert settings.from_store.get_secret_value() == "store"
    assert settings.from_secrets_dir == "secrets-dir"
    assert settings.from_default.get_secret_value() == "default"


def test_secret_store_is_not_read_without_app_name(
    memory_keyring: _MemoryKeyring, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[str, str]] = []
    original_get = memory_keyring.get_password

    def spy_get(service: str, username: str) -> str | None:
        calls.append((service, username))
        return original_get(service, username)

    memory_keyring.get_password = spy_get
    memory_keyring.set_password("", "api_key", "should-not-read")
    monkeypatch.setenv("OTHER", "from-env")

    class Settings(BaseSettings):
        api_key: Secret[str] = Secret("default")
        other: str

    settings = Settings()

    assert calls == []
    assert settings.api_key.get_secret_value() == "default"
    assert settings.other == "from-env"


def test_plain_fields_and_non_library_secrets_are_not_read_from_secret_store(
    memory_keyring, monkeypatch, tmp_path
):
    from pydantic import Secret as PydanticSecret
    from pydantic import SecretStr

    monkeypatch.chdir(tmp_path)
    memory_keyring.set_password("my-app", "plain", "from-store")
    memory_keyring.set_password("my-app", "pydantic_secret", "from-store")
    memory_keyring.set_password("my-app", "pydantic_secret_str", "from-store")

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name="my-app")

        plain: str = "default"
        pydantic_secret: PydanticSecret[str] = PydanticSecret("default")
        pydantic_secret_str: SecretStr = SecretStr("default")

    settings = Settings()

    assert settings.plain == "default"
    assert settings.pydantic_secret.get_secret_value() == "default"
    assert settings.pydantic_secret_str.get_secret_value() == "default"


def test_optional_and_typed_secrets_are_read_from_secret_store(
    memory_keyring, monkeypatch, tmp_path
):
    from typing import Annotated, Optional

    monkeypatch.chdir(tmp_path)
    memory_keyring.set_password("my-app", "optional_key", "opt-val")
    memory_keyring.set_password("my-app", "legacy_optional", "legacy-val")
    memory_keyring.set_password("my-app", "annotated_optional", "ann-val")
    memory_keyring.set_password("my-app", "pin", "4242")

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name="my-app")

        optional_key: Secret[str] | None = None
        missing_optional: Secret[str] | None = None
        legacy_optional: Optional[Secret[str]] = None  # noqa: UP045
        annotated_optional: Annotated[Secret[str] | None, "meta"] = None
        pin: Secret[int]

    settings = Settings()

    assert settings.optional_key is not None
    assert settings.optional_key.get_secret_value() == "opt-val"
    assert settings.missing_optional is None
    assert settings.legacy_optional is not None
    assert settings.legacy_optional.get_secret_value() == "legacy-val"
    assert settings.annotated_optional is not None
    assert settings.annotated_optional.get_secret_value() == "ann-val"
    assert settings.pin.get_secret_value() == 4242


def test_secret_under_different_app_name_is_not_read(memory_keyring, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    memory_keyring.set_password("other-app", "api_key", "other-secret")

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name="my-app")

        api_key: Secret[str] | None = None

    settings = Settings()

    assert settings.api_key is None


def test_secret_entry_uses_field_name_not_alias_or_env_name(memory_keyring, monkeypatch, tmp_path):
    from pydantic import Field

    monkeypatch.chdir(tmp_path)
    memory_keyring.set_password("my-app", "api_key", "by-field-name")
    memory_keyring.set_password("my-app", "CUSTOM_KEY", "by-alias")
    memory_keyring.set_password("my-app", "APP_API_KEY", "by-env-name")

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name="my-app", env_prefix="APP_")

        api_key: Secret[str] = Field(validation_alias="CUSTOM_KEY")

    settings = Settings()

    assert settings.api_key.get_secret_value() == "by-field-name"


def test_loads_from_env_and_dotenv_without_error_when_machine_has_no_secret_store(
    monkeypatch, tmp_path
):
    from keyring.backends import fail, null

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DOTENV_SECRET=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("API_KEY", "from-env")

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name="my-app")

        api_key: Secret[str]
        dotenv_secret: Secret[str]
        optional_secret: Secret[str] | None = None

    previous = keyring.get_keyring()
    try:
        for backend in (fail.Keyring(), null.Keyring()):
            keyring.set_keyring(backend)
            settings = Settings()
            assert settings.api_key.get_secret_value() == "from-env"
            assert settings.dotenv_secret.get_secret_value() == "from-dotenv"
            assert settings.optional_secret is None
    finally:
        keyring.set_keyring(previous)


def test_secret_store_read_failure_raises_settings_error_naming_field_and_type_without_value(
    memory_keyring, monkeypatch, tmp_path
):
    from keyring.errors import KeyringError

    from aa_settings import SettingsError

    monkeypatch.chdir(tmp_path)

    def broken_get(service: str, username: str) -> str | None:
        raise KeyringError("top-secret-value-inside-backend-error")

    memory_keyring.get_password = broken_get

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name="my-app")

        api_key: Secret[str]

    with pytest.raises(SettingsError) as exc_info:
        Settings()

    err = exc_info.value
    assert isinstance(err, ValueError)
    assert err.__cause__ is None
    assert err.__context__ is None
    assert "api_key" in str(err)
    assert "KeyringError" in str(err)
    assert "top-secret-value-inside-backend-error" not in str(err)
    assert "top-secret-value-inside-backend-error" not in repr(err.problems)
    assert len(err.problems) == 1
    assert err.problems[0]["field"] == "api_key"


def test_invalid_secret_type_from_secret_store_raises_settings_error_without_value(
    memory_keyring, monkeypatch, tmp_path
):
    from aa_settings import SettingsError

    monkeypatch.chdir(tmp_path)
    memory_keyring.set_password("my-app", "pin", "top-secret-not-a-number")

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name="my-app")

        pin: Secret[int]

    with pytest.raises(SettingsError) as exc_info:
        Settings()

    err = exc_info.value
    assert "top-secret-not-a-number" not in str(err)
    assert "top-secret-not-a-number" not in repr(err.problems)
    assert err.problems[0]["field"] == "pin"
    assert err.problems[0]["type"] == "int_parsing"


def test_save_secret_saves_and_replaces_and_settings_reads_latest(
    memory_keyring, monkeypatch, tmp_path
):
    from aa_settings import save_secret

    monkeypatch.chdir(tmp_path)

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name="my-app")

        api_key: Secret[str]

    assert save_secret("my-app", "api_key", "first-value") is False
    assert Settings().api_key.get_secret_value() == "first-value"

    assert save_secret("my-app", "api_key", "second-value") is True
    assert Settings().api_key.get_secret_value() == "second-value"


def test_save_secret_allows_exact_2560_utf16_bytes_and_refuses_empty_or_larger(memory_keyring):
    from aa_settings import save_secret

    plain_1280 = "a" * 1280
    emoji_640 = "🔑" * 640
    assert save_secret("my-app", "plain_max", plain_1280) is False
    assert memory_keyring.get_password("my-app", "plain_max") == plain_1280
    assert save_secret("my-app", "emoji_max", emoji_640) is False
    assert memory_keyring.get_password("my-app", "emoji_max") == emoji_640

    too_long_plain = "x" * 1281
    with pytest.raises(ValueError) as plain_exc:
        save_secret("my-app", "too_long", too_long_plain)
    assert "2562" in str(plain_exc.value)
    assert "2560" in str(plain_exc.value)
    assert "x" * 10 not in str(plain_exc.value)

    too_long_emoji = "🔑" * 641
    with pytest.raises(ValueError) as emoji_exc:
        save_secret("my-app", "too_long_emoji", too_long_emoji)
    assert "2564" in str(emoji_exc.value)
    assert "2560" in str(emoji_exc.value)
    assert "🔑" not in str(emoji_exc.value)

    with pytest.raises(ValueError) as empty_exc:
        save_secret("my-app", "empty", "")
    assert "0" in str(empty_exc.value)
    assert "2560" in str(empty_exc.value)


def test_delete_secret_removes_entry_and_reports_whether_one_existed(
    memory_keyring, monkeypatch, tmp_path
):
    from aa_settings import delete_secret, save_secret

    monkeypatch.chdir(tmp_path)

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name="my-app")

        api_key: Secret[str] | None = None

    assert delete_secret("my-app", "api_key") is False
    save_secret("my-app", "api_key", "to-delete")
    assert Settings().api_key is not None

    assert delete_secret("my-app", "api_key") is True
    assert Settings().api_key is None
    assert delete_secret("my-app", "api_key") is False


def test_save_and_delete_secret_raise_secret_store_error_when_no_store_available():
    from keyring.backends import fail, null

    from aa_settings import SecretStoreError, delete_secret, save_secret

    previous = keyring.get_keyring()
    try:
        for backend in (fail.Keyring(), null.Keyring()):
            keyring.set_keyring(backend)
            with pytest.raises(SecretStoreError) as save_exc:
                save_secret("my-app", "api_key", "secret-val")
            assert save_exc.value.no_store is True
            assert "secret-val" not in str(save_exc.value)

            with pytest.raises(SecretStoreError) as del_exc:
                delete_secret("my-app", "api_key")
            assert del_exc.value.no_store is True
    finally:
        keyring.set_keyring(previous)


def test_save_and_delete_secret_raise_secret_store_error_without_value_on_backend_failure(
    memory_keyring,
):
    from keyring.errors import KeyringError

    from aa_settings import SecretStoreError, delete_secret, save_secret

    def broken_set(service: str, username: str, password: str) -> None:
        raise KeyringError(f"backend choked on {password}")

    def broken_delete(service: str, username: str) -> None:
        raise KeyringError("backend choked on secret-in-delete")

    memory_keyring.set_password = broken_set
    memory_keyring.delete_password = broken_delete

    with pytest.raises(SecretStoreError) as save_exc:
        save_secret("my-app", "api_key", "super-secret-value")
    assert save_exc.value.no_store is False
    assert save_exc.value.__cause__ is None
    assert save_exc.value.__context__ is None
    assert "super-secret-value" not in str(save_exc.value)

    with pytest.raises(SecretStoreError) as del_exc:
        delete_secret("my-app", "api_key")
    assert del_exc.value.no_store is False
    assert del_exc.value.__cause__ is None
    assert del_exc.value.__context__ is None
    assert "secret-in-delete" not in str(del_exc.value)


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Real Credential Manager test runs only on Windows",
)
def test_real_windows_credential_manager_round_trip(monkeypatch, tmp_path):
    import uuid

    from aa_settings import delete_secret, save_secret

    monkeypatch.chdir(tmp_path)
    app_name = f"aa-toolkit-test-{uuid.uuid4().hex}"

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name=app_name)

        api_key: Secret[str]
        emoji_key: Secret[str]

    max_plain = "a" * 1280
    max_emoji = "🔑" * 640
    try:
        assert save_secret(app_name, "api_key", "initial-win-secret") is False
        assert save_secret(app_name, "emoji_key", max_emoji) is False
        settings = Settings()
        assert settings.api_key.get_secret_value() == "initial-win-secret"
        assert settings.emoji_key.get_secret_value() == max_emoji

        assert save_secret(app_name, "api_key", max_plain) is True
        assert Settings().api_key.get_secret_value() == max_plain

        with pytest.raises(ValueError) as too_large:
            save_secret(app_name, "api_key", "x" * 1281)
        assert "2562" in str(too_large.value)
        assert "2560" in str(too_large.value)
    finally:
        deleted_api = delete_secret(app_name, "api_key")
        deleted_emoji = delete_secret(app_name, "emoji_key")

    assert deleted_api is True
    assert deleted_emoji is True
    assert delete_secret(app_name, "api_key") is False
    assert delete_secret(app_name, "emoji_key") is False
    assert keyring.get_password(app_name, "api_key") is None
    assert keyring.get_password(app_name, "emoji_key") is None
