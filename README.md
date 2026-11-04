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

## Commands

`aa init <name>` creates a project in the folder `<name>`, which must be new or empty. It runs `uv init` (a CLI by default, a typed library with `--lib`), pins Python 3.15, records the project kind under `[tool.aa]` in pyproject, adds ruff and pytest, and writes a starter test, AGENTS.md, CLAUDE.md, an MIT LICENSE (`--license none` skips it), a README, a .gitignore and a CI workflow for Windows and Linux. It ends with one commit, `chore: initialize project with aa`. It checks uv, git and your git identity first, and creates nothing if one is missing.

```bash
aa init my-app
```

`aa doctor` checks the machine: uv, git and gh on PATH, your git name and email, and the gh sign-in. Every failed check shows the command that fixes it. It exits `1` when any check fails.

```bash
aa doctor
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

- `--json` (before or after the subcommand) or `AA_JSON=1` prints exactly one JSON object on stdout: `{"ok": true, "data": ...}` on success, `{"ok": false, "error": {"code", "message", "fix"}}` on failure. A failure may also carry `data` with the partial result. For example, `aa doctor` returns the full check list there.
- Logs go to stderr. `--verbose` adds debug logs, including the traceback of an unexpected error.
- Exit codes: `0` success, `1` problems found or an action failed, `2` usage error, `3` unexpected error.
- Error codes are stable, so scripts can branch on them:

| Code | Exit | Meaning |
|---|---|---|
| `checks_failed` | `1` | `aa doctor` found at least one failed check. `data.checks` holds every check. |
| `target_not_empty` | `1` | `aa init` found the target folder already has something in it. Nothing was changed. |
| `preflight_failed` | `1` | `aa init` found uv, git or the git identity missing. `data.checks` holds the failed checks. Nothing was created. |
| `step_failed` | `1` | An `aa init` step failed. The message names the step and the tool's error. The folder is left as it is. |
| `usage` | `2` | Bad or conflicting flags, or a missing argument. |
| `unexpected` | `3` | An uncaught error. Rerun with `--verbose` for the traceback. |
