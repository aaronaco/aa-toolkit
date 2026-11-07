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

`aa init <name>` creates a project in the folder `<name>`, which must be new or empty. It runs `uv init` (a CLI by default, a typed library with `--lib`), pins Python 3.15, adds ruff and pytest, and writes a starter test, AGENTS.md, CLAUDE.md, an MIT LICENSE (`--license none` skips it), a README, a .gitignore and a CI workflow for Windows and Linux. It stages every file on `main` and stops there, so you make the first commit: `aa init` commits only with `--github`. It leaves no aa config in the project.

`aa init` assumes uv and git are installed, and doesn't look for them first. A missing tool is reported as `unexpected`, and the message names it. A missing git name fails with `step_failed` when the project gets a LICENSE, because the name goes in it. When `aa init` fails partway, the folder stays as it is, and the message tells you to delete it before running `aa init` again.

With `--github`, `aa init` also makes the first commit, `chore: initial commit`, creates a private GitHub repo with the project's name, pushes the commit to it and prints its URL. Add `--public` to make the repo public. It assumes gh is installed and signed in, and the commit step fails with git's error if git can't work out your identity. If creating the repo fails, for example because gh is signed out, the local project and its commit stay, and the fix is the `gh repo create` command to rerun from inside the project. If gh created the repo but the push failed, the fix is the `git push` instead.

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

```bash
uv run ty check
```

ty is in beta and can change its diagnostics in any release, so `uv.lock` pins its exact version. Upgrade it by hand with `uv lock --upgrade-package ty`.

The toolkit needs Python 3.14 or newer. Development uses the Python 3.15 pinned in `.python-version`.

### Commit hooks

[prek](https://github.com/j178/prek) runs hooks on every commit. CI runs the same hooks, except `no-commit-to-branch` and the one that reads the commit message. Install them once per machine:

```bash
uv tool install prek==0.5.10
```

```bash
prek install --allow-missing-config
```

Use the `uv tool` copy, not one in a venv. The installed hook stores the full path to the prek that installed it, and all worktrees share that hook, so deleting that venv would fail every commit in every worktree. `--allow-missing-config` keeps commits working on branches that have no `prek.toml` yet.

Run the hooks by hand:

```bash
uv run prek run --all-files
```

On `main`, this reports `no-commit-to-branch` as failed, because commits there are refused.

`uv.lock` pins the prek that CI uses. Dependabot doesn't cover uv here, so upgrade it by hand with `uv lock --upgrade-package prek`, and change the version in the install command above to match. After upgrading, recheck the commit-message hook: `require-pattern` works on commit messages, but prek's docs don't describe this use.

### Workflow audit

[zizmor](https://docs.zizmor.sh/) audits the GitHub Actions workflows and the Dependabot config. The `zizmor` hook runs it offline, and a finding stops a commit and a merge. The `zizmor` workflow also runs the online audits and sends results to the Security tab, but its findings don't block merges.

`uv.lock` pins the zizmor that the hook uses. Upgrade it by hand with `uv lock --upgrade-package zizmor`. The workflow uses the zizmor that the action pins, and Dependabot upgrades the action.

To run the online audits locally, set `GH_TOKEN` and run `uv run zizmor .`.

## Output contract

Every `aa` command follows the same rules, so scripts and AI agents can rely on them:

- `--json` (before or after the subcommand) or `AA_JSON=1` prints exactly one JSON object on stdout: `{"ok": true, "data": ...}` on success, `{"ok": false, "error": {"code", "message", "fix"}}` on failure.
- Logs go to stderr. `--verbose` adds debug logs, including the traceback of an unexpected error.
- Exit codes: `0` success, `1` problems found or an action failed, `2` usage error, `3` unexpected error, `130` stopped with Ctrl+C.
- Error codes are stable, so scripts can branch on them:

| Code | Exit | Meaning |
|---|---|---|
| `target_not_empty` | `1` | `aa init` found the target folder already has something in it. Nothing was changed. |
| `target_in_workspace` | `1` | `aa init` found an outer uv workspace whose `members` would include the target. The fix names the `exclude` entry to add. Nothing was changed. |
| `step_failed` | `1` | An `aa init` step failed. The message names the step and what went wrong. The folder is left as it is, and the message says to delete it before running `aa init` again. When creating the GitHub repo fails, the fix is the `gh repo create` command to rerun from inside the project, or `git push --set-upstream origin main` when the repo was created and only the push failed. |
| `usage` | `2` | Bad or conflicting flags, a missing argument, or an `aa init` name that breaks the name rule. Nothing was created. |
| `aborted` | `130` | Ctrl+C stopped the command. When `aa init` had started writing, the message says the folder was left as it is. |
| `unexpected` | `3` | An uncaught error, such as uv, git or gh missing from PATH. Rerun with `--verbose` for the traceback. |
