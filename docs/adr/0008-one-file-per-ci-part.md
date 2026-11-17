# aa add ci writes one file per CI part

`aa add ci` sets up several CI parts: the tests, the workflow audit, the dependency audit and Dependabot updates. Each CI part is written to a file of its own, and the command can be told to set up only some of them. One file per CI part is what lets a project add a CI part later: `aa add` never changes a file that already exists (ADR 0006), so if every CI part lived in one combined `ci.yml`, a project that started with only the tests could never add the audit without deleting its CI first. `aa init` writes no CI at all, so `aa add ci` is the one place CI comes from.

## Considered Options

- One combined workflow with a job per CI part. Rejected because adding a CI part later would mean changing a file aa already wrote.
- Lint and tests as separate CI parts. Rejected for now to keep the first version small. It can come later if lint without tests is ever wanted.
- `aa init` keeps writing `ci.yml`, or a smaller one. Rejected because a new project doesn't need CI yet, and two places writing CI would drift apart.
