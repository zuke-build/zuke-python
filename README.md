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

> **Status: in progress.** The engine hosts a worker in any language since
> `@zuke/engine` 1.0.0, and this package is growing into the SDK slice by slice
> under [#3](https://github.com/zuke-build/zuke-python/issues/3). The worker
> loop, the authoring surface, the body context, the hooks, the gates and the
> services are in, the worker passes every conformance case of `@zuke/engine`
> 1.0.0, and this repository's own gate runs as a Zuke build on that engine;
> the tool facades are next. The sequencing is described in
> [`AGENTS.md`](./AGENTS.md#status-and-sequencing).

## What it looks like

```python
from zuke import Build, parameter, run, target
from zuke.tools.docker import DockerTasks


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
            lambda ctx: DockerTasks.build(
                ctx, lambda s: s.tag(f"app:{tag.value}").file("Dockerfile")
            )
        )
    )


run(CI)
```

The class and its fields work today: `target()` carries every setting the
engine schedules by (`depends_on`, `retry`, `timeout`, `before`, `after`,
`triggers`, `on_failure`, …), `parameter()` has the string, number, boolean and
list kinds with `.value` resolved by the engine, `group()` names a parallel
batch, and `run()` makes the file a worker. A body gets a `ctx`: `await
ctx.sh(...)` runs a command through the engine and raises `CommandError` on a
non-zero code, `ctx.state` and `ctx.state_of(...)` read and write durable state,
and `ctx.outcome_of`, `ctx.outcomes`, `ctx.summary`, `ctx.secret`, `ctx.log`,
`ctx.plan` and `ctx.signals` are the rest of what the engine serves a body.
A target may declare a `.condition(...)`, a `.cache_key(...)`, a `.lock(...)`, a
`.waits_for(...)` gate and `.validate_during(...)` checks; `service()` declares
a service with `start`, `ready` and `stop` phases; a `Build` overrides
`on_start`, `on_target_start`, `on_target_end` and `on_finish` for hooks; and
`ci()` fields declare the CI files `zuke generate-ci` renders. `zuke.tools`
holds a facade per engine wrapper, `zuke.tools.docker`, `zuke.tools.deno` and
the rest, generated from the engine's tool spec: `DockerTasks.build(ctx, lambda
s: ...)` sends the engine a `tool.call` naming the wrapper's release, the task
and the setters the lambda called, and the engine runs the real wrapper with
the worker's environment and directory.

`./zuke test` then runs the Zuke engine, which starts this file as a worker,
asks it for the graph, and runs `lint` and `test` with every subprocess spawned
by the engine: argv only, output captured and redacted, dry-run, cancellation
and timeouts all handled once, in one place.

## Development

[uv](https://docs.astral.sh/uv/) is the only tool you need.

```sh
uv sync          # the locked environment
./zuke ci        # the gate: format check, lint, pyright strict, tests at 95%+
./zuke --list    # every target of build.py, this repository's own Zuke build
```

The gate is itself a Zuke build, `build.py`, run by `@zuke/engine` at the
version `zuke.json` pins: the launcher bootstraps Deno, the engine starts
`build.py` as its worker, and every command a target runs goes through the
engine. `./zuke.ps1` is the launcher on Windows.

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the workflow and
[`AGENTS.md`](./AGENTS.md) for the rules this repository is built by.

## License

[MIT](./LICENSE)
