"""Settings base class and SettingsConfigDict."""

from typing import Any, ClassVar, cast

from pydantic import ValidationError
from pydantic_settings import BaseSettings as PydanticBaseSettings
from pydantic_settings import PydanticBaseSettingsSource
from pydantic_settings import SettingsConfigDict as PydanticSettingsConfigDict
from pydantic_settings.exceptions import SettingsError as PydanticSettingsError

from aa_settings._errors import (
    SettingsError,
    build_settings_error_from_source,
    build_settings_error_from_validation,
)
from aa_settings._store import SecretStoreSettingsSource

# Options an app can also pass when creating Settings, as `Settings(_env_prefix="APP_")`.
_RUNTIME_OPTIONS = ("env_prefix", "env_prefix_target", "case_sensitive", "env_nested_delimiter")


class SettingsConfigDict(PydanticSettingsConfigDict, total=False):
    """Settings options for `BaseSettings` subclasses."""

    app_name: str | None


class BaseSettings(PydanticBaseSettings):
    """Base class for app Settings loaded from code, environment, `.env`, and defaults."""

    # Mirrors pydantic_settings.BaseSettings narrowing BaseModel.model_config.
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(  # ty: ignore[invalid-mutable-override]
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[PydanticBaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            SecretStoreSettingsSource(settings_cls),
            file_secret_settings,
        )

    def __init__(
        self,
        **values: Any,  # noqa: ANN401  # mirrors pydantic_settings.BaseSettings.__init__
    ) -> None:
        error: SettingsError | None = None
        try:
            super().__init__(**values)
        except ValidationError as exc:
            overrides = {
                key: values[f"_{key}"]
                for key in _RUNTIME_OPTIONS
                if values.get(f"_{key}") is not None
            }
            config = cast("SettingsConfigDict", {**type(self).model_config, **overrides})
            error = build_settings_error_from_validation(exc, type(self), config)
        except PydanticSettingsError as exc:
            error = build_settings_error_from_source(exc)
        except SettingsError as exc:
            error = exc
        # Raised here, outside the except blocks, so pydantic's error is neither
        # the cause nor the context and its input values stay out of tracebacks.
        if error is not None:
            raise error
