"""Loading Settings from code, environment variables, .env files, and defaults."""

from aa_settings import BaseSettings, SettingsConfigDict


def test_reads_field_from_uppercase_environment_variable(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgres://db.internal/app")

    class Settings(BaseSettings):
        database_url: str

    settings = Settings()

    assert settings.database_url == "postgres://db.internal/app"


def test_reads_field_from_lowercase_environment_variable(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("database_url", "postgres://db.internal/lower")

    class Settings(BaseSettings):
        database_url: str

    settings = Settings()

    assert settings.database_url == "postgres://db.internal/lower"


def test_reads_utf8_values_from_dotenv_when_environment_variable_is_unset(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        'DATABASE_URL=postgres://db.internal/app\nGREETING="café — 日本語"\n',
        encoding="utf-8",
    )

    class Settings(BaseSettings):
        database_url: str
        greeting: str

    settings = Settings()

    assert settings.database_url == "postgres://db.internal/app"
    assert settings.greeting == "café — 日本語"


def test_loads_from_environment_and_defaults_when_dotenv_is_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgres://db.internal/app")

    class Settings(BaseSettings):
        database_url: str
        port: int = 8080

    settings = Settings()

    assert settings.database_url == "postgres://db.internal/app"
    assert settings.port == 8080


def test_ignores_unknown_keys_in_dotenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgres://db.internal/app\nOTHER_TOOL_KEY=value\n",
        encoding="utf-8",
    )

    class Settings(BaseSettings):
        database_url: str

    settings = Settings()

    assert settings.database_url == "postgres://db.internal/app"


def test_source_precedence_code_then_env_then_dotenv_then_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "FROM_CODE=dotenv\nFROM_ENV=dotenv\nFROM_DOTENV=dotenv\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FROM_CODE", "env")
    monkeypatch.setenv("FROM_ENV", "env")

    class Settings(BaseSettings):
        from_code: str = "default"
        from_env: str = "default"
        from_dotenv: str = "default"
        from_default: str = "default"

    settings = Settings(from_code="code")

    assert settings.from_code == "code"
    assert settings.from_env == "env"
    assert settings.from_dotenv == "dotenv"
    assert settings.from_default == "default"


def test_subclass_can_override_model_config_while_keeping_other_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "APP_DATABASE_URL=postgres://db.internal/prefixed\nUNKNOWN=ignored\n",
        encoding="utf-8",
    )

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_prefix="APP_")

        database_url: str

    settings = Settings()

    assert settings.database_url == "postgres://db.internal/prefixed"


def test_subclass_can_customise_sources(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PORT", "9000")

    class Settings(BaseSettings):
        port: int = 8080

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls,
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        ):
            return (init_settings, dotenv_settings)

    settings = Settings()

    assert settings.port == 8080


def test_dotenv_beats_secrets_dir_which_beats_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "from_dotenv").write_text("secrets-dir", encoding="utf-8")
    (secrets / "from_secrets_dir").write_text("secrets-dir", encoding="utf-8")
    (tmp_path / ".env").write_text("FROM_DOTENV=dotenv\n", encoding="utf-8")

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(secrets_dir=secrets)

        from_dotenv: str = "default"
        from_secrets_dir: str = "default"
        from_default: str = "default"

    settings = Settings()

    assert settings.from_dotenv == "dotenv"
    assert settings.from_secrets_dir == "secrets-dir"
    assert settings.from_default == "default"
