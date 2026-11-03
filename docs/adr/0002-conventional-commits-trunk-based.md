# Conventional Commits and trunk-based flow

Projects use Conventional Commits because AI agents already write them without extra instructions and existing changelog and version tools read them as is. Projects are trunk-based (short branches merged into `main`, releases cut from `main`) because a `dev` integration branch only adds promotion PRs for a solo maintainer.

## Considered Options

- **A custom commit format**: rejected, because agents would need extra instructions to follow it and standard changelog tools couldn't read it.
- **A `dev` → `main` branching flow**: rejected, because promoting from `dev` to `main` adds a PR for every release with no second person to review it.
