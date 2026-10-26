# zuke-python

🥷 Zuke for Python: author your build as typed Python, run it on the Zuke engine.

[Zuke](https://github.com/zuke-build/zuke) is a code-first, strongly-typed build
automation system: your build and your CI are one typed file, and your agent can
run it. This package brings that authoring model to Python. A build is a class
whose fields are targets, dependencies are references the type checker sees,
and every tool call is a typed facade. The scheduling, the durable runs, the
locks, the caching, the CI generation, the MCP server and every tool wrapper
stay in the Zuke **engine**; this package is the thin SDK that describes your
build to it and runs your target bodies when asked.

> **Status: scaffolding.** The SDK is gated on the engine learning to host a
> worker written in another language. Until then this package exports only its
> version. The sequencing is described in
> [`AGENTS.md`](./AGENTS.md#status-and-sequencing).

## What it will look like

```python
from zuke import Build, parameter, run, target
from zuke.tools import docker


class CI(Build):
    tag = parameter("image tag").default("dev")

    lint = (
        target().description("ruff").executes(lambda ctx: ctx.sh("ruff", "check", "."))
    )
    test = target().depends_on(lint).executes(lambda ctx: ctx.sh("pytest", "-q"))
    image = (
        target()
        .depends_on(test)
        .executes(
            lambda ctx: docker.build(
                ctx, lambda s: s.tag(f"app:{tag.value}").file("Dockerfile")
            )
        )
    )


run(CI)
```

`./zuke test` then runs the Zuke engine, which starts this file as a worker,
asks it for the graph, and runs `lint` and `test` with every subprocess spawned
by the engine: argv only, output captured and redacted, dry-run, cancellation
and timeouts all handled once, in one place.

## Development

[uv](https://docs.astral.sh/uv/) is the only tool you need.

```sh
uv sync          # the locked environment
uv run poe ci    # the gate: format check, lint, pyright strict, tests at 95%+
```

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the workflow and
[`AGENTS.md`](./AGENTS.md) for the rules this repository is built by.

## License

[MIT](./LICENSE)
