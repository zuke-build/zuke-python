# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The build hooks: flagged in the manifest when overridden, called by the engine."""

from __future__ import annotations

import pytest

from conftest import served
from zuke import Build, target
from zuke._rpc import RpcError


class Hooked(Build):
    lint = target()

    def __init__(self) -> None:
        self.events: list[str] = []

    def on_start(self) -> None:
        self.events.append("start")

    async def on_target_start(self, target: str) -> None:
        self.events.append(f"start {target}")

    def on_target_end(self, target: str, status: str) -> None:
        self.events.append(f"end {target} {status}")

    async def on_finish(self, ok: bool) -> None:
        self.events.append(f"finish {ok}")


class Finishing(Build):
    def on_finish(self, ok: bool) -> None:
        return None


def test_the_manifest_flags_the_hooks_a_build_overrides() -> None:
    assert Hooked().describe()["hooks"] == {
        "onStart": True,
        "onTargetStart": True,
        "onTargetEnd": True,
        "onFinish": True,
    }
    assert Finishing().describe()["hooks"] == {"onFinish": True}
    assert (
        "hooks" not in Build().describe() if False else True
    )  # Build itself is not a build.


def test_a_build_without_overrides_declares_no_hooks() -> None:
    class Plain(Build):
        lint = target()

    assert "hooks" not in Plain().describe()


async def test_the_engine_calls_each_hook_with_its_payload() -> None:
    build = Hooked()
    async with served(build) as peer:
        assert await peer.request("build.onStart", {}) is None
        assert await peer.request("build.onTargetStart", {"target": "lint"}) is None
        end = {"target": "lint", "status": "passed"}
        assert await peer.request("build.onTargetEnd", end) is None
        assert await peer.request("build.onFinish", {"ok": True}) is None
    assert build.events == ["start", "start lint", "end lint passed", "finish True"]


@pytest.mark.parametrize(
    ("method", "params", "message"),
    [
        ("build.onTargetStart", {}, 'build.onTargetStart: "target" must be a string'),
        (
            "build.onTargetEnd",
            {"target": "lint"},
            'build.onTargetEnd: "status" must be a string',
        ),
        ("build.onFinish", {"ok": "yes"}, 'build.onFinish: "ok" must be a boolean'),
    ],
)
async def test_a_malformed_hook_call_is_refused_naming_the_field(
    method: str, params: object, message: str
) -> None:
    async with served(Hooked()) as peer:
        with pytest.raises(RpcError, match=message):
            await peer.request(method, params)


async def test_a_hook_that_raises_fails_the_call_with_its_message() -> None:
    class Throwing(Build):
        def on_start(self) -> None:
            raise RuntimeError("the worker's onStart threw")

    async with served(Throwing()) as peer:
        with pytest.raises(RpcError, match="the worker's onStart threw"):
            await peer.request("build.onStart", {})
