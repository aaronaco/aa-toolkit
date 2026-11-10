# aa-toolkit-log

Ready-made logging for apps, on top of Python's built-in logging. It has no dependencies.

An app gets clean, lined-up columns in a terminal and JSON lines when a tool or an agent runs it, and it can save its logs to a file that can't fill the disk.

## Install

Install it from the toolkit's GitHub repo, pinned to a version tag:

```bash
uv add "aa-toolkit-log @ git+https://github.com/aaronaco/aa-toolkit@log-v0.1.0#subdirectory=packages/aa-toolkit-log"
```

## Use

Call `configure_logging()` once when the app starts. Every file gets its logger from `get_logger(__name__)` and logs with the usual methods, because it's a standard Python logger.

```python
from aa_log import configure_logging, get_logger

log = get_logger(__name__)


def main() -> None:
    configure_logging()
    log.info("fetched", extra={"url": "https://example.com", "code": 200})
```

In a terminal that prints:

```text
14:03:21  INFO   __main__                  fetched url=https://example.com code=200
```

When stderr isn't a terminal, it prints:

```json
{"time": "2026-11-09T14:03:21.482+08:00", "level": "info", "logger": "__main__", "message": "fetched", "url": "https://example.com", "code": 200}
```

Logs go to stderr, so stdout stays free for the app's own output. Logs from installed packages appear in the same format. Calling `configure_logging()` again replaces the earlier settings, and handlers it didn't add stay attached. If you never call it, Python's normal behavior applies, and warnings and errors still show.

Only an app calls `configure_logging()`. A library should log through Python's `logging` and leave the setup to the app.

### Arguments

`configure_logging(level=..., file=..., redact=...)` takes three optional arguments:

- `level`: the lowest level to show, as a name like `"DEBUG"` or a number like `logging.DEBUG`. The default is `INFO`.
- `file`: a path to save logs to. A relative path is relative to the current folder. By default no file is written.
- `redact`: a function that cleans every log line before it's written, see [Hiding secrets](#hiding-secrets). By default nothing is cleaned.

### Environment variables

A variable that is set wins over the matching argument. An empty one counts as not set.

| Variable | Values | What it does |
|---|---|---|
| `AA_LOG_LEVEL` | `DEBUG`, `INFO`, `WARN`, `ERROR`, `CRIT` | Sets the lowest level to show. |
| `AA_LOG_FORMAT` | `text`, `json` | Forces the style on screen. Without it, a terminal gets `text` and anything else gets `json`. |
| `AA_LOG_FILE` | a path | Saves logs to that file. |

A bad `AA_LOG_LEVEL` gives a warning and the `level` argument is used, which is `INFO` unless the app passes another level. A bad `AA_LOG_FORMAT` gives a warning and the style is chosen as if it weren't set. A log file that can't be opened gives a warning and logs stay on screen. Neither stops the app.

## Saving to a file

The file always holds JSON lines in UTF-8, with the same messages as the screen. Its folder is created when it's missing. At 10 MB a new file starts and the last 3 old ones are kept. Only one copy of an app should write to a log file at a time: on Windows, starting a new file can fail when two copies share one, and some lines can be lost.

Add `*.log` and `*.log.[1-3]` to your `.gitignore`, so a log file and its old copies aren't committed by accident.

## Hiding secrets

By default, logs don't hide secrets: whatever you log is shown on screen and saved to the file as it is. The best fix is not to log passwords, tokens or keys at all. For the ones you don't see coming, such as a token in an error message from another package, pass a function as `redact`.

The redaction library, [`aa-toolkit-redact`](../aa-toolkit-redact/README.md), gives you one. Install it as its README shows, then pass a `Redactor`:

```python
from aa_log import configure_logging, get_logger
from aa_redact import Redactor

log = get_logger(__name__)


def main() -> None:
    configure_logging(redact=Redactor())
    log.info("signed up %s", "ann@example.com", extra={"password": "hunter2"})
```

That prints:

```text
14:03:21  INFO   __main__                  signed up [EMAIL] password=[REDACTED]
```

Every line is cleaned the same way on screen and in the file: the message after its values are filled in, tracebacks, stack information and every `extra` value. Logs from installed packages are cleaned too. The time, level and logger name are left alone. There is no environment variable for it, so a stray setting can't turn it on or off.

If the function fails, the line shows only the time, level, logger and `[REDACTION FAILED]`, and the app carries on. The same happens when a log call's values don't fit its message, such as `log.info("%d", "text")`. A `redact` that can't be called gives a warning, and every line after it shows `[REDACTION FAILED]`.

Only the handlers `configure_logging()` adds are cleaned. A handler your app adds itself gets the raw lines.

`redact` can be any function. It gets one dictionary and returns one of the same shape:

```python
{
    "message": "signed up ann@example.com",
    "exception": None,
    "stack": None,
    "extra": {"password": "hunter2"},
}
```

`exception` and `stack` are text or `None`, and `extra` holds the `extra` values by name. The dictionaries, lists, sets and tuples it gets are copies, so changing them leaves the app's own record alone. It shouldn't change any other object it gets.

## Names you can't use in `extra`

Python raises an error when `extra` uses a name it reserves: `args`, `asctime`, `created`, `exc_info`, `exc_text`, `filename`, `funcName`, `levelname`, `levelno`, `lineno`, `message`, `module`, `msecs`, `msg`, `name`, `pathname`, `process`, `processName`, `relativeCreated`, `stack_info`, `taskName`, `thread` and `threadName`.

`extra` can use `time`, `level` and `logger`, but in JSON the real values keep those fields and the `extra` values are dropped.
