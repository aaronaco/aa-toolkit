# aa-toolkit

[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/aaronaco/aa-toolkit/badge)](https://scorecard.dev/viewer/?uri=github.com/aaronaco/aa-toolkit)

A personal developer toolkit: the `aa` command plus small libraries, developed together in one uv workspace.

| Path | What it is |
|---|---|
| `packages/aa-toolkit-cli` | The `aa` command (import name `aa_cli`). |
| `packages/aa-toolkit-log` | The log library (import name `aa_log`). See [its README](packages/aa-toolkit-log/README.md). |
| `packages/aa-toolkit-redact` | The redaction library (import name `aa_redact`). See [its README](packages/aa-toolkit-redact/README.md). |
| `packages/aa-toolkit-settings` | The Settings library (import name `aa_settings`). See [its README](packages/aa-toolkit-settings/README.md). |

## Install `aa` from this checkout

You need [uv](https://docs.astral.sh/uv/). From the repo root:

```bash
uv tool install --editable ./packages/aa-toolkit-cli
```

This puts `aa` on your PATH (run `uv tool update-shell` once if it isn't). The install is editable, so changes to the source under `packages/aa-toolkit-cli/src` take effect the next time you run `aa`, with no reinstall.

Changes to `packages/aa-toolkit-cli/pyproject.toml`, such as a new entry point or a new dependency, are not picked up by an editable install. After changing them, reinstall with `--force`:

```bash
uv tool install --force --editable ./packages/aa-toolkit-cli
```

Check it works:

```bash
aa --version
```

## Commands

`aa init <name>` creates a project in the folder `<name>`, which must be new or empty. It runs `uv init` (a CLI by default, a typed library with `--lib`), pins Python 3.15, adds ruff and pytest, and writes a starter test, AGENTS.md, CLAUDE.md, an MIT LICENSE (`--license none` skips it), a README and a .gitignore. It stages every file on `main` and stops there, so you make the first commit: `aa init` commits only with `--github`. It leaves no aa config in the project. It writes no CI; run `aa add ci` to set it up.

`aa init` assumes uv and git are installed, and doesn't look for them first. A missing tool is reported as `unexpected`, and the message names it. A missing git name fails with `step_failed` when the project gets a LICENSE, because the name goes in it. When `aa init` fails partway, the folder stays as it is, and the message tells you to delete it before running `aa init` again.

With `--github`, `aa init` also makes the first commit, `chore: initial commit`, creates a private GitHub repo with the project's name, pushes the commit to it and prints its URL. Add `--public` to make the repo public. It assumes gh is installed and signed in, and the commit step fails with git's error if git can't work out your identity. If creating the repo fails, for example because gh is signed out, the local project and its commit stay, and the fix is the `gh repo create` command to rerun from inside the project. If gh created the repo but the push failed, the fix is the `git push` instead.

The name is also the folder and the package name, so it must start with a letter, end with a letter or digit, hold only letters, digits, `-` and `_`, and be neither a Python keyword nor a name Windows reserves (`con`, `prn`, `aux`, `nul`, `com0`-`com9`, `lpt0`-`lpt9`). Any other name is refused as a usage error before anything is created, never renamed. `aa init .` creates the project in the current folder, which must be empty and whose name follows the same rule.

A project is always its own uv workspace. When you run `aa init` inside another uv workspace whose `members` would include the new folder, `aa init` stops before creating anything and tells you which `exclude` entry to add, because uv would otherwise take the project in as a member and break the outer lock.

Add `--dry-run` to run the same validation (reading `git config` for `user.name` when adding an MIT LICENSE) and print the files and commands `aa init` would create and run, without writing anything or running any setup command. With `--json`, `data` includes `"dry_run": true` and `steps`.

```bash
aa init my-app
```

```bash
aa init my-app --github
```

```bash
aa init my-app --dry-run
```

`aa redact [FILE]` prints a cleaned copy of a file, or of piped text when no file is given, using a `Redactor` from the [redaction library](packages/aa-toolkit-redact/README.md) with its defaults. Every sensitive value is replaced by a Placeholder such as `[EMAIL]`, and a value under a Sensitive name becomes `[REDACTED]`. The original file is never changed; redirect the output to save the cleaned copy. Each line is cleaned with its line ending and flushed as it arrives, and a private key that spans several lines is held back until its end line so its middle lines never slip out.

`--with KIND` turns on the built-in Detectors that are off by default (`IP_ADDRESS`, `PHONE`). `--without KIND` turns off built-in Detectors that are on by default (`AWS_ACCESS_KEY`, `GITHUB_TOKEN`, `API_KEY`, `SLACK_TOKEN`, `JWT`, `BEARER_TOKEN`, `PRIVATE_KEY`, `URL_PASSWORD`, `EMAIL`, `CARD`). Both flags are case-insensitive and accept commas or repetition. Patterns alone cannot find names, street addresses, or secrets with no recognizable prefix, so redaction lowers risk and does not guarantee safety ([ADR 0004](docs/adr/0004-redaction-library-without-dependencies.md)): still read what you share.

```bash
aa redact app.log
```

```bash
aa redact app.log > clean.log
```

```bash
docker logs -f web | aa redact --with ip_address,phone --without card
```

`aa redact --check [FILE]` reports every Finding without changing the file or printing the cleaned copy. Each Finding prints as `<source>:<line>:<column>: <KIND>` (`<stdin>` for piped text), with 1-based character positions and never any part of the value. `--with` and `--without` narrow what counts, and a value under a Sensitive name reports as `REDACTED`. Clean input prints nothing and exits `0`; any Finding makes it exit `1` (plain `aa redact` exits `0` either way). With `--json` (or `AA_JSON=1`), it prints `{"ok": true, "data": {"findings": [...]}}` with each Finding's `line`, `column`, `end_line`, `end_column`, and `kind`, still exiting `1` when the list is not empty.

```bash
aa redact --check app.log
```

```text
app.log:3:6: EMAIL
app.log:3:23: GITHUB_TOKEN
```

`aa secret set NAME` saves a Secret in the Secret store (Credential Manager on Windows), so no file in your project has to hold it. `NAME` is the field name in your app's Settings class, such as `api_key`, so it must be a name a field can have: a valid Python name that doesn't start with `_` and isn't one pydantic reserves, such as `model_config`. The Secret is saved for the app named by `--app`, or else by `[project].name` in `pyproject.toml` in the current folder. Your Settings class's `app_name` must match that name, or the [Settings library](packages/aa-toolkit-settings/README.md) won't find the Secret. At a terminal, `aa secret set` asks for the value at a hidden prompt. Piped text is read to the end, without one trailing line ending, so a file that ends with a line break saves without it. The value is never an argument of `aa`, and no output or error ever prints it. The command you pipe from is another matter: `echo sk-live-abc123 | aa secret set api_key` puts the value in your shell history, so pipe from a file or a password manager instead, or use the prompt. An empty value is refused, and so is one over Credential Manager's limit of 2560 bytes. Saving over an existing Secret replaces it and says `Replaced`. With `--json` (or `AA_JSON=1`), pipe the value in: a terminal is a usage error, because JSON mode never waits for input. `data` holds `app`, `name` and `replaced`.

```bash
aa secret set api_key
```

```bash
cat api_key.txt | aa secret set api_key --app my-app --json
```

```text
{"ok": true, "data": {"app": "my-app", "name": "api_key", "replaced": false}}
```

`aa secret delete NAME` removes a saved Secret, with the same `--app` rule. A Secret that isn't saved is the error `secret_not_found`. There is no command to show a saved Secret or to list them: printing a Secret defeats the point.

```bash
aa secret delete api_key
```

`aa prune [BRANCH...]` cleans up the repo it runs in once pull requests merge: it deletes each Finished branch and removes its worktree folder, and keeps everything whose work isn't already in a merged pull request. It looks at every local branch, with or without a worktree, and asks GitHub through gh, because a squash merge never makes a branch merged to git. A branch goes only when one of the commits of a merged pull request is its last commit, no open pull request contains that commit or comes from that branch, it isn't the repo's default branch, and its worktree, if it has one, has no uncommitted changes or untracked files (changes inside a submodule count), isn't locked, isn't the folder `aa prune` runs from and isn't the repo's main folder. Gitignored files, such as `.venv`, go with the folder. Every other branch is kept, and its line says why: an open pull request, uncommitted changes or new files, a locked worktree, commits added after the pull request merged, no merged pull request (a pull request closed without merging counts as none), the repo's default branch, the folder `aa prune` runs from or the main folder, a branch checked out in more than one worktree, a branch that a rebase or bisect in progress uses, a worktree with a submodule checked out (`git worktree remove` refuses those, and forcing it could lose work), or a worktree whose folder is missing (`git worktree prune` clears those). Worktrees with no branch checked out are listed as kept. Remote branches are left alone, since GitHub deletes them when a pull request merges.

aa reads up to 100 open pull requests and the last 100 commits of each. When it can't see them all, it keeps every branch it would otherwise remove and says so, because it can't rule out an open pull request that holds the branch's last commit. aa decides about every branch before it removes any. Right before removing one, it makes sure again that the branch still points at the commit it asked GitHub about and is still checked out where it was, or nowhere. If either changed, for example because you committed or switched to the branch while aa ran, the branch is kept.

To keep a worktree for good, lock it with `git worktree lock <path>`; aa has no setting of its own for it. Naming branches limits the run to them, with the same rules. There is no confirmation prompt: `--dry-run` shows what would happen and changes nothing. It works with one repo on github.com through gh, which must be signed in.

`aa prune` exits `0` even when it keeps branches. It exits `1` when a worktree folder can't be removed, for example because a terminal or editor on Windows holds a file in it open (that branch is reported as `failed` with git's message, and the other removals still happen), or when a branch you named is kept. git gives up on such a folder only after it has deleted everything else in it and stopped tracking it as a worktree, so the line tells you to close the program and delete what's left of the folder. The next run then deletes the branch. A name that isn't a local branch fails before anything changes. With `--json` (or `AA_JSON=1`), `data` holds `dry_run` and `branches`, each with its `branch` (null for a detached worktree), `action` (`would_remove`, `removed`, `keep` or `failed`), `reason`, `pull_request` (a number or null) and `worktree` (its path or null).

```bash
aa prune --dry-run
```

```text
keep          main       the folder aa runs from
would remove  ticket-64  PR #69 merged, worktree clean
would remove  ticket-65  PR #70 merged, no worktree
keep          ticket-72  worktree has uncommitted changes
keep          ticket-84  PR #89 open
```

```bash
aa prune
```

```bash
aa prune ticket-64 --json
```

`aa commands` lists every visible command with its summary. With `--json` (or `AA_JSON=1`), it follows the Output contract and describes the exit codes, the global flags (`--json`, `--verbose`, `--version`), and each command's summary, arguments, options and effect (`read` or `write`), so an agent or script can learn how to run `aa` without reading `--help`.

```bash
aa commands
```

```bash
aa commands --json
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

```bash
uv run lint-imports
```

`lint-imports` fails when one library imports another, as [ADR 0001](docs/adr/0001-single-workspace-independent-libraries.md) requires. It also runs as a commit hook.

ty is in beta and can change its diagnostics in any release, so `uv.lock` pins its exact version. Upgrade it by hand with `uv lock --upgrade-package ty`. Like every uv upgrade here, it only reaches a version at least 7 days old.

The toolkit needs Python 3.14 or newer. Development uses the Python 3.15 pinned in `.python-version`.

### uv version and cooldown

The toolkit needs uv 0.13.7 exactly. `required-version` in `pyproject.toml` sets it, and CI installs the version it names. Any other uv stops on every project command with an error that names the version. If you installed uv with the standalone installer, get it with:

```bash
uv self update 0.13.7
```

Dependabot doesn't change `required-version`, so upgrade uv by hand: pick a release at least 7 days old, change `required-version`, and change the version in this section and in the workflow templates to match. Dependabot bumps only the templates' `uses:` lines.

uv packages get a 7-day cooldown from `exclude-newer = "7 days"` in `pyproject.toml`. uv skips any file uploaded less than 7 days ago, so `uv lock --upgrade` and `uv lock --upgrade-package` only reach versions at least that old. A file added later to an old release waits 7 days too. Workspace members aren't affected. `uv.lock` records the window, not a date, so it doesn't go stale as days pass. uv only moves the cutoff when it resolves again.

The error doesn't say "too new". A version under 7 days old is treated as if it doesn't exist, so raising a floor to one fails with "only ruff<=0.17.4 is available", even though 0.17.5 is out. uv 0.13.7 may add a `hint:` naming the cutoff. When a version you know exists can't be found, check its upload date first.

To let an urgent security fix through, give that package an exception under `[tool.uv]`: `false` turns the cooldown off for it, or a shorter window lets it through sooner.

```toml
exclude-newer-package = { ruff = false }
```

Remove the exception once every file of that version is more than 7 days old. A file uploaded later, such as a new wheel, waits its own 7 days, and without the exception uv leaves it out of the lock. The `uv audit` workflow is what flags packages that need one.

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

[zizmor](https://docs.zizmor.sh/) audits the GitHub Actions workflows, the workflow templates in `packages/aa-toolkit-cli/src/aa_cli/templates/workflows` and the Dependabot config. The `zizmor` hook runs it offline, and a finding stops a commit and a merge. The `zizmor` workflow also runs the online audits and sends results to the Security tab, but its findings don't block merges.

`uv.lock` pins the zizmor that the hook uses. Upgrade it by hand with `uv lock --upgrade-package zizmor`. The workflow uses the zizmor that the action pins, and Dependabot upgrades the action.

To run the online audits locally, set `GH_TOKEN` and run `uv run zizmor .`.

### Workflow lockfile

`.github/workflows/actions.lock` records the exact commit of every action the workflows use, including actions those actions use. The `uses:` lines name version tags, and the lockfile holds the commits. The `actions-lock` workflow fails a pull request when the lockfile is out of date. Install the [gh-actions-lock](https://github.com/github/gh-actions-lock) extension at the version CI pins:

```bash
gh extension install github/gh-actions-lock --pin v0.4.1
```

Third-party actions only run if they're on the repo's allow list, so add a new one to the list before its pull request runs. Actions created by GitHub, local actions and actions in the owner's repos don't need an entry. [ADR 0003](docs/adr/0003-allow-listed-actions-and-pinning.md) has the steps.

After adding a workflow or changing a `uses:` line, relock and commit the workflow and the lockfile together:

```bash
gh actions-lock
```

Check the lockfile without changing anything:

```bash
gh actions-lock --verify
```

Don't edit the lockfile by hand, and don't delete it to make an error go away. GitHub says Dependabot updates the lockfile in its own pull requests, but no Dependabot pull request here has shown it yet, so check the first one. Dependabot doesn't cover gh extensions, so upgrade the extension by hand: run `gh extension remove actions-lock`, install the new version, and change the `--pin` here and in `.github/workflows/actions-lock.yml` to match.

### Dependency review

The `Dependency review` workflow runs GitHub's [dependency-review-action](https://github.com/actions/dependency-review-action) on every pull request. It fails the pull request when it adds a uv package or a GitHub Action with a known vulnerability of any severity, or a package under a license that isn't allowed. It looks only at what the pull request changes: Dependabot alerts and the weekly `uv audit` cover packages already locked. Packages with no detectable license only warn.

The policy is in `.github/dependency-review.yml`, not in the workflow. Change it in the same pull request that needs the change:

- **Allow a new license:** add its SPDX ID, like `PSF-2.0`, to `allow-licenses`.
- **Skip an advisory:** add its GHSA ID to `allow-ghsas`, with a comment saying why and until when.

GitHub doesn't list uv among the ecosystems its dependency graph supports, although it reads `uv.lock` today. That's why the `uv audit` workflow still runs on pull requests that change `uv.lock`. Coverage of GitHub Actions is partial too: the graph reads the `uses:` lines but not `actions.lock`, so the `known-vulnerable-actions` audit in the `zizmor` workflow stays the check for vulnerable actions. That audit needs the network, so the offline hook skips it, and like the rest of that workflow it doesn't block merges.

### OpenSSF Scorecard

The `Scorecard` workflow scores the repo with [OpenSSF Scorecard](https://github.com/ossf/scorecard) on every push to `main`, every Monday and by hand. Scorecard rates repo-level practices, like branch protection, code review, the security policy and whether the project is maintained. Findings go to the Security tab, and the score goes to the public viewer the badge at the top links to. It runs on `main` only and doesn't block merges.

Sending the score to the Scorecard API makes the API check the workflow before it accepts the results. So the workflow must keep no workflow-level `env`, `defaults` or write permissions, and its job may only use `actions/checkout`, `actions/upload-artifact`, `github/codeql-action/upload-sarif`, `ossf/scorecard-action` and `step-security/harden-runner`.

It uses the default `GITHUB_TOKEN`. That token can read the `Protect main` ruleset, so the Branch-Protection check needs no personal access token.

Scorecard doesn't read `actions.lock`. A `uses:` line that names a tag counts as pinned only when the tag comes from an immutable release, so Pinned-Dependencies can report locked tag refs as unpinned. Dismiss those alerts as "False positive", with the lockfile as the reason, the same way Sonar's `githubactions:S7637` is ignored.

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
| `step_failed` | `1` | An `aa init` step failed. The message names the step and what went wrong. When `aa init` had started writing, the folder is left as it is and the message says to delete it before running `aa init` again; a missing git `user.name` fails before anything is written. When creating the GitHub repo fails, the fix is the `gh repo create` command to rerun from inside the project, or `git push --set-upstream origin main` when the repo was created and only the push failed. In `aa prune`, a git command that reads the repo or a worktree failed. The message names the folder. `aa prune` decides about every branch before it removes any, so nothing changed. |
| `file_not_found` | `1` | `aa redact` was given a file path that does not exist. The message names the path. |
| `cannot_read` | `1` | `aa redact` was given a folder or a file that cannot be read. The message says why. |
| `secret_too_large` | `1` | `aa secret set` was given a value over Credential Manager's limit. The message gives its size and the limit in bytes, never the value. Nothing was saved. |
| `secret_not_found` | `1` | `aa secret delete` found no saved Secret for that app and name. Nothing changed. |
| `no_secret_store` | `1` | `aa secret set` or `aa secret delete` found no Secret store on this machine. |
| `not_a_git_repo` | `1` | `aa prune` ran outside a git repo. Nothing changed. |
| `branch_not_found` | `1` | `aa prune` was given a name that isn't a local branch. The message names it. Nothing changed. |
| `gh_signed_out` | `1` | `aa prune` found gh signed out of github.com. The fix is `gh auth login`. Nothing changed. |
| `no_github_remote` | `1` | `aa prune` found no GitHub repo for the repo it runs in. The message holds gh's error, and the fix is the `git remote add` command. Nothing changed. |
| `github_request_failed` | `1` | `aa prune` couldn't ask GitHub about the pull requests, for example because it's offline. The message holds gh's error. Nothing changed. |
| `usage` | `2` | Bad or conflicting flags, a missing argument, an `aa init` name that breaks the name rule, `aa redact` with no file and a terminal for standard input, or for `aa secret`: a `NAME` no Settings field can have, no app name (the message names `--app`), an empty value, or `--json` with a terminal for standard input. Nothing was created. |
| `aborted` | `130` | Ctrl+C stopped the command, including at the `aa secret set` prompt. When `aa init` had started writing, the message says the folder was left as it is. |
| `unexpected` | `3` | An uncaught error, such as uv, git or gh missing from PATH, or a Secret store that fails (the message never holds the value). `fix` names the Crash report saved for it (see the CLI README), or is null when the report can't be saved. Rerun with `--verbose` for the traceback. |

## Security

To report a vulnerability, follow [SECURITY.md](SECURITY.md). It links to the private report form. Don't use a public issue.
