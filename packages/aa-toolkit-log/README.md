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

`configure_logging(level=..., file=...)` takes two optional arguments:

- `level`: the lowest level to show, as a name like `"DEBUG"` or a number like `logging.DEBUG`. The default is `INFO`.
- `file`: a path to save logs to. A relative path is relative to the current folder. By default no file is written.

### Environment variables

A variable that is set wins over the matching argument. An empty one counts as not set.

| Variable | Values | What it does |
|---|---|---|
| `AA_LOG_LEVEL` | `DEBUG`, `INFO`, `WARN`, `ERROR`, `CRIT` | Sets the lowest level to show. |
| `AA_LOG_FORMAT` | `text`, `json` | Forces the style on screen. Without it, a terminal gets `text` and anything else gets `json`. |
| `AA_LOG_FILE` | a path | Saves logs to that file. |

A bad value gives a warning on stderr and the default is used. A log file that can't be opened gives a warning and logs stay on screen. Neither stops the app.

## Saving to a file

The file always holds JSON lines in UTF-8, with the same messages as the screen. Its folder is created when it's missing. At 10 MB a new file starts and the last 3 old ones are kept. Only one copy of an app should write to a log file at a time: on Windows, starting a new file can fail when two copies share one, and some lines can be lost.

Add `*.log` to your `.gitignore`, so a log file isn't committed by accident.

## Logs don't hide secrets

Logs don't hide secrets. Whatever you log is shown on screen and saved to the file as it is, so don't log passwords, tokens or keys.

## Names you can't use in `extra`

Python raises an error when `extra` uses a name it reserves: `args`, `asctime`, `created`, `exc_info`, `exc_text`, `filename`, `funcName`, `levelname`, `levelno`, `lineno`, `message`, `module`, `msecs`, `msg`, `name`, `pathname`, `process`, `processName`, `relativeCreated`, `stack_info`, `taskName`, `thread` and `threadName`.

`extra` can use `time`, `level` and `logger`, but in JSON the real values keep those fields and the `extra` values are dropped.
