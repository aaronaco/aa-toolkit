# aa add never edits a project's own code

`aa add` changes a project in only two ways: through uv, which updates `pyproject.toml` and `uv.lock`, and by writing new files that don't exist yet, such as a CI workflow. Anything else a piece needs, like the call that starts logging or lines for `.gitignore`, is printed as next steps for the person to add by hand. Projects come from anywhere, so aa can't know where an app starts or how its files are laid out. Placing code safely in files like that takes a code-rewriting engine with a preview mode, which is far more than this toolkit needs, and a wrong guess would quietly change someone's app. Package managers already edit their own files this way, and tools that set up a framework commonly finish by suggesting the next steps.

## Considered Options

- Edit the entry point when there's exactly one and print otherwise. This was rejected because the command would then behave two different ways, and the edit could still land in the wrong place.
- Append to `.gitignore`. This was rejected to keep a single rule: aa touches only uv's files and new files.
