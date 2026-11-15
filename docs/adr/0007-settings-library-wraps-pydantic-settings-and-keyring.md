# The settings library wraps pydantic-settings and keyring

The Settings library is built on pydantic-settings, which already reads Settings from the environment, a `.env` file and defaults in a fixed order and validates them, and on keyring, which already reads and writes Windows Credential Manager. We add only what neither has: a Secret type that shows `[REDACTED]`, a source that fills Secrets from the Secret store, our defaults, and errors that never show a value. This makes it the first library with third-party dependencies, unlike the redaction library (ADR 0004): there, a small pattern library was cheaper than adopting a heavy engine, but here the existing libraries are the standard ones and writing our own would only repeat them. It replaces the separate config and vault libraries that ADR 0001 names as examples.

## Considered Options

- **Our own settings loader on the standard library**: rejected, because priority order, `.env` parsing and type checking are what pydantic-settings already does, and apps and agents already know how to use it.
- **Calling the Windows credential API directly**: rejected, because keyring already wraps it and also covers macOS and Linux if the toolkit ever leaves Windows.
- **Two libraries, one for Settings and one for Secrets**: rejected, because a Secret is a Setting that comes from one more place, so the vault would only be a source inside the settings library.

## Consequences

An app gets about ten packages on Windows, including pydantic's compiled core. The library still never imports the log or redaction libraries (ADR 0001): a Secret shows `[REDACTED]` on its own, and the app connects the redaction library to its logs.

pydantic's validation errors keep the raw input in `.errors()` and `.json()` even with `hide_input_in_errors`, so the library raises its own error built without inputs. Credential Manager holds at most 1280 characters per secret, so a private key file doesn't fit. GitHub reports typing-extensions, which pydantic needs, under a license string the dependency review policy rejects, so the policy allows that one package by name instead of widening the license list.
