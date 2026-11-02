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

import json
from pathlib import Path
from typing import TypeGuard

import pytest

from zuke import Build, Parameter, Target, group, parameter, target
from zuke._rpc import is_record

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

LATER_SLICE = frozenset(
    {"kind", "ready", "readyTimeoutMs", "condition", "cacheKey", "lock", "waitsFor"}
)
"""Target fields the authoring surface gains in slice 4, with ``hooks`` and ``ci``."""


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


def is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def records(value: object) -> list[dict[str, object]]:
    assert is_list(value)
    return [item for item in value if is_record(item)]


def strings(value: object) -> list[str]:
    assert is_list(value)
    return [item for item in value if isinstance(item, str)]


def twin(manifest: dict[str, object]) -> type[Build]:
    """The ``Build`` subclass a user would write for ``manifest``."""
    if not LATER_SLICE.isdisjoint(k for t in records(manifest["targets"]) for k in t):
        pytest.skip("uses target fields of slice 4")
    if "hooks" in manifest or "ci" in manifest:
        pytest.skip("uses hooks or ci, which are slice 4")
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
    b = target()
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
    return twin_links(b, t, earlier, parameters)


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
