# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The committed facades: every module imports, names its release, and calls through."""

from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path

from conftest import Harness
from zuke import Context, ExecResult, tools
from zuke._rpc import is_record
from zuke.tools import docker
from zuke.tools.docker import DockerTasks

ENGINE: object = json.loads(
    (Path(__file__).parent.parent / "spec" / "engine.json").read_text()
)


def test_every_facade_imports_and_pins_its_release() -> None:
    assert is_record(ENGINE)
    versions = ENGINE["versions"]
    assert is_record(versions)
    modules = [m.name for m in pkgutil.iter_modules(tools.__path__)]
    assert "_tooling" in modules
    for name, version in versions.items():
        module = importlib.import_module(f"zuke.tools.{name.replace('-', '_')}")
        assert name == module.PACKAGE
        assert version == module.VERSION
    assert len(modules) == len(versions) + 1


async def test_a_facade_task_sends_its_setters_and_reads_the_output(
    harness: Harness,
) -> None:
    results: list[ExecResult] = []

    async def body(ctx: Context) -> None:
        results.append(
            await DockerTasks.build(ctx, lambda s: s.tag("app:1").no_throw())
        )

    answer = {"code": 0, "stdout": "built", "stderr": ""}
    assert await harness.run(body, ("tool.call", answer)) is None
    assert harness.calls == [
        (
            "tool.call",
            {
                "target": "t",
                "package": "docker",
                "version": docker.VERSION,
                "tasks": "DockerTasks",
                "task": "build",
                "args": [{"configure": [["tag", ["app:1"]], ["noThrow", []]]}],
            },
        )
    ]
    assert results == [ExecResult(0, "built", "")]
