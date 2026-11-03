# uv and tooling research

Retrieved 2026-11-04. Facts only, from official docs and PyPI project pages. Items marked **UNCONFIRMED** are not stated in the official docs consulted and need an empirical check.

## 1. Current versions

- uv latest: **0.13.7** (released 2026-11-03). Previous releases: 0.13.6 (2026-10-27), 0.13.5 (2026-10-22).
- Python latest release: **3.15.2** (2026-10-25). The 3.14 line is at 3.14.10 (2026-10-25).
- Supported branches according to the devguide:

  | Branch | Status | EOL |
  |---|---|---|
  | 3.16 (main) | feature | 2032-10 (scheduled) |
  | 3.15 | bugfix | 2031-10 |
  | 3.14 | bugfix | 2030-10 |
  | 3.13 | security | 2029-10 |
  | 3.12 | security | 2028-10 |
  | 3.11 | security | 2027-10 |

- 3.10 reached end of life on 2026-10-01, and 3.9 on 2025-10-31.

Sources: https://pypi.org/project/uv/ · https://www.python.org/downloads/ · https://devguide.python.org/versions/

## 2. `uv tool install --editable` for a workspace member

- The `-e/--editable` flag exists on `uv tool install`. Per the CLI reference, it installs "the target package in editable mode, such that changes in the package's source directory are reflected without reinstallation".
- Tool installs get an isolated, persistent venv in the tools directory. The docs say never to mutate it manually (for example with pip).
- Other flags: `--with`, `--with-editable` (extra packages in editable mode), `--force` (recreates the env and replaces entry points), `--reinstall`, `-p/--python`, `--no-sources` (ignore `tool.uv.sources`).
- Executables are symlinked on Unix and copied on Windows. uv will not overwrite executables it did not create unless you pass `--force`.
- Executable directory on Windows, first match wins: `%XDG_BIN_HOME%`, then `%XDG_DATA_HOME%\..\bin`, then `%USERPROFILE%\.local\bin`. `UV_TOOL_BIN_DIR` overrides it, and `UV_TOOL_DIR` sets the tool env directory.
- `uv tool dir` prints the tool env directory. `uv tool dir --bin` prints the executable directory.
- `uv tool update-shell` "ensures that the tool executable directory is on the PATH" by adding it to shell config files. If a config blurb already exists but the directory is still not on PATH, uv exits with an error.
- **UNCONFIRMED:** how `update-shell` changes PATH on Windows (registry user env or PowerShell profile). The docs do not say.
- **UNCONFIRMED:** whether `uv tool install -e packages/aa-cli` honours the member's `[tool.uv.sources] aa-log = { workspace = true }` and resolves siblings from the workspace, and whether those siblings are also installed editable. The docs only say that `--no-sources` would ignore workspace/git/path sources, which implies sources are read by default. Neither the tools concept page nor the tools guide covers workspace members. Verify empirically, or pass siblings explicitly with `--with-editable ./packages/aa-log`.
- **UNCONFIRMED:** whether edits to the `pyproject.toml` entry points or dependencies take effect without reinstall. The editable flag only promises that source changes do. Use `uv tool install --force -e ...` or `--reinstall` after metadata changes.

Sources: https://docs.astral.sh/uv/concepts/tools/ · https://docs.astral.sh/uv/guides/tools/ · https://docs.astral.sh/uv/reference/storage/ · https://docs.astral.sh/uv/reference/cli/#uv-tool-install

## 3. uv workspaces

- Root config:
  ```toml
  [tool.uv.workspace]
  members = ["packages/*"]
  exclude = ["packages/seeds"]   # optional
  ```
  Every matched directory must contain a `pyproject.toml`.
- Member-to-member dependency: list the dependency in `[project].dependencies`, then add `[tool.uv.sources] aa-log = { workspace = true }`.
  - Workspace members are always editable.
  - A source defined in the root applies to all members unless a member overrides it.
