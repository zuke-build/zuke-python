# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The worker loop against the fake engine."""

from __future__ import annotations

import asyncio
import os
import signal
import threading
from collections.abc import AsyncIterator

import pytest

from conftest import TOKEN, FakeEngine, Script
from zuke import ExecResult
from zuke._guard import ProtocolError
from zuke._rpc import CANCELLED, FAILED, Peer, RpcError, is_record
from zuke._worker import PROTOCOL, SDK, host, serve


async def ok(_params: object) -> object:
    return {"code": 0, "stdout": "", "stderr": ""}


class Session:
    """A worker serving ``script``'s build against ``engine``, and the peer to it."""

    def __init__(self, engine: FakeEngine, script: Script) -> None:
        self.engine = engine
        self.script = script
        self.serving = asyncio.ensure_future(
            serve(script.build, engine.environ, "/work/dir")
        )
        self.peer: Peer

    async def greeted(self) -> Peer:
        self.peer = await self.engine.greeted()
        self.peer.on("exec", ok)
        return self.peer

    async def ended(self) -> None:
        await asyncio.wait_for(self.serving, 5)


@pytest.fixture
async def session(engine: FakeEngine) -> AsyncIterator[Session]:
    s = Session(engine, Script())
    yield s
    if not s.serving.done():
        s.serving.cancel()


async def test_hello_carries_the_sdk_protocol_token_environment_and_cwd(
    session: Session,
) -> None:
    await session.greeted()
    assert session.engine.hello == {
        "sdk": SDK,
        "protocol": PROTOCOL,
        "token": TOKEN,
        "env": session.engine.environ,
        "cwd": "/work/dir",
    }


async def test_describe_answers_the_builds_manifest(session: Session) -> None:
    peer = await session.greeted()
    assert await peer.request("build.describe", {}) == session.script.build.describe()


async def test_configure_hands_the_build_its_parameters(session: Session) -> None:
    peer = await session.greeted()
    params = {"parameters": {"tag": "dev", "token": None}}
    assert await peer.request("build.configure", params) is None
    assert (session.script.tag.value, session.script.token.value) == ("dev", None)


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({}, '"parameters" must be an object'),
        ({"parameters": {"n": 1}}, 'parameter "n" must be a string or null'),
    ],
)
async def test_a_malformed_configure_is_refused_naming_the_field(
    session: Session, params: object, field: str
) -> None:
    peer = await session.greeted()
    with pytest.raises(RpcError, match=f"build.configure: {field}"):
        await peer.request("build.configure", params)


async def test_target_run_runs_the_body_which_may_exec_through_the_engine(
    session: Session,
) -> None:
    peer = await session.greeted()
    run = {"target": "lint", "runId": "r1", "dryRun": False}
    assert await peer.request("target.run", run) is None
    assert session.script.requests == [("lint", "r1", False)]
    assert session.script.results == [ExecResult(code=0, stdout="", stderr="")]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"runId": "r1", "dryRun": True}, '"target" must be a string'),
        ({"target": "lint", "dryRun": True}, '"runId" must be a string'),
        (
            {"target": "lint", "runId": "r1", "dryRun": "yes"},
            '"dryRun" must be a boolean',
        ),
        ("not an object", '"target" must be a string'),
    ],
)
async def test_a_malformed_target_run_is_refused_naming_the_field(
    session: Session, params: object, field: str
) -> None:
    peer = await session.greeted()
    with pytest.raises(RpcError, match=f"target.run: {field}"):
        await peer.request("target.run", params)


async def test_an_unknown_target_is_refused_by_name(session: Session) -> None:
    peer = await session.greeted()
    with pytest.raises(RpcError, match=r'target\.run: Scripted has no target "nope"'):
        await peer.request(
            "target.run", {"target": "nope", "runId": "r", "dryRun": False}
        )


async def test_a_body_that_raises_fails_the_target_with_its_message(
    session: Session,
) -> None:
    session.script.fail = ValueError("the linter found 3 problems")
    peer = await session.greeted()
    with pytest.raises(RpcError) as caught:
        await peer.request(
            "target.run", {"target": "lint", "runId": "r", "dryRun": False}
        )
    assert (caught.value.code, str(caught.value)) == (
        FAILED,
        "the linter found 3 problems",
    )


