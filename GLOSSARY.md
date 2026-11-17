# aa toolkit

A personal developer toolkit: one CLI that standardizes how projects are set up, committed and released, plus small libraries that any project can use on its own.

## Language

**Toolkit**:
The whole collection of the `aa` CLI and the aa libraries, developed together.
_Avoid_: monorepo, framework

**Library**:
An aa package that can be installed and used on its own, without the CLI or any other aa library.
_Avoid_: engine, module, core

**Log library**:
The library that gives an app a ready-made logging setup.
_Avoid_: log engine, logger (when you mean the library)

**Redaction library**:
The library that takes sensitive values out of text and data before they leave an app.
_Avoid_: anonymizer, scrubber, sanitizer

**Detector**:
The part of the redaction library that finds one kind of sensitive value in text. It can be built in or added by an app.
_Avoid_: recognizer, scanner, adapter

**Sensitive name**:
A field name whose value is always redacted, whatever the value looks like.
_Avoid_: blocklist, mask key

**Known value**:
A sensitive value an app already holds and asks to have redacted wherever it appears.
_Avoid_: deny list

**Placeholder**:
The text left where a redacted value used to be, naming only what kind of value it was, such as `[EMAIL]`.
_Avoid_: mask, token

**Finding**:
One sensitive value found in a text, given by its kind and where it sits, never by the value itself.
_Avoid_: match, hit, detection

**Settings library**:
The library that gives an app its Settings from the environment, a `.env` file, the Secret store and defaults, in that order.
_Avoid_: config library, vault, configuration

**Setting**:
One named value an app reads when it starts, such as a database URL.
_Avoid_: config value, option, variable

**Secret**:
A Setting that shows as `[REDACTED]` wherever it's printed, logged or saved. Only code that asks for its real value gets it, and that code has to keep it hidden itself.
_Avoid_: credential, password (when you mean any Secret), sensitive setting

**Secret store**:
The place the operating system keeps secrets for the signed-in user, such as Windows Credential Manager.
_Avoid_: vault, keyring, keychain, wallet

**App**:
A program someone runs, as opposed to a library that other code imports. An app decides how its logs look and where they go.
_Avoid_: program, service

**Project**:
A Python repo with a `pyproject.toml` at its root, whether `aa init` made it or not.
_Avoid_: repo (when you mean a project), workspace

**Piece**:
One self-contained thing `aa add` puts into a project, such as the log setup or the CI workflow.
_Avoid_: feature, add-on, extra, plugin, module

**Output contract**:
The promise every `aa` command keeps to whoever runs it, whether a person, a script or an agent: one machine-readable answer when asked for one, logs kept apart from that answer, the same exit codes everywhere, and never waiting for input no one can give.
_Avoid_: contract (on its own, or for anything else), API, interface

**Crash report**:
The file `aa` saves on the user's computer when a command fails with an unexpected error. It holds what's needed to fix the bug, with sensitive values taken out, and is never uploaded.
_Avoid_: crash log, dump, bug report, telemetry

**Finished branch**:
A local branch whose last commit is one of the commits of a pull request GitHub shows as merged, with no open pull request containing that commit. `aa prune` removes only finished branches and their worktrees, and only when nothing would be lost.
_Avoid_: merged branch (git calls a branch merged only when its commits are on the default branch, which a squash merge never does), stale branch, dead branch

**Release**:
Choosing a project's next version, recording its changelog and tagging it.
_Avoid_: ship, deploy

**Publish**:
Uploading a built artifact of a release to a place others install it from.
_Avoid_: ship, deploy, release