- One lockfile for the whole workspace. `uv lock` operates on the whole workspace.
- One `requires-python` for the whole workspace: the intersection of all members' values.
- `uv run --package X` / `uv sync --package X` target one member from any directory in the workspace. `uv run` and `uv sync` default to the root.
- `uv sync --all-packages`: "Sync all packages in the workspace." `uv run --all-packages` runs with all members installed.
- `uv build --package X` builds one member. `uv build --all-packages` (alias `--all`) builds all of them. Output goes to `dist/` by default and can be changed with `-o/--out-dir`.
- Virtual root (no `[project]` in the root):
  - The workspaces page says every workspace "needs a root, which is also a workspace member". All its examples use a root that has `[project]`.
  - The internal metadata reference does describe "the non-package workspace root" that defines dependency groups. That implies a root without a package is supported.
  - **UNCONFIRMED:** that a `[project]`-less root is officially supported. No recommendation either way was found in the docs.
- The docs say not to use a workspace when members have conflicting requirements or need separate venvs. Use path dependencies instead.

Sources: https://docs.astral.sh/uv/concepts/projects/workspaces/ · https://docs.astral.sh/uv/concepts/projects/dependencies/ · https://docs.astral.sh/uv/reference/internals/metadata/ · https://docs.astral.sh/uv/reference/cli/

## 4. Verifying one member installs and imports in isolation

- All flags exist on `uv run`. Exact wording from the CLI reference:
  - `--no-project`: "Avoid discovering the project or workspace", and "run in an isolated, ephemeral environment populated by the `--with` requirements."
  - `--isolated`: "forces a fresh environment to be used for the project, enforcing strict isolation between dependencies and declaration of requirements."
  - `--with`: "Run with the given packages installed." `--with-editable` is the editable variant.
- Candidate command: `uv run --isolated --no-project --with ./packages/aa-vault python -c "import aa_vault"`
- **UNCONFIRMED:** that `--with` accepts a local path like `./packages/aa-vault`. The CLI reference says only "packages". `uv tool run` is documented as "nearly equivalent to" `uv run --no-project --with <name>`.
- **UNCONFIRMED:** whether `--no-project` alone ignores a `.venv` discovered in the cwd or its parents. The general `uv run` text says that outside a project a discovered venv is used. `--isolated` is the documented way to force a fresh env, so keep both flags, or run from outside the workspace dir.
- Sibling imports are not covered by this check. A sibling import that is not in the member's deps would fail at import time only if that code path runs. Use import-linter (section 8) to catch them statically.

Source: https://docs.astral.sh/uv/reference/cli/#uv-run

## 5. Downstream git dependency on one member

- Documented form uses a URL fragment:
  ```
  uv add "git+https://github.com/OWNER/REPO#subdirectory=packages/aa-vault" --tag v0.1.0
  ```
- Resulting entry:
  ```toml
  [tool.uv.sources]
  aa-vault = { git = "https://github.com/OWNER/REPO", subdirectory = "packages/aa-vault", tag = "v0.1.0" }
  ```
- Supported source keys: `git`, `tag`, `branch`, `rev`, `subdirectory`, `lfs`.
- `uv add` has `--tag`, `--branch`, `--rev` and `--lfs` flags.
- **UNCONFIRMED:** whether a `--subdirectory` flag exists on `uv add`. It was not found in the CLI reference sections read. Use the `#subdirectory=` fragment, which is documented.
- A member with no sibling deps is a normal standalone package in a subdirectory and should resolve.
- **UNCONFIRMED:** how uv treats `{ workspace = true }` sources of a member fetched from git. The docs say nothing about workspace discovery inside git checkouts.
- `tool.uv.sources` is uv-only metadata. `--no-sources` resolves against standards-compliant metadata.

Sources: https://docs.astral.sh/uv/concepts/projects/dependencies/ · https://docs.astral.sh/uv/reference/cli/#uv-add

## 6. `uv init` options and output

- Flags (from the CLI reference):
  - `--app`: the default project kind. "Applications are packaged by default".
  - `--lib`
  - `--package`: defines `[build-system]`. "This is the default behavior."
  - `--no-package`: flat layout with `main.py` and no build-system.
  - `--bare`: only `pyproject.toml`. No README, `src/` or `.python-version`, and no VCS init.
  - `--build-backend {uv,hatch,flit,pdm,poetry,setuptools,maturin,scikit}`: implies `--package`.
  - `-p/--python`: the interpreter used to determine minimum `requires-python`.
  - `--pin-python` / `--no-pin-python`
  - `--vcs {git,none}`: default `git`.
  - `--no-readme`
  - `--author-from {auto,git,none}`: default `auto`.
  - `--description`, `--no-description`
  - `--no-workspace` (alias `--no-project`): do not join a parent workspace.
  - `--script`: PEP 723 script.
  - `--name`: defaults to the directory name.
