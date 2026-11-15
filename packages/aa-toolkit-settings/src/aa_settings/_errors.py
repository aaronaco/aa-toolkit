"""Settings validation errors without raw input values."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from pydantic import ValidationError
    from pydantic_settings.exceptions import SettingsError as PydanticSettingsError


class SettingsProblem(TypedDict):
    """One validation problem on a Settings field, with no raw input value."""

    field: str
    type: str
    message: str


class SettingsError(ValueError):
    """Raised when Settings fail to load or validate, with no input values."""

    def __init__(self, message: str, problems: Sequence[SettingsProblem] = ()) -> None:
        super().__init__(message)
        self.problems: list[SettingsProblem] = [
            {"field": p["field"], "type": p["type"], "message": p["message"]} for p in problems
        ]


def _env_var_name(
    loc: tuple[int | str, ...],
    env_prefix: str,
    case_sensitive: bool,
    env_nested_delimiter: str | None,
) -> str | None:
    if len(loc) == 1:
        raw_name = str(loc[0])
    elif len(loc) > 1 and env_nested_delimiter:
        raw_name = env_nested_delimiter.join(str(part) for part in loc)
    else:
        return None
    full_name = f"{env_prefix}{raw_name}"
    return full_name if case_sensitive else full_name.upper()


def _format_problem_line(problem: SettingsProblem) -> str:
    if problem["field"]:
        return f"{problem['field']}: {problem['message']}"
    return problem["message"]


def build_settings_error_from_validation(
    exc: ValidationError,
    *,
    env_prefix: str = "",
    case_sensitive: bool = False,
    env_nested_delimiter: str | None = None,
) -> SettingsError:
    """Convert a pydantic ValidationError into a SettingsError with no input values."""
    problems: list[SettingsProblem] = []
    for err in exc.errors(include_url=False, include_input=False):
        loc = err["loc"]
        field = ".".join(str(part) for part in loc)
        err_type = err["type"]
        if err_type == "missing":
            env_name = _env_var_name(loc, env_prefix, case_sensitive, env_nested_delimiter)
            if env_name is not None:
                message = f"missing. Set {env_name} in the environment or in .env"
            else:
                message = "missing"
        else:
            message = err["msg"]
        problems.append({"field": field, "type": err_type, "message": message})
    lines = [_format_problem_line(problem) for problem in problems]
    return SettingsError("\n".join(lines), problems)


def build_settings_error_from_source(exc: PydanticSettingsError) -> SettingsError:
    """Convert a pydantic-settings source parsing error into a SettingsError."""
    message = str(exc)
    problem: SettingsProblem = {"field": "", "type": "settings_error", "message": message}
    return SettingsError(message, [problem])