async def test_run_cancel_cancels_the_body_and_answers_cancelled(
    session: Session,
) -> None:
    session.script.hold = asyncio.Event()
    peer = await session.greeted()
    run = {"target": "slow", "runId": "r", "dryRun": False}
    running = asyncio.ensure_future(peer.request("target.run", run))
    while not session.script.requests:
        await asyncio.sleep(0.01)
    await peer.notify("run.cancel", {"target": "slow"})
    with pytest.raises(RpcError) as caught:
        await asyncio.wait_for(running, 5)
    assert (caught.value.code, str(caught.value)) == (CANCELLED, '"slow" was cancelled')


async def test_run_cancel_for_a_target_not_running_is_nothing(session: Session) -> None:
    peer = await session.greeted()
    await peer.notify("run.cancel", {"target": "idle"})
    assert await peer.request("build.describe", {}) == session.script.build.describe()


async def test_run_exit_ends_the_loop(session: Session) -> None:
    peer = await session.greeted()
    await peer.notify("run.exit", {"code": 0, "suspended": False})
    await session.ended()


async def test_the_connection_ending_without_run_exit_ends_the_loop(
    session: Session,
) -> None:
    peer = await session.greeted()
    peer.close()  # What an engine that died looks like from here.
    await session.ended()


async def test_a_body_in_flight_when_the_engine_dies_fails_and_the_loop_ends(
    session: Session,
) -> None:
    session.script.hold = asyncio.Event()
    peer = await session.greeted()
    run = {"target": "slow", "runId": "r", "dryRun": False}
    asyncio.ensure_future(peer.request("target.run", run)).add_done_callback(
        lambda done: done.exception()
    )
    while not session.script.requests:
        await asyncio.sleep(0.01)
    peer.close()
    await session.ended()


async def test_a_refused_hello_raises_the_engines_reason(engine: FakeEngine) -> None:
    environ = {**engine.environ, "ZUKE_ENGINE_TOKEN": "wrong"}
    with pytest.raises(RpcError, match="token mismatch"):
        await asyncio.wait_for(serve(Script().build, environ, "."), 5)


async def test_an_engine_that_hangs_up_on_hello_raises(engine: FakeEngine) -> None:
    serving = asyncio.ensure_future(serve(Script().build, engine.environ, "."))
    (await engine.connected()).close()
    with pytest.raises(RpcError):  # Closed, or reset with the greeting unread.
        await asyncio.wait_for(serving, 5)


async def test_another_protocol_version_is_refused_before_connecting() -> None:
    environ = {"ZUKE_PROTOCOL": "2", "ZUKE_ENGINE_ADDR": "x", "ZUKE_ENGINE_TOKEN": "t"}
    with pytest.raises(
        ProtocolError, match="speaks protocol 1; the engine asked for 2"
    ):
        await serve(Script().build, environ, ".")


@pytest.mark.parametrize(
    "missing", ["ZUKE_PROTOCOL", "ZUKE_ENGINE_ADDR", "ZUKE_ENGINE_TOKEN"]
)
async def test_a_missing_engine_variable_says_how_a_build_is_run(missing: str) -> None:
    environ = {
        "ZUKE_PROTOCOL": "1",
        "ZUKE_ENGINE_ADDR": "127.0.0.1:1",
        "ZUKE_ENGINE_TOKEN": "t",
    }
    del environ[missing]
    with pytest.raises(ProtocolError, match=f"{missing} is not set"):
        await serve(Script().build, environ, ".")


def test_host_ignores_sigint_and_serves_the_engine_in_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = signal.getsignal(signal.SIGINT)
    environ: dict[str, str] = {}
    listening = threading.Event()
    build = Script().build
    seen: list[object] = []

    async def engine_side() -> None:
        engine = FakeEngine()
        await engine.start()
        environ.update(engine.environ)
        listening.set()
        peer = await engine.greeted()
        seen.append(engine.hello)
        assert await peer.request("build.describe", {}) == build.describe()
        await peer.notify("run.exit", {"code": 0, "suspended": False})
        await engine.stop()

    thread = threading.Thread(target=lambda: asyncio.run(engine_side()))
    thread.start()
    try:
        assert listening.wait(5)
        for name, value in environ.items():
            monkeypatch.setenv(name, value)
        host(build)
        assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
        hello = seen[0]
        assert is_record(hello) and hello["cwd"] == os.getcwd()
    finally:
        signal.signal(signal.SIGINT, before)
        thread.join(5)
