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

**App**:
A program someone runs, as opposed to a library that other code imports. An app decides how its logs look and where they go.
_Avoid_: program, service

**Project**:
A repo that `aa init` set up.
_Avoid_: repo (when you mean a project), workspace

**Release**:
Choosing a project's next version, recording its changelog and tagging it.
_Avoid_: ship, deploy

**Publish**:
Uploading a built artifact of a release to a place others install it from.
_Avoid_: ship, deploy, release
