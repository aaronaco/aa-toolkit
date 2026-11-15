# Self-describing CLI research

Retrieved 2026-11-15. Facts only, from official docs, specs and source code, plus local runs where noted ("verified locally"). Items marked **UNCONFIRMED** are not stated in a primary source consulted and need a check. The last section holds the recommendations for aa.

## 1. Versions checked

- Click latest: **8.5.1**. Typer installed in this repo: **0.27.3**. Typer latest: **0.29.1**. Typer 0.29.0 came out on 2026-11-09, so the repo's 7-day uv cooldown still holds it back.
- MCP spec latest: **2026-07-28** (`LATEST_PROTOCOL_VERSION` in `schema.ts`). Python SDK `mcp` **2.3.0**, `fastmcp` **4.2.0**, `click-mcp` **0.6.1**.
- Tools run locally: uv 0.13.7, gh 2.102.0, git 2.56.1, npm 11.12.1, kubectl 1.34.1 (client), Docker 29.1.3, copier 9.19.1 (through `uvx`).

Sources: https://pypi.org/project/click/ · https://pypi.org/project/typer/ · https://typer.tiangolo.com/release-notes/ · https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2026-07-28/schema.ts · https://pypi.org/project/mcp/ · https://pypi.org/project/fastmcp/ · https://pypi.org/project/click-mcp/

## 2. Click's `to_info_dict()`

- `Context.to_info_dict()` walks the whole command tree. Its docstring says it gathers information "useful for a tool generating user-facing documentation". It was added in **8.0**. Neither the docstring nor the API page calls the output stable.
- The shape has changed in minor releases. In 8.3.0 `default` and `flag_value` became `None` when unset. In 8.5.0 `default` and `flag_value` began reporting auto-derived values.
- Top level: `command`, `info_name`, `allow_extra_args`, `allow_interspersed_args`, `ignore_unknown_options`, `auto_envvar_prefix`.
- Command: `name`, `params`, `help`, `epilog`, `short_help`, `hidden`, `deprecated`. A group adds `commands` (name to command dict) and `chain`.
- Parameter: `name`, `param_type_name` (`option` or `argument`), `opts`, `secondary_opts`, `type`, `required`, `nargs`, `multiple`, `default`, `envvar`, `help`. An option adds `prompt`, `is_flag`, `flag_value`, `count` and `hidden`.
- Type: `{"param_type": "Choice", "name": "choice", "choices": [...], "case_sensitive": false}`. A plain string is `{"param_type": "String", "name": "text"}`.
- The auto-added help option shows up as a param named `_click_default_help`.
- Trimmed real output from Click 8.5.1 on a small demo group (verified locally):

  ```json
  {"command": {"name": "cli", "commands": {"init": {"name": "init", "help": "Create a project.",
    "hidden": false, "deprecated": false, "params": [
      {"name": "name", "param_type_name": "argument", "opts": ["name"],
       "type": {"param_type": "String", "name": "text"}, "required": true, "nargs": 1,
       "multiple": false, "default": null, "envvar": null, "help": null},
      {"name": "license", "param_type_name": "option", "opts": ["--license"],
       "type": {"choices": ["MIT", "none"], "case_sensitive": false, "param_type": "Choice", "name": "choice"},
       "required": false, "default": "MIT", "is_flag": false, "flag_value": null, "count": false, "hidden": false}]}},
    "chain": false},
   "info_name": "demo", "auto_envvar_prefix": null}
  ```

Sources: Click 8.5.1 source (`click.core.Context.to_info_dict`, `Command`, `Group`, `Parameter`, `Option`, `click.types.ParamType.to_info_dict`) · https://click.palletsprojects.com/en/stable/api/

## 3. Typer: what it exposes now

- **Typer stopped depending on Click in 0.26.0 (2026-05-26).** It now ships a copy of Click under the private module `typer._click`. The release notes say "Click-specific functionality is no longer supported", naming "extracting the Click app" and Click plug-ins. The "Vendored Click" docs page adds that some Click functionality "will not be available anymore in the future".
- **`to_info_dict` is gone.** The vendored copy (adapted from Click 8.3.1) has no `to_info_dict` anywhere, and `typer.main.get_command(app)` returns a `typer._click` object, not a `click.Command`. Verified locally on 0.27.3: `hasattr(..., "to_info_dict")` is false for the root command and for `Context`, and `import click` fails in the aa environment.
- **0.29.0 changed parameter internals again.** On Typer's master branch (0.29.1), parameters have no `.type` attribute (no `ParamType`, no `TyperChoice.choices`). They carry a Pydantic-based `type_descriptor` instead. Pydantic `>=2.5.3` is now a required dependency, and `click_type` was removed from `typer.Option()` and `typer.Argument()`. Code that reads `param.type.name` on 0.27.3 will break on 0.29.
- What still works on 0.27.3 and master:
  - `typer.main.get_command(app)` builds the command tree. Typer's own `typer utils docs` (Markdown docs generator) calls it on both versions.
  - On that tree, each `TyperOption` and `TyperArgument` has `name`, `opts`, `required`, `multiple`, `nargs`, `default`, `hidden`, `help`, `envvar` and `metavar`.
  - Each command has `help`, `short_help`, `hidden` and `deprecated`.
