# Security policy

## Reporting a vulnerability

Report a vulnerability through the private report form: <https://github.com/aaronaco/aa-toolkit/security/advisories/new>. It is the only channel. Don't report vulnerabilities in public issues, pull requests or discussions.

## What to include

- The affected version or commit.
- Steps to reproduce.
- The impact.
- A proof of concept, if you have one.
- Any known mitigations.

## Supported versions

Only the latest `main` is supported. There are no releases yet.

## What to expect

You get an acknowledgement within 7 days. A confirmed vulnerability is fixed in a private GitHub security advisory, released, and the advisory is then published, with a CVE requested through GitHub when one applies. The default is disclosure within 90 days of the report. That is a starting point to agree on with you, not a hard deadline.

## Scope

In scope are the `aa` CLI, the libraries, the templates `aa init` writes and the toolkit's GitHub Actions workflows. A bug in a template is a toolkit bug. Bugs in third-party tools the toolkit runs, such as uv, gh and git, go to those projects.

## Credit

Reporters are credited in the advisory unless they ask to stay anonymous.

## Bounty

There is no bug bounty.
