# aa-toolkit

A personal developer toolkit: the `aa` command plus small libraries, developed together in one uv workspace.

| Path | What it is |
|---|---|
| `packages/aa-cli` | The `aa` command (import name `aa_cli`). |

## Install `aa` from this checkout

You need [uv](https://docs.astral.sh/uv/). From the repo root:

```bash
uv tool install --editable ./packages/aa-cli
```

This puts `aa` on your PATH (run `uv tool update-shell` once if it isn't). The install is editable, so changes to the source under `packages/aa-cli/src` take effect the next time you run `aa`, with no reinstall.

Changes to `packages/aa-cli/pyproject.toml`, such as a new entry point or a new dependency, are not picked up by an editable install. After changing them, reinstall with `--force`:

```bash
uv tool install --force --editable ./packages/aa-cli
```

Check it works:

```bash
aa --version
```

## Develop

```bash
uv sync
```

```bash
uv run pytest
```

```bash
uv run ruff check .
```

```bash
uv run ruff format .
```

The toolkit needs Python 3.14 or newer. Development uses the Python 3.15 pinned in `.python-version`.

## Output contract

Every `aa` command follows the same rules, so scripts and AI agents can rely on them:

- `--json` (before or after the subcommand) or `AA_JSON=1` prints exactly one JSON object on stdout: `{"ok": true, "data": ...}` on success, `{"ok": false, "error": {"code", "message", "fix"}}` on failure.
- Logs go to stderr. `--verbose` adds debug logs, including the traceback of an unexpected error.
- Exit codes: `0` success, `1` problems found or an action failed, `2` usage error (code `usage`), `3` unexpected error (code `unexpected`).
