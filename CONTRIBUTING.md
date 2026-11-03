# Contributing to zuke-python

Thanks for your interest in improving zuke-python! This project is the Python
SDK for [Zuke](https://github.com/zuke-build/zuke), the code-first,
strongly-typed build automation system, and contributions of all kinds — bug
reports, docs, tests, and code — are welcome.

By participating, you agree to abide by our
[Code of Conduct](./CODE_OF_CONDUCT.md).

> [!NOTE]
> The engine, the protocol and every tool wrapper live in the
> [main repository](https://github.com/zuke-build/zuke). A change to any of
> them lands there first and reaches this one through the pinned engine
> release and the vendored tool spec; see
> [how the SDK relates to the engine](./AGENTS.md#how-the-sdk-relates-to-the-engine).

> [!IMPORTANT]
> **Every change starts with an issue.** Before opening a pull request — for a
> feature, a bugfix, documentation, a refactor, or any other work — file an
> issue from
> [the templates](https://github.com/zuke-build/zuke-python/issues/new/choose)
> so the problem, the proposed shape, and the acceptance criteria are agreed
> before you invest the effort. The pull request then closes it.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — the only tool you need. It installs the
  pinned Python and every development dependency from the lock.

## Getting started

```sh
git clone https://github.com/zuke-build/zuke-python
cd zuke-python
uv sync          # create the environment from uv.lock
uv run poe ci    # run the full gate to confirm a clean baseline
```

## Development workflow

| Task                        | Command                                   |
| --------------------------- | ----------------------------------------- |
| Run tests with coverage     | `uv run poe test`                         |
| Type-check                  | `uv run poe check`                        |
| Format / check formatting   | `uv run poe fmt` / `uv run poe fmt:check` |
| Lint                        | `uv run poe lint`                         |
| Full pre-commit / CI gate   | `uv run poe ci`                           |
| Regenerate `uv.lock`        | `uv lock`                                 |

**Run `uv run poe ci` before opening a pull request — it must be green.** It is
the same gate CI's `ci` job runs on Ubuntu, macOS and Windows, so a green run
locally means a green CI run.

## Coding standards (non-negotiable)

The full list, with the reasoning, is in
[`AGENTS.md`](./AGENTS.md#coding-guidelines-non-negotiable). In short:

1. Strict, strongly-typed Python: pyright `strict` is clean, no `Any`, `cast`
   or `type: ignore` in `src/`, every function annotated.
2. The gate always passes, and coverage stays at 95%+ lines and branches.
3. Every public symbol has a docstring; every file carries the copyright and
   license header.
4. Tests are hermetic: no network, no ambient tools, a fake engine over a
   loopback socket rather than a real one.
5. No dead code and no duplicated logic.

## Commit messages

We follow [Conventional Commits](https://www.conventionalcommits.org/) and the
repository squash-merges pull requests, so the PR title and description become
the squash commit that release-please parses.

- Use the imperative mood and explain the _why_, not just the _what_.
- Keep commit bodies to prose. **Do not put code snippets in commit message
  bodies** — release-please uses a strict parser, and a code fragment with
  parentheses can make it silently drop the whole commit from the release. Put
  illustrative code in the PR discussion instead.
- Keep changes small and focused so they stay reviewable.

## Pull requests

1. File the issue that describes the work (feature request, bug report, or
   chore) if one does not exist yet.
2. Fork and create a topic branch from `main`.
3. Make your change, adding tests and docs in the same PR.
4. Run `uv run poe ci` and make sure it is green.
5. Open a pull request with a clear description of the change and its
   motivation, closing the issue with `Closes #<n>`.
6. Update `README.md` and the docstrings whenever behaviour changes.

## Code review

Every change reaches `main` through a pull request — there is no direct push
path. Each PR is reviewed by the required CI gate (the same one you run
locally) and a human maintainer, who reads the diff and every reviewer finding.
Once this repository's build is a Zuke build, the same AI reviewers as the main
repository post assessments here too; their findings are advisory, and a
maintainer addresses or answers each one, quoting its id.

A PR merges only when the required status checks are green, every reviewer
finding has been fixed or answered, and a maintainer approves.

## Reporting bugs and requesting features

- Search [existing issues](https://github.com/zuke-build/zuke-python/issues)
  first.
- For bugs, include a minimal reproduction, the Python and engine versions, and
  what you expected versus what happened.
- A bug in the engine or in a tool wrapper belongs in the
  [main repository](https://github.com/zuke-build/zuke/issues); the facades
  here are generated from it.

## Security

Please **do not** open public issues for security vulnerabilities. Follow the
private reporting process in [`SECURITY.md`](./SECURITY.md) instead.

## Developer Certificate of Origin

Contributions are accepted under the
[Developer Certificate of Origin 1.1](https://developercertificate.org/) (DCO).
By opening a pull request you certify that you wrote the contribution (or
otherwise have the right to submit it) and that you may license it under this
project's [MIT License](./LICENSE). A `Signed-off-by:` trailer (`git commit -s`)
is welcome as an explicit record, but submitting the pull request itself
constitutes your certification.

## License

By contributing, you agree that your contributions will be licensed under the
project's [MIT License](./LICENSE).
