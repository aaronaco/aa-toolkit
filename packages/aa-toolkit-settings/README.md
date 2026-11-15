# aa-toolkit-settings

Settings and Secrets for apps, on top of [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

An app describes its Settings as a typed class and loads them from values passed in code, environment variables, a `.env` file and defaults, in that order. A `Secret` prints and saves as `[REDACTED]` and reveals its real value only when code asks for it.

## Install

Install it from the toolkit's GitHub repo, pinned to a version tag:

```bash
uv add "aa-toolkit-settings @ git+https://github.com/aaronaco/aa-toolkit@settings-v0.1.0#subdirectory=packages/aa-toolkit-settings"
```

## Use

Subclass `BaseSettings`, list your Settings with their types, and call `Settings()`:

```python
import os

from aa_settings import BaseSettings

os.environ["DATABASE_URL"] = "postgres://db.internal/app"


class Settings(BaseSettings):
    database_url: str
    port: int = 8080


settings = Settings()
print(settings.database_url, settings.port)
```

That prints:

```text
postgres://db.internal/app 8080
```

Values are checked and converted to their field types when `Settings()` runs. Anything missing or wrong raises `SettingsError` (a `ValueError`) listing every problem at once, with no input values in its message or `.problems`:

```python
import os

from aa_settings import BaseSettings, SettingsError

os.environ.pop("DATABASE_URL", None)
os.environ["PORT"] = "not-a-port"


class Settings(BaseSettings):
    database_url: str
    port: int


try:
    Settings()
except SettingsError as err:
    print(err)
```

That prints:

```text
database_url: missing. Set DATABASE_URL in the environment or in .env
port: Input should be a valid integer, unable to parse string as an integer
```

A field path shows only names written in your Settings classes, so a dict key from the input shows as `[key]`, as in `tokens.[key]`. The one exception to "no input values" is your own validators: their messages are kept as written (see [What this library can't do](#what-this-library-cant-do)).

## Where values come from

Each Setting is taken from the first place that has it:

1. Values passed in code (`Settings(port=9000)`)
2. Environment variables (matching the field name in any case, with no prefix by default)
3. `.env` in the current folder (read as UTF-8; a missing `.env` or unknown keys in `.env` are ignored)
4. `secrets_dir` (off unless set in `model_config`)
5. The default on the class

```python
from contextlib import chdir
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from aa_settings import BaseSettings

os.environ["FROM_ENV"] = "env"

with TemporaryDirectory() as folder, chdir(folder):
    Path(".env").write_text("FROM_ENV=dotenv\nFROM_DOTENV=dotenv\n", encoding="utf-8")

    class Settings(BaseSettings):
        from_code: str = "default"
        from_env: str = "default"
        from_dotenv: str = "default"
        from_default: str = "default"

    settings = Settings(from_code="code")
    print(settings.from_code, settings.from_env, settings.from_dotenv, settings.from_default)
```

That prints:

```text
code env dotenv default
```

Override any default through `model_config = SettingsConfigDict(...)`, or change the source order by overriding `settings_customise_sources`.

## Secrets

Type a sensitive Setting as `Secret[T]`. It validates the inner type `T`, prints as `[REDACTED]`, uses `Secret('[REDACTED]')` for `repr()`, and serializes to `"[REDACTED]"` in JSON. Call `get_secret_value()` only where you need the real value:

```python
import os

from aa_settings import BaseSettings, Secret

os.environ["API_KEY"] = "sk-live-abc123"
os.environ["PIN"] = "4242"


class Settings(BaseSettings):
    api_key: Secret[str]
    pin: Secret[int]


settings = Settings()
print(settings)
print(settings.api_key)
print(settings.model_dump_json())
print(settings.pin.get_secret_value())
```

That prints:

```text
api_key=Secret('[REDACTED]') pin=Secret('[REDACTED]')
[REDACTED]
{"api_key":"[REDACTED]","pin":"[REDACTED]"}
4242
```

## Logging Settings with the log and redaction libraries

The Settings library never imports [`aa-toolkit-log`](../aa-toolkit-log/README.md) or [`aa-toolkit-redact`](../aa-toolkit-redact/README.md). An app connects them when it starts and passes `secret_values(settings)` to `known_values()` so Secrets stay hidden even if a real value from `get_secret_value()` ends up in another message, and passwords inside plain text Settings such as `database_url` are redacted too:

```python
import os

from aa_log import configure_logging, get_logger
from aa_redact import Redactor, known_values
from aa_settings import BaseSettings, Secret, secret_values

os.environ["DATABASE_URL"] = "postgres://app:hunter2@db.internal/app"
os.environ["API_KEY"] = "rawtokenwithoutprefix12345"


class Settings(BaseSettings):
    database_url: str
    api_key: Secret[str]


settings = Settings()
configure_logging(redact=Redactor(detectors=[known_values("SECRET", secret_values(settings))]))
log = get_logger(__name__)
log.info("started", extra={"settings": settings})
log.error("upstream rejected %s", settings.api_key.get_secret_value())
```

When stderr isn't a terminal, that writes:

```json
{"time": "2026-11-15T15:35:30.501+08:00", "level": "info", "logger": "__main__", "message": "started", "settings": "database_url='postgres://app:[URL_PASSWORD]@db.internal/app' api_key=[REDACTED]"}
{"time": "2026-11-15T15:35:30.503+08:00", "level": "error", "logger": "__main__", "message": "upstream rejected [SECRET]"}
```

## What this library can't do

- **Keep values hidden after `get_secret_value()`.** Once code calls `get_secret_value()`, it holds the plain value and must keep it out of logs, errors and files itself.
- **Hide passwords inside plain text Settings on its own.** A password inside a `str` Setting such as `postgres://app:hunter2@db.internal/app` is hidden only when the [redaction library](../aa-toolkit-redact/README.md) is attached.
- **Hide input values echoed inside custom validator exceptions.** A `@field_validator` or `@model_validator` keeps its raised exception message, so validator code must not include raw values in that text.
