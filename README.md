<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://github.com/zuke-build/zuke/raw/master/assets/logo-white.png" />
  <img width="400px" alt="Zuke" src="https://github.com/zuke-build/zuke/raw/master/assets/logo.png" />
</picture>

> Zuke for Python: author your build as typed Python, run it on the Zuke engine.
> Your build and your CI are one typed file — and your agent can run it.

<p align="center">
  <a href="https://github.com/zuke-build/zuke-python/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/zuke-build/zuke-python/actions/workflows/ci.yml/badge.svg" /></a>
  <a href="https://github.com/zuke-build/zuke-python/actions/workflows/release.yml"><img alt="Release" src="https://github.com/zuke-build/zuke-python/actions/workflows/release.yml/badge.svg" /></a>
  <a href="https://github.com/zuke-build/zuke-python/actions/workflows/ai-review.yml"><img alt="AI review" src="https://github.com/zuke-build/zuke-python/actions/workflows/ai-review.yml/badge.svg" /></a>
  <a href="https://pypi.org/project/zuke/"><img alt="PyPI" src="https://img.shields.io/pypi/v/zuke?logo=pypi&amp;logoColor=white" /></a>
  <a href="https://pypi.org/project/zuke/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/zuke?logo=python&amp;logoColor=white" /></a>
  <a href="https://pypi.org/project/zuke/#provenance"><img alt="Provenance: PEP 740" src="https://img.shields.io/badge/provenance-PEP%20740-2ea44f" /></a>
  <a href="https://microsoft.github.io/pyright/"><img alt="Typed: pyright strict" src="https://img.shields.io/badge/typed-pyright%20strict-4B8BBE" /></a>
  <a href="https://github.com/astral-sh/uv"><img alt="uv" src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json" /></a>
  <a href="https://github.com/astral-sh/ruff"><img alt="Ruff" src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" /></a>
  <a href="https://jsr.io/@zuke/engine"><img alt="Runs on @zuke/engine" src="https://jsr.io/badges/@zuke/engine" /></a>
  <a href="https://github.com/zuke-build/zuke-python/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-yellow.svg" /></a>
  <a href="https://github.com/zuke-build/zuke"><img alt="Part of Zuke" src="https://img.shields.io/badge/part%20of-zuke--build%2Fzuke-000?logo=github" /></a>
</p>