- Typer has no JSON output of its command tree. `typer utils docs` writes Markdown only. Rich help is presentation only.
- Typer 0.25.1+ ships an agent skill file at `typer/.agents/skills/typer/SKILL.md` in the installed package. It holds coding guidance, not a description of the app.
- Real aa command tree, walked from `get_command(app)` on Typer 0.27.3 (verified locally, trimmed). The root holds `--json`, `--verbose` and `--version` (eager). The hidden `crash` command shows `"hidden": true`.

  ```json
  {"init": {"help": "Create a project in a new or empty folder.", "hidden": false, "params": [
     {"class": "TyperArgument", "name": "name", "opts": ["name"], "type": "str", "required": true,
      "help": "The project name, also the folder it goes in."},
     {"class": "TyperOption", "name": "license_choice", "opts": ["--license"], "type": "choice",
      "choices": ["MIT", "none"], "default": "MIT", "is_flag": false, "help": "The license to add."},
     {"class": "TyperOption", "name": "github", "opts": ["--github"], "type": "boolean", "is_flag": true,
      "default": false, "help": "Also create a private GitHub repo and push to it."}]},
   "redact": {"help": "Print a cleaned copy of a file or piped text.", "params": [
     {"class": "TyperArgument", "name": "file", "type": "path", "required": false, "metavar": "FILE"},
     {"class": "TyperOption", "name": "with_kinds", "opts": ["--with"], "type": "str", "multiple": true,
      "metavar": "KIND"}]}}
  ```

- The parameter `name` on the tree is the Python parameter name (`license_choice`, `json_output`). It matches the parameter of aa's own command function, so the stdlib `typing.get_type_hints(fn, include_extras=True)` can supply the type (`License`, `list[str] | None`, `Path | None`) without touching Typer internals (verified locally).

Sources: https://typer.tiangolo.com/release-notes/ · https://github.com/fastapi/typer/blob/master/docs/tutorial/click.md · https://github.com/fastapi/typer/blob/master/typer/core.py · https://github.com/fastapi/typer/blob/master/typer/_click/core.py · https://github.com/fastapi/typer/blob/master/typer/cli.py · installed `typer` 0.27.3 package

## 4. How established CLIs describe themselves

- **gh**
  - `--json` with no field names prints the list of available fields on stderr and exits 1 (verified locally with `gh pr list --json`).
  - `gh help formatting` documents `--json`, `--jq` and `--template`.
  - `gh help reference` prints every command as one Markdown document.
  - `gh help exit-codes` documents exit codes in prose: 0 ok, 1 failed, 2 cancelled, 4 auth needed. It warns that some commands use more codes.
  - gh has no JSON listing of its commands.
- **kubectl**
  - `kubectl explain <type>.<field>` describes the fields of API resources. It reads them from the server in OpenAPI format.
  - `kubectl api-resources -o` accepts `json`, `yaml`, `name` or `wide` per the local help. It lists resources, not CLI commands.
  - Most commands take `-o json|yaml|...` (verified locally).
- **terraform**
  - `terraform providers schema -json` prints provider schemas with a `format_version` key. Each attribute has `type`, `description`, `required`, `optional`, `computed` and `sensitive`. The page says the `-json` flag is required.
  - `-json` on `plan`, `apply` and others streams one JSON message per line. The first message is always `version`, and each message has a `type`.
  - Versioning rule for both formats: a minor bump adds fields and consumers must ignore unknown ones. A major bump breaks, and consumers must reject unsupported majors.
  - Terraform describes provider and resource schemas, not its own commands.
- **docker**: many commands take `--format json` (verified locally: `docker version --format json`, and the `docker inspect --help` text). Docker has no command listing.
- **aws CLI**
  - `--generate-cli-skeleton` (values `input`, `yaml-input`, `output`) prints a template holding every input (or output) parameter of one command. `--cli-input-json` and `--cli-input-yaml` feed a filled template back in.
  - The skeleton uses the underlying API's parameter names. Custom commands such as `aws s3` don't support it.
  - Return codes are documented in a prose table: 0, 1, 2 (could not parse), 130 (Ctrl+C), 252, 253, 254, 255.
