# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""Python twins of the engine's conformance manifests.

A case's manifest is what the engine's scripted fake worker answers to
``build.describe``, script keys included. :func:`twin` builds the ``Build``
subclass a user would write for it, through the public surface only, and
:func:`expected` is the manifest with the script keys stripped, which is what
the twin must describe.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from pathlib import Path

from zuke import (
    Build,
    Ci,
    Context,
    LockSettings,
    Parameter,
    Service,
    ServiceContext,
    Target,
    WaitSettings,
    ci,
    group,
    parameter,
    service,
    target,
)
from zuke._dsl import Body
from zuke._facade import call as tool_call
from zuke._guard import is_list
from zuke._guard import string as field
from zuke._guard import strings as field_strings
from zuke._rpc import RpcError, is_record
from zuke._settings import Configure

CASES = Path(__file__).parent / "protocol" / "cases"

SCRIPT_KEYS = frozenset(
    {
        "exec",
        "expectStdout",
        "barrier",
        "fail",
        "failTimes",
        "execAs",
        "condition_answer",
        "cacheKey_answer",
        "calls",
        "settings",
        "wait_answer",
        "validate_fail",
        "service_handle",
        "ready_answers",
        "crash_exit",
        "hangup",
        "sleep_ms",
    }
)
"""The fake worker's per-target script keys, which are not manifest."""


def cases() -> list[str]:
    return sorted(p.stem for p in CASES.glob("*.json"))


def manifest_of(case: str) -> dict[str, object]:
    loaded: object = json.loads((CASES / f"{case}.json").read_text())
    assert is_record(loaded) and is_record(loaded["manifest"])
    return loaded["manifest"]


def expected(manifest: dict[str, object]) -> dict[str, object]:
    """The manifest without the script keys."""
    clean = {k: v for k, v in manifest.items() if k != "failHook"}
    clean["targets"] = [
        {k: v for k, v in t.items() if k not in SCRIPT_KEYS}
        for t in records(manifest["targets"])
    ]
    return clean


def records(value: object) -> list[dict[str, object]]:
    assert is_list(value)
    return [item for item in value if is_record(item)]


def strings(value: object) -> list[str]:
    assert is_list(value)
    return [item for item in value if isinstance(item, str)]


def twin(manifest: dict[str, object]) -> type[Build]:
    """The ``Build`` subclass a user would write for ``manifest``."""
    fields: dict[str, object] = {}
    parameters: dict[str, Parameter] = {}
    for p in records(manifest.get("parameters", [])):
        parameters[str(p["name"])] = twin_parameter(p)
    fields.update(parameters)
    targets: dict[str, Target] = {}
    for t in records(manifest["targets"]):
        targets[str(t["name"])] = twin_target(t, targets, parameters)
    fields.update(targets)
    for g in records(manifest.get("groups", [])):
        fields[str(g["name"])] = group(*(targets[n] for n in strings(g["members"])))
    for c in records(manifest.get("ci", [])):
        fields[str(c["name"])] = twin_ci(c)
    hooks = manifest.get("hooks")
    if is_record(hooks):
        for flag, method in HOOKS.items():
            if hooks.get(flag) is True:
                fields[method] = HOOK_BODIES[method]
    config = manifest.get("config")
    if is_record(config):
        if "deadline" in config:
            fields["deadline"] = config["deadline"]
        if "unforceable" in config:
            fields["unforceable"] = tuple(
                targets[n] for n in strings(config["unforceable"])
            )
    return type(str(manifest["name"]), (Build,), fields)


def twin_target(
    t: dict[str, object], earlier: dict[str, Target], parameters: dict[str, Parameter]
) -> Target:
    b = twin_service(t) if t.get("kind") == "service" else target()
    if "description" in t:
        b = b.description(str(t["description"]))
    if "dependsOn" in t:
        b = b.depends_on(*(earlier[n] for n in strings(t["dependsOn"])))
    if t.get("unlisted") is True:
        b = b.unlisted()
    if "inputs" in t:
        b = b.inputs(*strings(t["inputs"]))
    if "outputs" in t:
        b = b.outputs(*strings(t["outputs"]))
    if "produces" in t:
        b = b.produces(*strings(t["produces"]))
    retry = t.get("retry")
    if is_record(retry):
        times, delay = retry.get("times", 0), retry.get("delayMs", 0)
        assert isinstance(times, int) and isinstance(delay, int)
        b = b.retry(times, delay)
    timeout = t.get("timeoutMs")
    if isinstance(timeout, int):
        b = b.timeout(timeout)
    if t.get("proceedAfterFailure") is True:
        b = b.proceed_after_failure()
    if t.get("always") is True:
        b = b.always()
    if t.get("dryRunnable") is True:
        b = b.dry_runnable()
    if not SCRIPT_KEYS.isdisjoint(t):
        b = b.executes(twin_body(t))
    return twin_links(twin_gates(b, t), t, earlier, parameters)


