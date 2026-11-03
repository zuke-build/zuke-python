# Security Policy

zuke-python runs inside other people's build pipelines, as a worker the Zuke
engine spawns, so supply-chain integrity is the primary concern. This document
describes how to report problems and how the project is hardened. The engine's
own posture, which covers everything the SDK delegates to it, is described in
the [main repository's security policy](https://github.com/zuke-build/zuke/blob/master/SECURITY.md).

> zuke-python is largely AI-written. Review before you rely on it.

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue.

- Use GitHub's **"Report a vulnerability"** button under the repository's
  **Security** tab (Private Vulnerability Reporting). This opens a private
  advisory visible only to you and the maintainers.
- Include affected version(s), reproduction steps, and impact. A minimal proof
  of concept helps us triage quickly.
- A problem in the engine, the protocol or a tool wrapper should be reported to
  the [main repository](https://github.com/zuke-build/zuke/security/advisories/new)
  instead; the SDK only forwards to them.

We aim to acknowledge a report within a few days and to coordinate a fix and
disclosure timeline with you. Fixes ship in a new release; the advisory is
published once a patched version is available.

**Credit:** reporters are credited by name in the published advisory (and in the
release notes of the fix) unless they ask to remain anonymous.

## Supported versions

Only the **latest** published version of `zuke` on PyPI receives security
fixes.

## Supply-chain posture

- **No runtime dependencies.** The package uses the Python standard library
  only, so there is no third-party code in the worker a build runs.
- **Locked development environment.** The tools that build, lint and test the
  package are pinned in `uv.lock`, and CI installs them with `uv sync --locked`,
  which refuses a lock that disagrees with `pyproject.toml`.
- **Locked engine and wrappers.** `deno.lock` pins `@zuke/engine` at the
  version `zuke.json` names, every `@zuke/<tool>` release `spec/engine.json`
  names (the engine imports them as a target calls them), and the `@zuke/core`
  they resolve, with integrity hashes. The launchers run the engine with
  `--lock=deno.lock --frozen`, so a release that is missing from the lock or
  differs from its hash fails the run instead of being fetched. The gate's
  `lock_check` fails when the lock is absent, misses a release, or differs
  from the commit.
- **No shell strings.** Every subprocess a build runs goes through the engine as
  a discrete argv array; the SDK never builds a shell command line.
- **Loopback only, per-run token.** The worker connects to the engine on
  `127.0.0.1` with a token the engine minted for that run and handed over in
  the environment; the engine accepts exactly one connection and closes the
  listener.
- **Pinned GitHub Actions.** Every action in `.github/workflows/` is pinned to
  a commit SHA with its version in a comment, and Dependabot bumps them. Jobs
  run with `permissions: {}` at the workflow level and the minimum each job
  needs, with egress audited by `step-security/harden-runner`.
- **Trusted publishing.** Once the package publishes, it will do so to PyPI
  through OIDC trusted publishing from this repository's release workflow, with
  no long-lived token stored.

## Hardening checklist for maintainers

- **Require 2FA** for all maintainers, on both GitHub and PyPI.
- **Branch protection** on `main`: required status checks, no direct pushes.
- **Scope the PyPI trusted publisher** to this repository and its release
  workflow only.