[Zuke](https://github.com/zuke-build/zuke) is a code-first, strongly-typed build automation system: a build is
a class whose fields are targets, dependencies are references the type checker
sees, and the same file generates your CI and serves your build to AI agents.
This package brings that model to **Python**. Write the build as typed Python,
and the Zuke **engine** runs it: scheduling, retries, timeouts, cancellation,
durable runs, locks, caching, services, CI generation, the MCP server and every
tool wrapper live there, implemented once. This package is the thin SDK that
describes your build to the engine and runs your target bodies when asked.

> [!TIP]
> **The main repository, [zuke-build/zuke](https://github.com/zuke-build/zuke), is the centre of the
> project.** The engine, the `zuke` CLI, the tool wrappers, the documentation,
> the website at [zuke.build](https://zuke.build) and the issue tracker for
> anything beyond the Python surface all live there. Start there to learn Zuke;
> come here for the Python side.

## Five minutes to a typed Python build

**1. Install the `zuke` CLI** — pick one. Every route is the same CLI; see the
main repository's [install guide](https://github.com/zuke-build/zuke/blob/master/docs/install.md).

```sh
brew install zuke-build/tap/zuke           # macOS, Linux
choco install zuke                         # Windows
deno install -A -g -n zuke jsr:@zuke/cli   # any OS, with Deno
```

The Homebrew and Chocolatey `zuke` is a standalone binary that carries the
engine and every tool wrapper inside it, so a Python build needs **no Deno at
all**: only Python and uv.

**2. Scaffold a Python project and run it**:

```sh
zuke setup --sdk python   # build.py, zuke.json pinning @zuke/engine, the launchers
zuke                      # run the build
zuke --list               # every target, with its description and dependencies
```

You need [uv](https://docs.astral.sh/uv/); the scaffolded `build.py` carries
inline script metadata, so `uv run build.py` installs this package by itself,
with no project file of its own. Here is a build after replacing the sample
target with real work:

```python
from zuke import Build, ci, parameter, run, target
from zuke.tools.docker import DockerTasks


class CI(Build):
    tag = parameter("image tag").default("dev")
    pipeline = ci().path(".github/workflows/ci.yml")

    lint = (
        target().description("ruff").executes(lambda ctx: ctx.sh("ruff", "check", "."))
    )
    test = target().depends_on(lint).executes(lambda ctx: ctx.sh("pytest", "-q"))
    image = (
        target()
        .depends_on(test)
        .executes(
            lambda ctx: DockerTasks.build(
                ctx, lambda s: s.tag(f"app:{tag.value}").file("Dockerfile")
            )
        )
    )


run(CI)
```

`zuke image` runs `lint`, `test` and `image` in order, every command spawned by
the engine. `zuke graph --output=html` draws the graph, `zuke generate-ci`
writes the workflow the `ci()` field declares, and `zuke mcp` serves the whole
build to an agent as typed tools.

## Why Zuke for Python

- **Typed, refactor-safe dependencies.** `depends_on(lint)` is a reference to
  the sibling field, not a string: pyright sees it, a rename moves every use,
  and a typo is an error before anything runs.
- **Every tool, typed.** `zuke.tools` holds a facade for each of the engine's
  50+ wrappers — Docker, Kubernetes, Terraform, uv-adjacent tooling, the cloud
  CLIs, the AI reviewers — generated from the engine's own tool spec, so the
  Python surface matches the TypeScript one setter for setter.
- **One engine, every guarantee.** Argv-only command execution, output capture
  and secret redaction, dry runs, timeouts and cancellation, durable run
  records with resume, cross-run locks, caching and services are all done once,
  in the engine, for every SDK. The Python side cannot drift from them.
- **Never write CI YAML again.** Declare the pipeline in the build and the
  engine renders GitHub Actions, GitLab CI, Azure Pipelines or Bitbucket YAML;
  `generate-ci --check` fails CI when the committed file drifts.
- **Let your agent run the build.** `zuke mcp` serves your targets, parameters
  and graph over the Model Context Protocol, exactly as for a TypeScript build.
- **No runtime dependencies.** The package is the standard library only, and
  strict-typed end to end.

## Install

| What                                   | How                                                                                       |
| -------------------------------------- | ----------------------------------------------------------------------------------------- |
| The `zuke` CLI                         | `deno install -A -g -n zuke jsr:@zuke/cli`, `brew install zuke-build/tap/zuke`, `choco install zuke` |
| This package, into an existing project | `uv add --dev zuke`, or `pip install zuke`                                                |
| A new project                          | `zuke setup --sdk python`, which writes `build.py`, `zuke.json` and the launchers         |

Python 3.12 or newer. The standalone `zuke` binary runs the build on the
engine compiled into it, with no Deno installed, whenever that engine serves
the `@zuke/engine` release `zuke.json` pins (the same major version, at the pin
or newer); `zuke --version` names it. The committed `./zuke` and `zuke.ps1`
launchers, and a `deno install`ed `zuke`, run the pinned release on Deno
instead, which the launchers download, pinned and checksum-verified, on first
use. `zuke upgrade --engine` moves the pin.

On a machine without the CLI, such as a CI runner, the launchers run the build
the same way: `./zuke ci`, or `./zuke.ps1 ci` on Windows. The generated
workflows call them.

## How it works

```
zuke <target>  ─▶  @zuke/engine (built into the binary, or the pin on Deno)
                      │  starts the worker zuke.json names: uv run build.py
                      ▼
                   build.py  ◀── JSON-RPC 2.0 over loopback ──▶  engine
                   (this SDK)     build.describe, target.run,     scheduling, exec,
                                  exec, tool.call, state, …       wrappers, CI, MCP
```

The engine starts your build file as a **worker** and asks it for the graph.
When a target's turn comes, the engine asks the worker to run its body; the
body's `ctx.sh(...)` and every `*Tasks` call travel back to the engine, which
spawns the process or runs the real wrapper under the run's dry-run, redaction
and cancellation. The worker's stdout and stderr become log lines, so a stray
`print` cannot corrupt the protocol. The protocol and its conformance cases are
defined in the main repository
([`packages/engine`](https://github.com/zuke-build/zuke/tree/master/packages/engine)); this package replays
every case of the engine release it pins.

## The authoring surface

`target()` carries every setting the engine schedules by (`depends_on`,
`retry`, `timeout`, `before`, `after`, `triggers`, `on_failure`, …);
`parameter()` has the string, number, boolean and list kinds, with `.value`
resolved by the engine from flags and environment variables, and `.secret()`
redacts one everywhere; `group()` names a parallel batch; `service()` declares a
service with `start`, `ready` and `stop` phases; `ci()` declares a CI file; and
`run()` makes the file a worker.

A body gets a `ctx`: `await ctx.sh(...)` runs a command through the engine and
raises `CommandError` on a non-zero code; `ctx.state` and `ctx.state_of(...)`
read and write durable state; `ctx.outcome_of`, `ctx.outcomes`, `ctx.summary`,
`ctx.secret`, `ctx.log`, `ctx.plan` and `ctx.signals` are the rest of what the
engine serves a body. A target may declare `.condition(...)`, `.cache_key(...)`,
`.lock(...)`, `.waits_for(...)` and `.validate_during(...)`, and a `Build`
overrides `on_start`, `on_target_start`, `on_target_end` and `on_finish` for
hooks.

`zuke.tools.<wrapper>` is a facade per engine wrapper — `zuke.tools.docker`,
`zuke.tools.deno`, `zuke.tools.gh` and the rest. `DockerTasks.build(ctx, lambda
s: ...)` records the setters the lambda calls and sends the engine one
`tool.call`, which runs the real wrapper with the worker's environment and
directory. The full catalogue, with every task and setting, is the main
repository's [tool reference](https://github.com/zuke-build/zuke/blob/master/docs/tools.md).

## Supply chain

Every release is built by this repository's own Zuke build and uploaded to PyPI
with [trusted publishing](https://docs.pypi.org/trusted-publishers/): no API
token exists. From 1.0.1, each file also carries a
[PEP 740](https://peps.python.org/pep-0740/) provenance attestation, signed from
the release job's identity, which PyPI verifies back to
`zuke-build/zuke-python`'s `release.yml`; see the **Security** tab of a release
on [PyPI](https://pypi.org/project/zuke/). Actions are pinned by commit SHA, the
engine and every wrapper it loads run frozen against the committed `deno.lock`,
and `uv.lock` locks the development environment. See
[`SECURITY.md`](https://github.com/zuke-build/zuke-python/blob/main/SECURITY.md).

## Documentation

The documentation lives in the main repository:

- [Getting started](https://github.com/zuke-build/zuke/blob/master/docs/getting-started.md) — install, scaffold
  (including `zuke setup --sdk python`), and a first build.
- [Core concepts](https://github.com/zuke-build/zuke/blob/master/docs/concepts.md) — the build, target and
  graph model and its execution semantics, the same for every SDK.
- [Tools](https://github.com/zuke-build/zuke/blob/master/docs/tools.md) — every wrapper's tasks and settings.
- [CLI reference](https://github.com/zuke-build/zuke/blob/master/docs/cli.md) — the `zuke` command and a
  build's own CLI.
- [MCP server](https://github.com/zuke-build/zuke/blob/master/docs/mcp.md), [Caching](https://github.com/zuke-build/zuke/blob/master/docs/caching.md),
  [Services](https://github.com/zuke-build/zuke/blob/master/docs/services.md),
  [Durable run state](https://github.com/zuke-build/zuke/blob/master/docs/state.md) and
  [Cross-run locks](https://github.com/zuke-build/zuke/blob/master/docs/locks.md).
- The [engine and its protocol](https://github.com/zuke-build/zuke/tree/master/packages/engine) — how any
  language hosts a build.

The Python surface itself is documented by its docstrings, and pyright and your
editor read them. The website renders them as the
[Python API reference](https://zuke.build/api/python), with a
[Python guide](https://zuke.build/docs/python) beside it: `zuke api_reference`
generates the reference from the docstrings, and each release syncs it to the
website.

## Development

[uv](https://docs.astral.sh/uv/) is the only tool you need.

```sh
uv sync          # the locked environment
zuke ci          # the gate: format check, lint, pyright strict, tests at 95%+
zuke --list      # every target of build.py, this repository's own Zuke build
```

The gate is itself a Zuke build, `build.py`, run by `@zuke/engine` at the
version `zuke.json` pins; `./zuke ci` runs the same gate without the CLI, and
CI runs it on Ubuntu, macOS and Windows. The tool facades are generated from the
engine's tool spec, vendored under `spec/`, and `facades_check` fails the gate
when they drift. The engine, every wrapper it imports, and their `@zuke/core`
run frozen against `deno.lock`; `zuke lock` rewrites it. The same AI reviewers
the main repository runs review this repository's pull requests, from
`build.py`'s `review` target through `zuke.tools.ai`: the SDK's build is
reviewed by the SDK. An engine sync, `build.py`'s `sync_engine`, runs whenever
the engine repository publishes a CLI release, which is what the binary
carries: it vendors
that commit's tool spec, wrapper versions and conformance cases, pins its
engine, regenerates the facades and the lock, and opens one standing pull
request, with an issue, whose gate shows whether the SDK needs work for it.

## Contributing

Contributions are welcome! Start with [`CONTRIBUTING.md`](https://github.com/zuke-build/zuke-python/blob/main/CONTRIBUTING.md)
for the workflow, and please be mindful of the
[Code of Conduct](https://github.com/zuke-build/zuke-python/blob/main/CODE_OF_CONDUCT.md). [`AGENTS.md`](https://github.com/zuke-build/zuke-python/blob/main/AGENTS.md)
holds the coding standards — pyright strict, no `Any` or `cast`, 95%+ coverage,
hermetic tests. Every change starts with an issue. A change to the engine, the
protocol or a tool wrapper belongs in the [main repository](https://github.com/zuke-build/zuke), and reaches
this one through the vendored spec and the pinned engine.

## Security

zuke-python runs inside other people's build pipelines, so supply-chain
integrity is the primary concern. Please report a vulnerability privately,
through the **Security** tab's "Report a vulnerability"; see
[`SECURITY.md`](https://github.com/zuke-build/zuke-python/blob/main/SECURITY.md) for the posture and the process, and
the [main repository's policy](https://github.com/zuke-build/zuke/blob/master/SECURITY.md) for the engine.

## License

MIT — see [`LICENSE`](https://github.com/zuke-build/zuke-python/blob/main/LICENSE).

## Acknowledgements

- **[NUKE](https://nuke.build/)** and its creator
  **[Matthias Koch](https://github.com/matkoch)** — the code-first,
  strongly-typed build model Zuke is an homage to.
- **[uv](https://docs.astral.sh/uv/)**, **[Ruff](https://docs.astral.sh/ruff/)**
  and **[pyright](https://github.com/microsoft/pyright)** — the toolchain this
  package is built, linted and type-checked with.
- **[Deno](https://deno.com/)** and **[JSR](https://jsr.io/)**, which the engine
  runs on and ships from, and **[PyPI](https://pypi.org/)** and the
  [PyPA](https://www.pypa.io/), whose trusted publishing and attestations sign
  this package.

## Community & contact

Questions, ideas, or just want to say hi? Open an
[issue](https://github.com/zuke-build/zuke-python/issues) for the Python side, or one in the
[main repository](https://github.com/zuke-build/zuke/issues) for everything else, or reach out:

<p align="center">
  <a href="https://zuke.build"><img alt="Website" src="https://img.shields.io/badge/Website-zuke.build-000000?style=for-the-badge&amp;logo=googlechrome&amp;logoColor=white" /></a>
  <a href="mailto:contact@zuke.build"><img alt="Email" src="https://img.shields.io/badge/email-contact@zuke.build-8B89CC?style=for-the-badge&amp;logo=protonmail&amp;logoColor=white" /></a>
  <a href="https://todorov.bg"><img alt="Blog" src="https://img.shields.io/badge/Blog-todorov.bg-000000?style=for-the-badge&amp;logo=rss&amp;logoColor=white" /></a>
  <a href="https://twitter.com/totollygeek"><img alt="X" src="https://img.shields.io/badge/@totollygeek-000000?style=for-the-badge&amp;logo=x&amp;logoColor=white" /></a>
  <a href="https://www.linkedin.com/in/totollygeek"><img alt="LinkedIn" src="https://custom-icon-badges.demolab.com/badge/totollygeek-0A66C2?style=for-the-badge&amp;logo=linkedin-white&amp;logoColor=white" /></a>
  <a href="https://infosec.exchange/@totollygeek"><img alt="Mastodon" src="https://img.shields.io/badge/@totollygeek-6364FF?style=for-the-badge&amp;logo=mastodon&amp;logoColor=white" /></a>
  <a href="https://www.threads.net/@totollygeek"><img alt="Threads" src="https://img.shields.io/badge/@totollygeek-000000?style=for-the-badge&amp;logo=threads&amp;logoColor=white" /></a>
  <a href="https://bsky.app/profile/totollygeek.com"><img alt="Bluesky" src="https://img.shields.io/badge/totollygeek.com-0285FF?style=for-the-badge&amp;logo=bluesky&amp;logoColor=white" /></a>
  <a href="https://linktr.ee/totollygeek"><img alt="Linktree" src="https://img.shields.io/badge/totollygeek-39E09B?style=for-the-badge&amp;logo=linktree&amp;logoColor=white" /></a>
</p>

<details>
<summary><strong>Swag, sponsoring, star history &amp; contributors</strong></summary>

### Swag

Zuke has a swag shop! Grab some Zuke-branded apparel and accessories and wear
the build:

<p align="center">
  <a href="https://totollyshop.myspreadshop.net/"><img alt="Zuke swag shop" src="https://img.shields.io/badge/Swag_shop-totollyshop.myspreadshop.net-F5A623?style=for-the-badge" /></a>
</p>

### Sponsoring

If Zuke saves you time, you can support its development through
[GitHub Sponsors](https://github.com/sponsors/totollygeek),
[Buy Me a Coffee](https://buymeacoffee.com/totollygeek) or
[Patreon](https://www.patreon.com/totollygeek) — the **Sponsor** button at the
top of the repository lists them all.

### Star history

[![RepoStars](https://repostars.dev/api/embed?repo=zuke-build%2Fzuke-python&theme=dark)](https://repostars.dev/?repos=zuke-build%2Fzuke-python&theme=dark)

If Zuke for Python is useful to you, consider **starring this repository** and
[the main one](https://github.com/zuke-build/zuke) — it helps others find the project. ⭐

### Contributors

<a href="https://github.com/zuke-build/zuke-python/graphs/contributors">
  <img alt="Contributors" src="https://contrib.rocks/image?repo=zuke-build/zuke-python" />
</a>

</details>