- **cargo**
  - `cargo --list` lists installed subcommands as text.
  - `cargo metadata --format-version 1` prints JSON about the workspace, not the CLI. The page tells callers to pin `--format-version` and says new fields may be added within a version.
  - Exit status: 0 ok, 101 failed.
- **uv**
  - `uv help <command>` shows docs as text. uv has no machine-readable command list.
  - JSON output is per command: `--output-format json` on `sync`, `python list`, `version` and `self version`, and `--format json` on `pip list` (verified locally).
  - The `uv sync --output-format json` output starts with `"schema": {"version": "preview"}`.
- **git**
  - `git --list-cmds=<group>` lists commands as text. The docs call it an "internal/experimental option" that may change or be removed.
  - Help is man pages and `git help -a`.
- **npm**: the `json` config prints JSON "rather than the normal output", but the docs note it is not supported by all commands. npm has no command listing.
- **Cobra (Go)**
  - The `doc` package writes Markdown, man, reST or YAML per command. The YAML fields are `name`, `synopsis`, `description`, `usage`, `options`, `inherited_options` (each with `name`, `shorthand`, `default_value` and `usage`), `example` and `see_also`. There are no types or exit codes.
  - Cobra adds a `completion` command and a hidden `__complete` command that completion scripts call.
- **Fig / withfig autocomplete**
  - TypeScript specs describe subcommands, options and args.
  - Options can have `isRequired`, `isRepeatable`, `exclusiveOn` and `dependsOn`. Subcommands, options and args can have `isDangerous`.
  - A Click integration (`click_complete_fig`) adds a `generate-fig-spec` subcommand.
  - The withfig repos were last pushed in 2025. fig.io returned HTTP 503 when checked.
- **carapace**: YAML completion specs. Generators exist for clap, kong, urfave/cli, oclif, man pages and (through click-extra) Click.
- **usage spec (usage.jdx.dev)**
  - A KDL format describing `bin`, `cmd`, `flag`, `arg`, help, aliases, `deprecated`, `hide`, env bindings, config and defaults.
  - It also covers command **effects** (`read`, `write`, `destructive`). A flag can raise a command's effect, and a missing effect means "ask".
  - It also covers **outputs and exit codes**: `output "json" framing="json"` with an optional JSON Schema, and `exit_code 1 "a check failed"`, declared once at the top level or per command.
  - Tools generate completions, Markdown, man pages and SDKs from a spec.
  - `usage mcp` serves a spec as two MCP tools, `list_commands` and `describe_command`. Together they describe a CLI without running it.
  - `usage generate json` prints the spec as JSON.
  - Integrations exist for Typer (`usage-spec-typer` 1.2.1, which handles Typer >= 0.26 through `typer.core` classes), Click, argparse, clap, Cobra and others.
  - The Cobra guide recommends checking for a `--usage-spec` flag before `Execute()`. mise has a hidden `mise usage` command.
