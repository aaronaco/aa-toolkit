# Allow only listed GitHub Actions and require pinned actions

The toolkit's repo only runs GitHub Actions the owner has chosen. Before this, the repo allowed any action, so a pull request could bring in a new one and it ran. zizmor reports unpinned actions but can't stop a new one. With an allow list, a new third-party action fails at job start until the owner adds it on purpose. Repo settings aren't in git, so this ADR records them. This applies to the toolkit's repo only: `aa init` and the projects it sets up don't change.

## Settings

Settings → Actions → General. Read them with `gh api repos/aaronaco/aa-toolkit/actions/permissions` and `gh api repos/aaronaco/aa-toolkit/actions/permissions/selected-actions`.

| Setting | Before | Now |
|---|---|---|
| Allowed actions (`allowed_actions`) | `all` | `selected` |
| Allow actions created by GitHub (`github_owned_allowed`) | not used | on |
| Allow Marketplace actions by verified creators (`verified_allowed`) | not used | off |
| Patterns (`patterns_allowed`) | not used | `astral-sh/setup-uv@*`, `SonarSource/sonarqube-scan-action@*`, `zizmorcore/zizmor-action@*` |
| Require actions to be pinned to a full-length commit SHA (`sha_pinning_required`) | off | on |

- "Created by GitHub" covers the `actions` and `github` organizations, so `github/codeql-action`, which zizmor-action calls, keeps working.
- Verified creators stay off. GitHub calls the badge a signal, not a guarantee.
- Patterns end in `@*`, not a tag. GitHub checks locked workflows against the locked commits, so a tag entry like `@v8` doesn't match.
- Local actions (`uses: ./…`) and actions in repos owned by `aaronaco` are always allowed, so a pull request can add one without an allow-list entry. GitHub adds that rule itself.
- Pinning is a backstop. The Require lockfile policy already makes every workflow run locked commits, and GitHub counts a lockfile as pinned. If that Preview policy is turned off or changes, pinning still refuses a `uses:` line that names only a tag and has no lockfile entry.

With pinning on, CodeQL default setup and every workflow on `main` still pass. The dependency graph update and Dependabot's GitHub Actions check hadn't run yet when this was written. If either fails because of pinning, turn pinning off, keep the allow list, and record here which one broke.

To apply the settings from scratch, set the permissions first. GitHub refuses the selected-actions call until `allowed_actions` is `selected`.

```bash
gh api -X PUT repos/aaronaco/aa-toolkit/actions/permissions -F enabled=true -f allowed_actions=selected -F sha_pinning_required=true
```

```bash
gh api -X PUT repos/aaronaco/aa-toolkit/actions/permissions/selected-actions --input - <<'EOF'
{"github_owned_allowed": true, "verified_allowed": false, "patterns_allowed": ["astral-sh/setup-uv@*", "SonarSource/sonarqube-scan-action@*", "zizmorcore/zizmor-action@*"]}
EOF
```

The second call replaces the whole pattern list, so always send every pattern.

## How the checks fit together

| Check | Runs | Catches |
|---|---|---|
| Allow list | at job start (repo setting) | an action the owner hasn't chosen, even when it's locked and pinned |
| Require lockfile policy | at job start (repo setting) | a workflow that isn't in `actions.lock`, or a step that would run a commit other than the locked one |
| Pinning requirement | at job start (repo setting) | a `uses:` line with no full commit SHA and no lockfile entry, if the lockfile policy is ever off |
| `actions-lock verify` | `actions-lock` workflow, on every pull request | a lockfile out of sync with the workflows, or a locked commit no longer in its upstream ref's history |
| zizmor | prek hook and `zizmor` workflow | risky workflow code, like template injection, wide permissions, kept credentials and actions with known advisories |

The lockfile and pinning decide which commit runs, but not whether the owner chose the action. The allow list decides which actions may run, but not which commit. zizmor reads the workflow code and stops nothing at run time.

## Adding an action

1. Add `owner/action@*` to the allow list, in the settings page or with the selected-actions call above. Do it before the pull request that uses the action runs, or its job fails at start. Actions created by GitHub don't need this step.
2. Add the `uses:` line, run `gh actions-lock`, and commit the workflow and the lockfile together.
3. Add the pattern to the Settings table and the selected-actions call here.

When the last workflow stops using an action, take its pattern off the list.

## When an allowed action is compromised

Add a block entry for the bad commit to the patterns: `!owner/action@<sha>`. GitHub evaluates block entries last, so it blocks that commit even though `owner/action@*` allows the action. Then relock to a good commit, or remove the action.

## When a second maintainer joins

Add a CODEOWNERS file that covers the workflows and the lockfile (`.github/workflows/`), and the files that set Actions policy in git (`.github/dependabot.yml` and this ADR). Then turn on "Require review from Code Owners" in the "Protect main" ruleset. Until then CODEOWNERS would do nothing: GitHub never asks a pull request's author to review it, and the owner writes every pull request.

## Considered Options

- **Keep allowing all actions and rely on zizmor**: rejected, because zizmor reports problems but can't stop a new action from running.
- **Also allow verified creators**: rejected, because GitHub calls the badge a signal, not a guarantee.
- **Tag patterns like `astral-sh/setup-uv@v10`**: rejected, because locked workflows are checked against commits and tag entries don't match.
- **Leave pinning off, since the lockfile already pins**: rejected while it costs nothing, because the Require lockfile policy is in Preview and could change.

## Consequences

Every new action needs an owner step before its first run, which is the point. Dependabot version bumps keep working, because the patterns allow every version.

GitHub's docs don't say whether patterns are case-sensitive. The lockfile writes `sonarsource/sonarqube-scan-action` in lowercase and the list says `SonarSource/…`, and the SonarQube job passes, so at least this case matches. The docs also don't say whether the allow list and pinning check actions nested inside other actions. The only nested one today is `github/codeql-action`, which is GitHub-owned and locked, so it passes either way. A new action that calls a third-party action may need that action on the list too.
