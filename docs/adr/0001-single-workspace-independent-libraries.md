# Single uv workspace with fully independent libraries

The toolkit lives in one uv workspace (one repo, one lockfile) instead of one repo per package, to avoid multi-repo overhead for a solo maintainer. The libraries (log, config, vault) must still be installable and usable on their own, so none of them may import another; only the CLI depends on its siblings. Libraries log through stdlib `logging` rather than the log library, and anything that needs two libraries together is wired up in the CLI.

## Considered Options

- **One repo per package**: rejected, too much repo, CI and release overhead for one person.
- **One package with submodules**: rejected, because a project that only wants the vault would have to install everything.

## Consequences

All workspace members share one `.venv`, so an undeclared sibling import still works locally. CI must install each library in isolation, and an import-linter independence contract must forbid cross-imports.