def twin_body(t: dict[str, object]) -> Body:
    """The body the case scripts: its calls, then its failure, crash or success."""
    calls = records(t.get("calls", []))
    fail, fail_times = t.get("fail"), t.get("failTimes", 0)
    sleep_ms, crash = t.get("sleep_ms", 0), t.get("crash_exit")
    assert isinstance(fail_times, int) and isinstance(sleep_ms, int)
    attempts = 0

    async def body(ctx: Context) -> None:
        nonlocal attempts
        if sleep_ms:
            await asyncio.sleep(sleep_ms / 1000)
        for call in calls:
            await twin_call(ctx, str(call.get("method")), call.get("params"))
        if isinstance(crash, int):
            os._exit(crash)  # The worker process dies mid-body, as the case scripts.
        attempts += 1
        if attempts <= fail_times:
            raise RuntimeError(f"attempt {attempts} of {ctx.target} failed")
        if isinstance(fail, str):
            raise RuntimeError(fail)

    return body


async def twin_call(ctx: Context, method: str, params: object) -> None:
    """One scripted call a body makes, through the context method named for it."""
    p = params if is_record(params) else {}
    of = p.get("of")
    state = ctx.state if not isinstance(of, str) else ctx.state_of(of)
    patch = p.get("patch")
    bare = {"plan": ctx.plan, "signals": ctx.signals, "outcomes": ctx.outcomes}
    if method in bare:
        await bare[method]()
    elif method == "state.set":
        await state.set(patch if is_record(patch) else {})
    elif method == "state.get":
        await state.get()
    elif method == "state.trySet":
        await state.try_set(patch if is_record(patch) else {})
    elif method == "summary.report":
        pairs = p.get("pairs")
        await ctx.summary(summary_pairs(pairs if is_record(pairs) else {}))
    elif method == "log":
        await ctx.log(str(p.get("line")))
    elif method == "outcome.of":
        await ctx.outcome_of(str(of))
    elif method == "secret.register":
        await ctx.secret(str(p.get("value")))
    elif method == "exec":
        await ctx.sh(*field_strings(p, "argv", "exec"))
    elif method == "tool.call":
        await twin_tool_call(ctx, p)
    else:
        raise ValueError(f"the twin has no call for {method}")


async def twin_tool_call(ctx: Context, p: dict[str, object]) -> None:
    """A scripted ``tool.call``, through the facade runtime a generated facade uses.

    As the engine's scripted worker does, it notes the answer, an error
    included, and the body goes on.
    """
    args = p.get("args")
    with suppress(RpcError):
        await tool_call(
            ctx,
            field(p, "package", "tool.call"),
            field(p, "version", "tool.call"),
            field(p, "tasks", "tool.call"),
            field(p, "task", "tool.call"),
            args if is_list(args) else [],
        )


def summary_pairs(pairs: dict[str, object]) -> dict[str, str | float]:
    out: dict[str, str | float] = {}
    for label, value in pairs.items():
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise TypeError(f"summary.report: {label} must be a string or number")
        out[label] = value
    return out


def twin_gates(b: Target, t: dict[str, object]) -> Target:
    """The condition, cache key and late settings a target declares, as scripted."""
    if t.get("condition") is True:
        answer = t.get("condition_answer", True)
        assert isinstance(answer, bool)
        b = b.condition(lambda: answer)
    if t.get("cacheKey") is True:
        key = t.get("cacheKey_answer", "")
        assert isinstance(key, str)
        b = b.cache_key(lambda: key)
    settings = t.get("settings")
    lock = settings.get("lock") if is_record(settings) else None
    if t.get("lock") is True and is_record(lock):
        b = b.lock(twin_lock(lock))
    waits_for = settings.get("waitsFor") if is_record(settings) else None
    if t.get("waitsFor") is True and is_record(waits_for):
        wait_answer = t.get("wait_answer", False)
        assert isinstance(wait_answer, bool)
        b = b.waits_for(twin_wait(waits_for, wait_answer))
    return b


def twin_links(
    b: Target,
    t: dict[str, object],
    earlier: dict[str, Target],
    parameters: dict[str, Parameter],
) -> Target:
    """The references a target makes: soft orderings, compensations, parameters."""
    # A soft reference may name a target declared later, so the twin uses the
    # name, as a user would there; an earlier one is the field itself.
    for key, setter in (
        ("before", b.before),
        ("after", b.after),
        ("triggers", b.triggers),
    ):
        if key in t:
            b = setter(*(earlier.get(n, n) for n in strings(t[key])))
    if "requires" in t:
        b = b.requires(*(parameters[n] for n in strings(t["requires"])))
    on_cancel = t.get("onCancel")
    if isinstance(on_cancel, str):
        b = b.on_cancel(earlier.get(on_cancel, on_cancel))
    on_failure = t.get("onFailure")
    if isinstance(on_failure, str):
        b = b.on_failure(earlier.get(on_failure, on_failure))
    return b


