# aa toolkit

A personal developer toolkit: one CLI that standardizes how projects are set up, committed and released, plus small libraries that any project can use on its own.

## Language

**Toolkit**:
The whole collection of the `aa` CLI and the aa libraries, developed together.
_Avoid_: monorepo, framework

**Library**:
An aa package that can be installed and used on its own, without the CLI or any other aa library.
_Avoid_: engine, module, core

**Project**:
A repo that `aa init` set up and that carries aa project config. A repo without that config is just a repo.
_Avoid_: repo (when you mean a project), workspace

**Check**:
One condition `aa doctor` verifies about the machine or a project, which either passes or fails and comes with the command that fixes it.
_Avoid_: test, validation, lint

**Release**:
Choosing a project's next version, recording its changelog and tagging it.
_Avoid_: ship, deploy

**Publish**:
Uploading a built artifact of a release to a place others install it from.
_Avoid_: ship, deploy, release