- Command names seen for "describe yourself":
  - `help reference` (gh), `utils docs` (Typer), `--list` (cargo) and `--list-cmds` (git) as text listings.
  - `usage` or `--usage-spec` (mise, usage spec), `generate-fig-spec` (Fig), `explain` (kubectl for resources, `rustc --explain` for error codes), `--generate-cli-skeleton` (aws, per command).
  - `list_commands` / `describe_command` (usage's MCP server).
  - No primary-source example of `help --json`, `--help-json`, `describe` or a `commands` subcommand that prints JSON was found (**UNCONFIRMED** that none exists).
- The most common pattern: per-command `--json` (or `-o json`, `--format json`) for data, with help kept as text or Markdown. A full machine-readable command tree comes from a separate spec format (usage, Fig, carapace, Cobra YAML), usually produced by a hidden or dedicated command.

Sources: `gh help formatting` / `gh help exit-codes` / `gh help reference` (gh 2.102.0) · https://kubernetes.io/docs/reference/kubectl/ · https://developer.hashicorp.com/terraform/cli/commands/providers/schema · https://developer.hashicorp.com/terraform/internals/machine-readable-ui · https://developer.hashicorp.com/terraform/internals/json-format · https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-skeleton.html · https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-returncodes.html · https://doc.rust-lang.org/cargo/commands/cargo.html · https://doc.rust-lang.org/cargo/commands/cargo-metadata.html · https://github.com/git/git/blob/master/Documentation/git.adoc · https://docs.npmjs.com/cli/v11/using-npm/config · https://github.com/spf13/cobra/blob/main/doc/yaml_docs.go · https://github.com/spf13/cobra/blob/main/site/content/completions/_index.md · https://github.com/withfig/autocomplete-tools/blob/main/types/index.d.ts · https://github.com/withfig/autocomplete-tools/tree/main/integrations/click · https://github.com/carapace-sh/carapace-spec · https://usage.jdx.dev/spec/ · https://usage.jdx.dev/spec/reference/output · https://usage.jdx.dev/spec/integrations · https://github.com/jdx/usage/blob/main/docs/cli/reference/mcp.md · https://github.com/jdx/usage/blob/main/docs/spec/integrations/cobra.md · https://github.com/gaojunran/usage-integrations · https://github.com/jdx/mise/blob/main/src/cli/usage.rs

## 5. Exit codes and error codes in machine-readable form

- The **usage spec** is the only primary source found with a machine-readable exit code list (`exit_code <n> "<meaning>"`). Its MCP server exposes exit statuses through `describe_command`.
- Everyone else documents exit codes in prose or man pages: gh (`gh help exit-codes`), AWS (a table), cargo (0 and 101), Terraform (`-detailed-exitcode`: 0 no changes, 1 error, 2 changes present).
- Error codes:
  - `rustc` gives every error a code and explains it with `rustc --explain E0308`. Its `--error-format json` prints structured diagnostics.
  - Terraform's `diagnostic` messages share one JSON format with `terraform validate -json`.
  - No CLI found publishes a list of its error codes as JSON (**UNCONFIRMED**).

Sources: https://usage.jdx.dev/spec/reference/output · https://developer.hashicorp.com/terraform/cli/commands/plan · https://doc.rust-lang.org/rustc/command-line-arguments.html · https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-returncodes.html

## 6. Guidance on agent-friendly CLIs and tools

- **Anthropic, "Writing effective tools for AI agents" (2025-09-11)**
  - Build fewer, higher-impact tools rather than wrapping every endpoint.
  - Namespace tool names (`asana_search`, `asana_projects_search`).
  - Return meaningful, human-readable context over opaque IDs.
  - Keep responses token-efficient: pagination, filtering, truncation, and an optional concise or detailed `response_format`.
  - Write error messages that say how to fix the input.
  - Use unambiguous parameter names (`user_id`, not `user`).
  - Write descriptions as if for a new hire.
  - Evaluate with real tasks.
- **Claude Code docs (best practices)**
  - If a system has a CLI, that is usually the easiest way in. For an unfamiliar CLI, pointing Claude at `--help` is enough. MCP is for systems without a CLI.
  - Claude Code's own headless mode offers `--output-format json` (one result object) and `stream-json`.
- **clig.dev (Command Line Interface Guidelines)**
  - Offer `--json` for structured output, and `--plain` where human formatting breaks line tools.
  - Primary output goes to stdout. Messages and logs go to stderr.
  - Exit 0 on success, and map non-zero codes to the important failure modes.
  - Offer `-n`/`--dry-run` for moderately dangerous operations so users can see the changes first.
  - Confirm dangerous actions, or require `--force` or `--confirm=<name>` when not interactive.
  - `--no-input` must never prompt. Help should link to web docs.
- **MCP spec (2026-07-28)**
  - Hosts should keep a human in the loop who can deny tool calls.
  - Input validation and business errors go back as tool results with `isError: true`, so the model can correct itself. Protocol errors are for unknown tools and malformed requests.

Sources: https://www.anthropic.com/engineering/writing-tools-for-agents · https://code.claude.com/docs/en/best-practices · https://clig.dev/ · https://modelcontextprotocol.io/specification/latest/server/tools

## 7. MCP tools and existing Click/Typer-to-MCP mappings

- **Tool definition (spec 2026-07-28)**
  - `name`: 1-128 characters, only `A-Z a-z 0-9 _ - .`, case-sensitive, unique per server.
  - Also optional `title`, `description` and `icons`.
  - `inputSchema` (required): a JSON Schema object whose root must be `"type": "object"`. It defaults to JSON Schema 2020-12 when there is no `$schema`. The recommended schema for a tool without parameters is `{"type": "object", "additionalProperties": false}`.
  - `outputSchema` (optional): if given, the server must return `structuredContent` that conforms to it. A tool returning structured content should also return the serialized JSON in a text block.
  - `annotations`: `title`, `readOnlyHint` (default false), `destructiveHint` (default true, meaningful only when not read-only), `idempotentHint` (default false), `openWorldHint` (default true). Clients must treat annotations as untrusted unless the server is trusted.
- **click-mcp 0.6.1** (Click only)
  - Adds an `mcp` subcommand. Each command becomes a tool, and nested commands use dot names (`users.create`).
  - Mapping rules:
    - Int maps to `integer`, Float to `number`, Bool to `boolean`, anything else to `string`.
    - `Choice` maps to `enum`.
    - `help` becomes `description`.
    - JSON-safe defaults are copied.
    - `required` params are listed in `required`.
    - Hidden params are skipped.
    - Parent group params are merged into each tool.
    - `multiple` is not mapped to an array.
  - Runs a tool in-process with stdout captured and `standalone_mode=False`. Sets no annotations.
- **click-to-mcp** (GitHub only, small project)
  - Same type rules, plus `multiple=True` or `nargs` maps to `{"type": "array", "items": ...}`, and a tuple default becomes a list.
  - Runs a tool through Click's `CliRunner`, rebuilding argv from the arguments.
  - It checks `isinstance(..., click.Group)` on what Typer's `get_command` returns, so it likely fails on Typer >= 0.26 (**UNCONFIRMED**, not run).
- **FastMCP 4.2.0**
  - Builds `inputSchema` from a Python function's type hints through Pydantic: parameters without defaults are required, and Literal/Enum are constrained values.
  - Builds `outputSchema` from the return annotation, and takes `annotations=` with the hints above.
  - Its `generate-cli` goes the other way, from MCP to a cyclopts CLI: simple types become typed flags, arrays become repeatable flags, required stays required.
  - It has no Click/Typer-to-MCP converter.
- **usage mcp**: serves descriptions only (`list_commands`, `describe_command`) and does not run commands. It notes that stdin cannot be used for input, because stdin is the MCP transport.
- Common mapping rules across these projects:
  - Choices become `enum`.
  - Flags become `boolean`.
  - `multiple` or `nargs` become `array`.
  - Help becomes `description`.
  - Defaults are copied when JSON-safe.
  - Required params go in `required`.
  - Hidden params are dropped.
  - Dashes in flag names give way to the Python parameter name as the property key.
  - Positional order is kept on the side, to rebuild argv.

Sources: https://modelcontextprotocol.io/specification/latest/server/tools · https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2026-07-28/schema.ts · https://github.com/crowecawcaw/click-mcp · https://github.com/Coding-Dev-Tools/click-to-mcp · https://gofastmcp.com/docs/servers/tools.md · https://gofastmcp.com/docs/cli/generate-cli.md · https://github.com/jdx/usage/blob/main/docs/cli/reference/mcp.md

## 8. Dry runs in tools that create or change things

- **terraform plan**
  - Computes changes without applying them. `-json` streams `planned_change` messages (address, `action` such as `create`, `update`, `replace` or `delete`) and a `change_summary` (`add`, `change`, `remove`).
  - `terraform show -json <planfile>` gives `resource_changes[].change.actions`, one of `["no-op"]`, `["create"]`, `["read"]`, `["update"]`, `["delete","create"]`, `["create","delete"]` or `["delete"]`, plus `before` and `after`.
  - `-json` implies `-input=false`. The docs advise re-checking the final plan before applying, because things can change in between.
- **kubectl / Kubernetes**
  - `--dry-run=client` prints the object it would send. `--dry-run=server` runs every server stage (defaulting, validation, admission) except storage.
  - It returns "the final object which would have been persisted" with the normal status code.
  - Generated fields (random names from `generateName`, UIDs, timestamps, assigned IPs) "will likely be different" from a real run.
  - Dry run needs the same permissions as the real request.
  - Text mode prints `deployment.apps/demo created (dry run)` (verified locally).
- **npm**: `dry-run` makes no changes and reports what would have happened, for commands that modify the local install (`install`, `update`, `dedupe`, `uninstall`, `pack`, `publish`). Other network commands ignore it. `npm pack --dry-run --json` prints `id`, `name`, `version`, `filename`, `files[]` (`path`, `size`, `mode`), `entryCount` and more (verified locally).
- **uv**
  - `--dry-run` exists on `sync`, `lock`, `pip install`, `pip sync`, `pip uninstall`, `version`, `publish` and `self update` (verified locally on 0.13.7).
  - **`uv init` has no dry run.** `uv init --dry-run` fails with "unexpected argument" (verified locally).
  - Text output says "Would install 14 packages".
  - The JSON from `uv sync --dry-run --output-format json` has top-level `"dry_run": true` and `sync.changes[]` items like `{"name": "click", "version": "8.5.1", "action": "installed"}`. It uses the same action words as a real run.
  - `uv version --dry-run --output-format json` does not mark the dry run in its JSON (verified locally).
- **git**
  - `add -n` shows if files exist and/or would be ignored, printing `add 'a.txt'`. `clean -n` prints `Would remove a.txt`. `push -n` does "everything except actually send the updates". `commit --dry-run` summarizes what would be committed.
  - `git add -n missing.txt` fails exactly like the real command (exit 128) (verified locally).
- **cargo**: `cargo new` has no dry run. `cargo publish --dry-run` performs "all checks without uploading".
- **gh**
  - `gh repo create` has no dry run.
  - `gh pr create --dry-run` prints details instead of creating the PR, but its help warns it "May still push git changes".
- **aws ec2 `DryRun`**: checks permissions and parameters on the server. Success comes back as the error `DryRunOperation`, "Request would have succeeded".
- **ansible `--check`**
  - Modules that support it report what they would change, and `--diff` shows before and after.
  - Modules without check mode support "report nothing and do nothing".
  - Tasks that depend on registered results of earlier tasks can behave differently, since those tasks didn't run.
- **copier `-n`/`--pretend`** ("Run but do not make any changes")
  - Renders the templates and prints `create  README.md` lines.
  - Prints each task (`> Running task 1 of 1: ...`) but skips running it (`if self.pretend: continue`). Files a task would make are not reported. Verified locally and in copier 9.19.1 source.
- **cookiecutter**: no dry run option (`--help` checked locally).
- **Yeoman**
  - Generators write into an in-memory file system, which is written to disk once, after the conflicts stage.
  - `--dry-run` ("Print conflicts") skips the write. `--skip-install` skips dependency installs.
- **Rails generators / Thor `-p`/`--pretend`** ("Run but do not make any changes")
  - Thor's `run` prints `run <command> from "<dir>"` and returns without executing.
  - Rails' app generator skips `bundle install` under `--pretend`.
- **dotnet new `--dry-run`**
  - Runs the same parameter checks and the same overwrite check as a real run, through one `InstantiateAsync` call. It returns `DestructiveChangesDetected` without `--force` in both modes.
  - It computes "creation effects" (file changes) in memory and skips only the write.
  - Output: `File actions would have been taken:` and then `  Create: ./x.csproj` lines, sorted by path, with kinds Create, Change, Delete. Post-actions such as NuGet restore are not run. Each is listed under `Action would have been taken automatically:` with its description.
- **create-vite, create-next-app, create-t3-app**: no dry run. They offer `--no-immediate`, `--skip-install`, `--disable-git`, `--noInstall` and `--noGit` to skip the steps that call other tools.
- **Patterns across these tools**:
  - **Same checks, same failures.** API-backed tools (Kubernetes, AWS, cargo publish, dotnet new) run the real validation and fail the same way.
  - **Generators render their own files in memory** (dotnet, copier, Yeoman) and list them with an action word, usually "create".
  - **Steps that call other tools are listed, not run** (dotnet post-actions, copier tasks, Thor `run`, Rails `bundle install`). Files those tools would make are not predicted or reported.
  - **Nobody simulates in a temp dir.** Kubernetes says plainly that values generated in a dry run differ from the real ones.
  - **No shared JSON shape.** Recurring pieces: a top-level dry-run marker (uv), a list of changes each with a path or name and an action (`create`/`installed`/`["create"]`), and a summary or step list.

Sources: https://developer.hashicorp.com/terraform/cli/commands/plan · https://developer.hashicorp.com/terraform/internals/machine-readable-ui · https://developer.hashicorp.com/terraform/internals/json-format · https://kubernetes.io/docs/reference/using-api/api-concepts/#dry-run · https://docs.npmjs.com/cli/v11/using-npm/config · https://docs.astral.sh/uv/reference/cli/ · https://github.com/git/git/tree/master/Documentation · https://doc.rust-lang.org/cargo/commands/cargo-new.html · https://doc.rust-lang.org/cargo/commands/cargo-publish.html · https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-skeleton.html · https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_checkmode.html · https://github.com/copier-org/copier (`copier/_main.py`) · https://yeoman.io/authoring/file-system.html · https://github.com/yeoman/environment/blob/main/src/cli/command.ts · https://github.com/rails/thor/blob/main/lib/thor/actions.rb · https://github.com/rails/rails/blob/main/railties/lib/rails/generators/app_base.rb · https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-new · https://github.com/dotnet/sdk/blob/main/src/Cli/Microsoft.TemplateEngine.Cli/TemplateInvoker.cs · https://github.com/dotnet/sdk/blob/main/src/Cli/Microsoft.TemplateEngine.Cli/PostActionDispatcher.cs · https://github.com/dotnet/templating/blob/main/src/Microsoft.TemplateEngine.Edge/Template/TemplateCreator.cs · https://github.com/vitejs/vite/blob/main/packages/create-vite/src/index.ts · https://github.com/vercel/next.js/blob/canary/packages/create-next-app/index.ts · https://github.com/t3-oss/create-t3-app/blob/main/cli/src/cli/index.ts

## 9. What aa init would touch (local check)

- `uv init --app --package --python 3.15 --no-workspace --vcs none` writes `.python-version`, `README.md`, `pyproject.toml` and `src/<pkg>/__init__.py`. With `--lib` it also writes `src/<pkg>/py.typed` (verified locally in a scratch folder).
- aa then appends to `pyproject.toml`. `uv add --dev ruff pytest` writes `uv.lock` (and `.venv`, which the template `.gitignore` ignores). aa's templates write `src/<pkg>/__init__.py` and `README.md` over uv's copies, and add `tests/test_<pkg>.py`, `AGENTS.md`, `CLAUDE.md`, `.gitignore`, `.github/workflows/ci.yml` and `LICENSE` (MIT only).
- `tests/test_init.py` already pins the final tracked set in `EXPECTED_FILES` (11 files for a CLI project, plus `py.typed` for a library).
- Checks a real run makes before writing anything: the name rule, `--cli` with `--lib`, `--public` without `--github`, target not empty, outer uv workspace. The git `user.name` check for the MIT holder runs only at the "write files" step, after `git init`, `uv init` and `uv add` have already run.

Sources: local runs of uv 0.13.7 · `packages/aa-toolkit-cli/src/aa_cli/init.py` · `packages/aa-toolkit-cli/tests/test_init.py`

## What this means for aa

**1. The command listing: `aa commands`, aa's own shape, with a JSON Schema per command.**

- Name it `aa commands`. No big CLI has a JSON command listing, so there is no convention to follow (`help --json` and `--help-json` have no primary-source example). A plain noun command is easy to find and matches the `list_commands` tool name in usage's MCP server. It follows the existing contract: `aa commands --json` writes one envelope. Human mode prints a short table.
- Don't reuse Click's `to_info_dict()`. Typer 0.26+ removed it, and its shape changed across Click 8.3 and 8.5 anyway. It also carries Click details (`_click_default_help`, type name `text`) that would leak into aa's contract.
- Don't read `typer._click` types either. Typer 0.29 has already removed `param.type`, and the repo will pick up 0.29 once the cooldown passes.
- Build it from two sources:
  - From `typer.main.get_command(app)`, the tree Typer's own `typer utils docs` uses: command names, help, flag spellings, `required`, `multiple`, `hidden`, positional order.
  - From aa's own command functions through stdlib `typing.get_type_hints`: the types. `bool` maps to boolean, `str` and `Path` to string, a `StrEnum` such as `License` to an `enum` of its values, `list[str]` to an array of strings. `X | None` or a default means not required.
- Back it with one snapshot test of the full `aa commands --json` output, so a Typer upgrade that changes anything fails CI instead of silently changing the contract.
- Suggested shape, inside `data`:
  - `schema_version: 1`, with the cargo/Terraform rule: new fields are not breaking, and readers ignore fields they don't know.
  - `global_options`: `--json`, `--verbose`, `--version`, listed once.
  - `exit_codes`: see point 2.
  - `commands`: one entry per visible command, holding:
    - `name`, `summary` (first docstring line), `usage`.
    - `arguments` (positional names in order) and `options` (property name to flag spelling, e.g. `license_choice` to `--license`).
    - `input_schema`: JSON Schema 2020-12, `type: object`, properties keyed by parameter name, with `description` from help, plus `enum`, `default` and `required`.
    - `effect` (`read` / `write`, the usage spec's words).
    - `errors` (see point 2).
- Leave out hidden commands such as `crash` and the global flags inside each command's schema. Hidden means "not for callers", and that is how click-mcp and the usage spec treat it.
- Publishing a usage spec (KDL) through `usage-spec-typer` is possible later, but it adds a dependency and a second format. Not needed now.

**2. List exit codes, and list error codes too.**

- Exit codes: put the five once at the top, generated from the `ExitCode` enum so they can't drift. The usage spec is the one precedent for a machine-readable list. Everyone else (gh, AWS, cargo) uses prose, which agents can't rely on.
- Error codes: list per command the `error.code` values it can return:
  - `init`: `target_not_empty`, `target_in_workspace`, `step_failed`.
  - `redact`: its file error codes.
  - Global: `usage`, `aborted`, `unexpected`.
- No CLI found publishes error codes this way, so this is aa's own addition. It is cheap, because the envelope already has stable codes, and it lets an agent plan its error handling. Keep the codes in one registry per command that both the command and `aa commands` read.

**3. `aa init --dry-run`: predict and render in memory, run the same checks, list steps.**

- **Approach**: do what dotnet new, copier, Yeoman and Rails do.
  - Run all the same checks.
  - Render aa's own templates in memory, which catches template bugs, without writing.
  - List the external steps (`git init`, `uv init ...`, `uv add --dev ruff pytest`, `git add`) without running them.
  - Don't simulate in a temp dir. It would download Python and packages, fill the uv cache and take time. Kubernetes warns that generated values differ from a real run anyway, and nobody in this survey does it.
- **Files made by uv**: predict them (`.python-version`, `pyproject.toml`, `uv.lock`, `src/<pkg>/__init__.py`, `py.typed` for a library). Compute the package name the way uv does: lowercase, `-` becomes `_`. dotnet and copier don't report files from post-actions or tasks at all. aa can do better because its set is small and already pinned.
  - Keep the prediction honest with a test: the dry-run `files` must equal the real run's `files`, for both `--cli` and `--lib`. `EXPECTED_FILES` in `tests/test_init.py` already exists for that.
  - A uv upgrade that adds a file then fails the test instead of misleading agents.
- **Validate and fail like the real run**: same error codes, same exit codes. That is the Kubernetes, AWS, cargo publish and dotnet behaviour.
  - Move the git `user.name` check (and a "git / uv / gh is on PATH" check) up front into both the real run and the dry run. Today the real run only finds a missing holder after `uv add`. With the check up front, the dry run doesn't promise success that the real run can't deliver.
  - Exit 0 when the plan is fine. Don't copy Terraform's `-detailed-exitcode`.
- **Output shape**: the same `data` as a real run, so an agent can compare the two. Add an explicit marker, because uv's `version` JSON shows that leaving it out confuses readers.

  ```json
  {"ok": true, "data": {
    "dry_run": true,
    "path": "D:\\work\\my-app", "kind": "cli", "github_url": null,
    "files": [
      {"path": ".github/workflows/ci.yml", "action": "create", "source": "aa"},
      {"path": ".python-version", "action": "create", "source": "uv init"},
      {"path": "uv.lock", "action": "create", "source": "uv add"}],
    "steps": [
      {"step": "git init", "command": ["git", "init", "--quiet", "--initial-branch=main"]},
      {"step": "uv init", "command": ["uv", "init", "--app", "--package", "--python", "3.15", "--no-workspace", "--vcs", "none"]}]}}
  ```

  - The `action` word "create" is the one dotnet, copier and Terraform use.
  - Keep `files` sorted by path, like the real run and dotnet.
  - Human mode: `Would create a cli project at <path>`, the file list, then `Would run:` and the commands, like Thor's `run` lines.
  - `files` changes from a list of strings to a list of objects only in the dry run. If that is unwanted, keep `files` as strings in both modes and put the sources in a separate `file_sources` map. That choice is the owner's call.
- **`--github`**: plan only, and never talk to GitHub. Add `initial commit` and `create GitHub repo` steps (`gh repo create <name> --private|--public --source . --push`), with `github_url: null`. Check only that `gh` is on PATH. gh's own `pr create --dry-run` "may still push", which is exactly what an aa dry run must never do. A read-only `gh auth status` check is possible, but it needs the network and is a judgement call (**UNCONFIRMED** that it is worth it).

**4. What makes a later `aa mcp` easy.**

- Each command's `input_schema` above already satisfies MCP's `inputSchema`: a JSON Schema 2020-12 object at the root. `aa mcp` would then be a thin loop over `aa commands`:
  - One tool per command, named `aa_init` and `aa_redact`. That is the namespacing Anthropic recommends, and the characters fit MCP's name rules.
  - Description from the help text.
  - `annotations` from `effect`: `redact` is read-only. `init` is not read-only, not destructive (it only creates in an empty folder), not idempotent (a second run hits `target_not_empty`), and open-world (`uv add`, `gh`).
- Run a tool the way click-mcp and click-to-mcp do: rebuild argv from the arguments (positional order plus the `options` map) and run `aa <command> ... --json`. Then map the envelope:
  - `ok: true` becomes `structuredContent = data`, plus the same JSON as a text block.
  - `ok: false` (usage errors included) becomes `isError: true`, with text `message` and `Fix: fix`. That is the self-correcting kind of error both the MCP spec and Anthropic ask for.
- A `dry_run` boolean on `aa_init` lets an agent preview before a human approves the real call. That fits MCP's human-in-the-loop guidance.
- Plan now for stdin. `aa redact` reads piped text, but under MCP's stdio transport stdin is the protocol, as usage's MCP server notes. A redact tool needs the text as an argument, so give the CLI a way to take text other than stdin before building `aa mcp`.
- `outputSchema` per command is optional and can come later, by describing each command's `data` the same way.
