# aa add ci writes one file per Check

`aa add ci` sets up several Checks: the tests, the workflow audit, the dependency audit and Dependabot updates. Each Check is written to a file of its own, and the command can be told to set up only some of them. One file per Check is what lets a project add a Check later: `aa add` never changes a file that already exists (ADR 0006), so if every Check lived in one combined `ci.yml`, a project that started with only the tests could never add the audit without deleting its CI first. `aa init` writes no CI at all, so `aa add ci` is the one place CI comes from.

## Considered Options

- One combined workflow with a job per Check. Rejected because adding a Check later would mean changing a file aa already wrote.
- Lint and tests as separate Checks. Rejected for now to keep the first version small. It can come later if lint without tests is ever wanted.
- `aa init` keeps writing `ci.yml`, or a smaller one. Rejected because a new project doesn't need CI yet, and two places writing CI would drift apart.