def twin_parameter(p: dict[str, object]) -> Parameter:
    s = parameter(str(p.get("description", "")))
    if p.get("required") is True:
        s = s.required()
    if p.get("secret") is True:
        s = s.secret()
    flag, env = p.get("flag"), p.get("env")
    if isinstance(flag, str):
        s = s.flag(flag)
    if isinstance(env, str):
        s = s.env(env)
    kind, default = p.get("kind", "string"), p.get("default")
    if kind == "number":
        n = s.number()
        if isinstance(default, (int, float)):
            n = n.default(default)
        return n.array() if p.get("array") is True else n
    if kind == "boolean":
        return (
            s.boolean().default(default) if isinstance(default, bool) else s.boolean()
        )
    if "options" in p:
        s = s.options(*strings(p["options"]))
    if isinstance(default, str):
        s = s.default(default)
    return s.array() if p.get("array") is True else s


def twin_service(t: dict[str, object]) -> Service:
    """A service answering the case's handle and readiness answers in turn."""
    s = service()
    handle = t.get("service_handle", "h1")
    assert isinstance(handle, str)
    s = s.start(lambda _ctx: handle)
    if t.get("ready") is True:
        answers = bools(t.get("ready_answers", [True]))

        def probe(_ctx: ServiceContext, _handle: str) -> bool:
            return answers.pop(0) if len(answers) > 1 else answers[0]

        timeout = t.get("readyTimeoutMs")
        s = s.ready(probe, timeout if isinstance(timeout, int) else None)
    return s


def bools(value: object) -> list[bool]:
    assert is_list(value)
    return [item for item in value if isinstance(item, bool)]


def twin_lock(m: dict[str, object]) -> Configure[LockSettings]:
    def configure(s: LockSettings) -> LockSettings:
        key = m.get("key")
        assert isinstance(key, str)
        s = s.key(key)
        for name, setter in (
            ("ttl", s.ttl),
            ("waitUpTo", s.wait_up_to),
            ("pollEvery", s.poll_every),
        ):
            value = m.get(name)
            if isinstance(value, (str, int)):
                s = setter(value)
        return s.hold_for_run() if m.get("holdForRun") is True else s

    return configure


def twin_wait(m: dict[str, object], answer: bool) -> Configure[WaitSettings]:
    def configure(s: WaitSettings) -> WaitSettings:
        on = m.get("on")
        assert is_record(on)
        if on.get("kind") == "externalSignal":
            s = s.external_signal(str(on.get("name")))
        else:
            interval = on.get("interval")
            s = s.resume_when(
                lambda: answer, interval if isinstance(interval, (str, int)) else None
            )
        timeout = m.get("timeout")
        if isinstance(timeout, (str, int)):
            s = s.timeout(timeout)
        on_timeout = m.get("onTimeout")
        return s.on_timeout(on_timeout) if isinstance(on_timeout, str) else s

    return configure


def twin_ci(c: dict[str, object]) -> Ci:
    """A CI file declared as the case's manifest carries it."""
    f = ci()
    provider = c.get("provider")
    if provider in ("github", "gitlab", "azure", "bitbucket"):
        f = f.provider(provider)
    path = c.get("path")
    if isinstance(path, str):
        f = f.path(path)
    pipeline = c.get("pipeline")
    if is_record(pipeline):
        f = f.pipeline(pipeline)
    invokes = c.get("invokes")
    if is_list(invokes):
        f = f.invokes(*(twin_invocation(entry) for entry in invokes))
    fan_out = c.get("fanOut")
    if isinstance(fan_out, bool) or is_record(fan_out):
        f = f.fan_out(fan_out)
    pins = c.get("pins")
    if is_record(pins):
        f = f.pins(pins)
    return f


def twin_invocation(entry: object) -> str | dict[str, object]:
    # A bare name or the adjusted form, as the manifest carries them: what a
    # user writes through invoke() reduces to the same mapping.
    if isinstance(entry, str):
        return entry
    assert is_record(entry)
    return entry


def on_start(_self: Build) -> None:
    return None


def on_target_start(_self: Build, _target: str) -> None:
    return None


def on_target_end(_self: Build, _target: str, _status: str) -> None:
    return None


def on_finish(_self: Build, _ok: bool) -> None:
    return None


HOOKS = {
    "onStart": "on_start",
    "onTargetStart": "on_target_start",
    "onTargetEnd": "on_target_end",
    "onFinish": "on_finish",
}
"""The manifest's hook flags and the overrides that set them."""

HOOK_BODIES: dict[str, object] = {
    "on_start": on_start,
    "on_target_start": on_target_start,
    "on_target_end": on_target_end,
    "on_finish": on_finish,
}
