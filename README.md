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

`aa init <name>` creates a project in the folder `<name>`, which must be new or empty. It runs `uv init` (a CLI by default, a typed library with `--lib`), pins Python 3.15, adds ruff and pytest, and writes a starter test, AGENTS.md, CLAUDE.md, an MIT LICENSE (`--license none` skips it), a README, a .gitignore and a CI workflow for Windows and Linux. It ends with one commit, `chore: initial commit`, and leaves no aa config in the project.

`aa init` assumes uv and git are installed and your git identity is set, and doesn't look for them first. A missing tool is reported as `unexpected`, and a missing identity fails the commit step with git's error.

With `--github`, `aa init` also creates a private GitHub repo with the project's name, pushes the first commit to it and prints its URL. Add `--public` to make the repo public. It assumes gh is installed and signed in. If creating the repo fails, for example because gh is signed out, the local project and its commit stay, and the fix is the `gh repo create` command to rerun from inside the project. If gh created the repo but the push failed, the fix is the `git push` instead.

The name is also the folder and the package name, so it must start with a letter, end with a letter or digit, hold only letters, digits, `-` and `_`, and be neither a Python keyword nor a name Windows reserves (`con`, `prn`, `aux`, `nul`, `com0`-`com9`, `lpt0`-`lpt9`). Any other name is refused as a usage error before anything is created, never renamed. `aa init .` creates the project in the current folder, which must be empty and whose name follows the same rule.

A project is always its own uv workspace. When you run `aa init` inside another uv workspace whose `members` would include the new folder, `aa init` stops before creating anything and tells you which `exclude` entry to add, because uv would otherwise take the project in as a member and break the outer lock.

```bash
aa init my-app
```

```bash
aa init my-app --github
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

- `--json` (before or after the subcommand) or `AA_JSON=1` prints exactly one JSON object on stdout: `{"ok": true, "data": ...}` on success, `{"ok": false, "error": {"code", "message", "fix"}}` on failure. A failure may also carry `data` with the partial result.
- Logs go to stderr. `--verbose` adds debug logs, including the traceback of an unexpected error.
- Exit codes: `0` success, `1` problems found or an action failed, `2` usage error, `3` unexpected error, `130` stopped with Ctrl+C.
- Error codes are stable, so scripts can branch on them:

| Code | Exit | Meaning |
|---|---|---|
| `target_not_empty` | `1` | `aa init` found the target folder already has something in it. Nothing was changed. |
| `target_in_workspace` | `1` | `aa init` found an outer uv workspace whose `members` would include the target. The fix names the `exclude` entry to add. Nothing was changed. |
| `step_failed` | `1` | An `aa init` step failed. The message names the step and the tool's error. The folder is left as it is. When creating the GitHub repo fails, the fix is the `gh repo create` command to rerun from inside the project, or `git push --set-upstream origin main` when the repo was created and only the push failed. |
| `usage` | `2` | Bad or conflicting flags, a missing argument, or an `aa init` name that breaks the name rule. Nothing was created. |
| `aborted` | `130` | Ctrl+C stopped the command. When `aa init` had started writing, the message says the folder was left as it is. |
| `unexpected` | `3` | An uncaught error, such as uv, git or gh missing from PATH. Rerun with `--verbose` for the traceback. |
