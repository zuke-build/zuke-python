# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""Services: the manifest's kind, and the start, ready and stop phases and handle."""

from __future__ import annotations

import pytest

from conftest import served
from zuke import Build, ServiceContext, service, target
from zuke._rpc import RpcError


async def test_a_service_is_a_target_of_kind_service_with_its_probe_declared() -> None:
    s = service().description("postgres").ready(lambda _ctx, _h: True, timeout="5s")
    s.name_ = "db"
    assert s.manifest() == {
        "name": "db",
        "description": "postgres",
        "kind": "service",
        "ready": True,
        "readyTimeoutMs": 5000,
    }
    bare = service()
    bare.name_ = "cache"
    assert bare.manifest() == {"name": "cache", "kind": "service"}


async def test_the_phases_round_trip_the_handle_and_may_run_commands() -> None:
    events: list[str] = []

    async def start(ctx: ServiceContext) -> str:
        result = await ctx.sh("pg_ctl", "start")
        events.append(f"start {ctx.target} {result.stdout}")
        return "pg-1"

    answers = iter([False, True])

    def ready(_ctx: ServiceContext, handle: str) -> bool:
        events.append(f"ready {handle}")
        return next(answers)

    async def stop(_ctx: ServiceContext, handle: str) -> None:
        events.append(f"stop {handle}")

    class App(Build):
        db = service().start(start).ready(ready).stop(stop)
        test = target().depends_on(db)

    async def exec_(_params: object) -> object:
        return {"code": 0, "stdout": "started", "stderr": ""}

    async with served(App()) as peer:
        peer.on("exec", exec_)
        assert await peer.request("service.start", {"target": "db"}) == {
            "handle": "pg-1"
        }
        probe = {"target": "db", "handle": "pg-1"}
        assert await peer.request("service.ready", probe) is False
        assert await peer.request("service.ready", probe) is True
        assert await peer.request("service.stop", probe) is None
    assert events == ["start db started", "ready pg-1", "ready pg-1", "stop pg-1"]


async def test_a_service_without_a_stop_phase_stops_quietly() -> None:
    class App(Build):
        db = service().start(lambda _ctx: "h")

    async with served(App()) as peer:
        assert (
            await peer.request("service.stop", {"target": "db", "handle": "h"}) is None
        )


@pytest.mark.parametrize(
    ("method", "params", "message"),
    [
        ("service.start", {"target": "bare"}, '"bare" declared no start phase'),
        (
            "service.ready",
            {"target": "bare", "handle": "h"},
            '"bare" declared no readiness probe',
        ),
        ("service.start", {"target": "test"}, '"test" is not a service'),
        ("service.stop", {"target": "bare"}, '"handle" must be a string'),
        ("service.start", {"target": "nope"}, 'has no target "nope"'),
    ],
)
async def test_a_phase_the_service_lacks_is_refused_by_name(
    method: str, params: object, message: str
) -> None:
    class App(Build):
        bare = service()
        test = target()

    async with served(App()) as peer:
        with pytest.raises(RpcError, match=f"{method}: .*{message}"):
            await peer.request(method, params)
