"""Settings base class and SettingsConfigDict."""

from typing import Any, ClassVar

from pydantic import ValidationError
from pydantic_settings import BaseSettings as PydanticBaseSettings
from pydantic_settings import SettingsConfigDict as PydanticSettingsConfigDict
from pydantic_settings.exceptions import SettingsError as PydanticSettingsError

from aa_settings._errors import (
    SettingsError,
    build_settings_error_from_source,
    build_settings_error_from_validation,
)


class SettingsConfigDict(PydanticSettingsConfigDict, total=False):
    """Settings options for `BaseSettings` subclasses."""


class BaseSettings(PydanticBaseSettings):
    """Base class for app Settings loaded from code, environment, `.env`, and defaults."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    def __init__(
        self,
        **values: Any,  # noqa: ANN401  # mirrors pydantic_settings.BaseSettings.__init__
    ) -> None:
        error: SettingsError | None = None
        try:
            super().__init__(**values)
        except ValidationError as exc:
            config = type(self).model_config
            env_prefix = values.get("_env_prefix")
            if env_prefix is None:
                env_prefix = config.get("env_prefix", "")
            case_sensitive = values.get("_case_sensitive")
            if case_sensitive is None:
                case_sensitive = config.get("case_sensitive", False)
            env_nested_delimiter = values.get("_env_nested_delimiter")
            if env_nested_delimiter is None:
                env_nested_delimiter = config.get("env_nested_delimiter")
            error = build_settings_error_from_validation(
                exc,
                env_prefix=env_prefix,
                case_sensitive=bool(case_sensitive),
                env_nested_delimiter=env_nested_delimiter,
            )
        except PydanticSettingsError as exc:
            error = build_settings_error_from_source(exc)
        if error is not None:
            raise error