- Default build backend is `uv_build`. A generated app has:
  ```toml
  [project.scripts]
  example-app = "example_app:main"

  [build-system]
  requires = ["uv_build>=0.13.7,<0.14"]
  build-backend = "uv_build"
  ```
  - Since v0.12, apps get a build system by default.
- Default / `--app` output: `.python-version`, `README.md`, `pyproject.toml`, `src/<pkg>/__init__.py` (with a `main` function), plus a git repo.
- `--lib` output: the same files plus `src/<pkg>/py.typed`. No `[project.scripts]`.
- `--no-package` output: `.python-version`, `README.md`, `main.py`, `pyproject.toml`.
- Example `requires-python` is `>=3.11` (`>=3.12` in the `--bare` example). It derives from the discovered interpreter.
- **UNCONFIRMED:** the exact `.gitignore` contents and whether `.gitignore` is created when `--vcs git` is used. Not listed in the init page trees.
- Running `uv init` inside a workspace dir adds the new project as a member unless you pass `--no-workspace`. That follows from the flag's description.
- `uv_build` settings (`[tool.uv.build-backend]`):
  - `module-name` defaults to the package name with `-` and `.` replaced by `_`, so `aa-cli` maps to `aa_cli`. That mapping is an inference from the documented rule.
  - `module-root` defaults to `src`.
- `uv python pin [REQUEST]` writes `.python-version` in the cwd.
  - `--global` writes the user-level pin.
  - `--resolved` writes the interpreter path (docs: usually unsafe to commit).
  - `--rm` removes the pin.
- `uv python install` with no args installs the version in `.python-version`, or every version listed in `.python-versions`.

Sources: https://docs.astral.sh/uv/concepts/projects/init/ · https://docs.astral.sh/uv/reference/cli/#uv-init · https://docs.astral.sh/uv/concepts/projects/config/ · https://docs.astral.sh/uv/reference/settings/ · https://docs.astral.sh/uv/concepts/python-versions/

## 7. Typer and Click

- Typer latest: **0.27.3** (2026-10-06). Requires Python >=3.10.
- Since **0.26.0** (2026-05-26), Typer **vendors Click**. Click is no longer a separate dependency.
  - The notes say Click-specific features such as extracting the Click app and adding Click plugins are no longer supported.
- Dependencies: `rich`, `shellingham`, `annotated-doc`, and `colorama` (Windows only). `typing-extensions` was removed in 0.21.2.
- `typer-slim` and `typer-cli` were discontinued in 0.24.1. Install `typer` only.
- Rich is required. Rich error formatting can be disabled with `TYPER_USE_RICH=0`.
- Startup: 0.17.0 lazy-loads `rich_utils` "to reduce startup time". No timing figures are published.
- Global options:
  - Declare them as parameters of an `@app.callback()` function.
  - Share state via a module-level dict (tutorial pattern) or `typer.Context`.
  - Global options must come **before** the subcommand (`aa --json doctor`). `aa doctor --json` errors unless the option is also declared on the command.
  - `ctx.invoked_subcommand` and `@app.callback(invoke_without_command=True)` are documented.
  - **UNCONFIRMED** in the Typer docs: `ctx.obj` usage. It is not on the callback or context pages read.
- Click latest: **8.5.0** (2026-08-26). Requires Python >=3.10.

Sources: https://pypi.org/project/typer/ · https://typer.tiangolo.com/release-notes/ · https://typer.tiangolo.com/tutorial/commands/callback/ · https://typer.tiangolo.com/tutorial/commands/context/ · https://pypi.org/project/click/

## 8. import-linter independence contract

- Latest version: **2.15** (2026-09-04). Requires Python >=3.10.
- Install: `uv add --dev import-linter`.
- Config:
  ```toml
  [tool.importlinter]
  root_packages = ["aa_log", "aa_config", "aa_vault"]

  [[tool.importlinter.contracts]]
  id = "libs-independent"        # optional
  name = "Libraries are independent"
  type = "independence"
  modules = ["aa_log", "aa_config", "aa_vault"]
  # ignore_imports = ["a.b -> c.d"]   # optional
  ```
