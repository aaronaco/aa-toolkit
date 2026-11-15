# aa-toolkit-cli

The `aa` command. See the toolkit README for how to install and develop it.

## Crash reports

When a command fails with an unexpected error (exit code `3`), `aa` saves a Crash report and puts its full path in the error's `fix` field (the `Fix:` line in human mode). Usage errors and Ctrl+C don't save one. Nothing is uploaded.

- **Where:** `%LOCALAPPDATA%\aa\crash\`, one Markdown file per crash, named by date and time (`2026-11-16-141205.md`). Only the newest 10 are kept.
- **What it holds:** the aa version, the Python version, the Windows build, the command name without its arguments (`aa init`, never `aa init my-app`), the error message and the traceback. Never local variables or environment variables.
- **What's taken out:** the home folder path becomes `[HOME]`, the computer name becomes `[COMPUTER]`, and the error message and traceback go through the same cleaning as `aa redact`. No tool catches everything, so read the file before you post it.

If the report can't be saved, `aa` answers as it would without one, with no `fix`.
