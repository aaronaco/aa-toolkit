# Projects pin actions by commit, not with the actions lockfile

The workflows `aa add ci` writes pin every action to a full commit SHA in the `uses:` line, with the version in a comment, and the Dependabot CI part keeps those pins current. The toolkit's own repo pins differently, with version tags and `actions.lock` (ADR 0003). The lockfile needs a preview gh extension on the developer's machine and a repo setting that aa can't write from files, so a project would get a lockfile nothing enforces. A commit pin works with no setup, and zizmor, Dependabot and GitHub's pinning setting all read it.

## Consequences

The pins in the toolkit's workflow templates have to stay current too, or new projects start on old actions. The templates are plain `.yml` files in a folder of their own, and the toolkit's Dependabot config lists that folder, so the same monthly PR that bumps the toolkit's workflows bumps the templates. For a folder other than the root, Dependabot reads the `.yml` files directly inside it, not a `.github/workflows` folder under it. If Dependabot ever stops updating that folder, the fallback is a test that fails when a template's pins don't match `actions.lock`.