- Independence means "no imports in any direction between the modules, even indirectly". `modules` supports wildcards.
- Root packages must be importable: installed in the env, or in the cwd. Run inside the synced workspace venv.
- Run with `lint-imports` (e.g. `uv run lint-imports`). Flags: `--config <file>`, `--contract <id>` (repeatable), `--verbose`.
- **UNCONFIRMED:** that the stable docs show the independence example with separate top-level packages. All examples use subpackages of one root, and the `root_packages` page does not say it is restricted.

Sources: https://import-linter.readthedocs.io/en/stable/contract_types/independence/ · https://import-linter.readthedocs.io/en/stable/get_started/configure/ · https://import-linter.readthedocs.io/en/stable/get_started/install/ · https://import-linter.readthedocs.io/en/v2.0/usage.html (CLI flags) · https://pypi.org/project/import-linter/

## 9. Claude Code: CLAUDE.md imports and AGENTS.md

- CLAUDE.md supports `@path/to/file` imports.
  - Relative paths resolve from the importing file. Absolute paths are allowed.
  - Imports can recurse up to a **max depth of four hops**.
  - Imports inside code spans and fences are ignored.
  - Imports that resolve outside the working directory trigger a one-time approval dialog.
- Claude Code reads AGENTS.md natively, from **v2.1.277**.
  - By default (`claude-md-or-agents-md`), it reads AGENTS.md **only when there is no** `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` in the cwd or any parent directory.
  - The setting `claude-md-and-agents-md` loads both.
- If you keep a CLAUDE.md too, the docs say to put `@AGENTS.md` in it. The import never causes double loading.
- On **Windows**, the docs recommend the `@AGENTS.md` import over symlinking `CLAUDE.md` to `AGENTS.md`. Symlinks need admin or Developer Mode, and git checks them out as plain text unless `core.symlinks` is set.
- `AGENTS.local.md`, `AGENTS.override.md` and `.agents/` are not read.

Source: https://code.claude.com/docs/en/memory

## 10. GitHub Actions with setup-uv

- `astral-sh/setup-uv` latest: **v10.3.3** (released 28 Oct). The current major is **v10**.
  - v10.0.0 broke compatibility: `enable-cache: auto` now disables caching on `pull_request_target`, `workflow_run` and `release` events.
  - The uv docs' GitHub guide still shows `v9.0.0`.
- Inputs:

  | Input | Default |
  |---|---|
  | `version` | `required-version` from config, otherwise latest |
  | `python-version` | none; sets `UV_PYTHON` |
  | `enable-cache` | `auto`, which is on for GitHub-hosted runners |
  | `cache-dependency-glob` | includes `pyproject.toml`, `uv.lock`, `requirements*.txt` |
  | `activate-environment` | `false` |
  | `working-directory` | none |
  | `cache-suffix` | none |
  | `prune-cache` | none |

- The uv docs recommend pinning the uv `version`, using `uv python install` (it reads `.python-version`), `uv sync --locked ...` and `uv run pytest`.
- The docs show no OS matrix. The matrix below is standard GitHub Actions syntax:
  ```yaml
  jobs:
    test:
      strategy:
        matrix:
          os: [ubuntu-latest, windows-latest]
      runs-on: ${{ matrix.os }}
      steps:
        - uses: actions/checkout@v5            # UNCONFIRMED: current actions/checkout major not checked
        - uses: astral-sh/setup-uv@v10         # pin to SHA per upstream examples
          with:
            version: "0.13.7"
            enable-cache: true
        - run: uv python install
        - run: uv sync --locked --all-packages --dev
        - run: uv run pytest
  ```
- The upstream examples pin by commit SHA with a version comment. Example: `astral-sh/setup-uv@68559e99cc807c1eb7e9238fd43a15bba460eec2 # v10.3.3`.

Sources: https://github.com/astral-sh/setup-uv · https://github.com/astral-sh/setup-uv/releases · https://docs.astral.sh/uv/guides/integration/github/
