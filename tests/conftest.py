# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""A fake engine for the worker's tests: the protocol's other side on a loopback socket.

It is built on the same :class:`~zuke._rpc.Peer` the worker uses, since the
protocol is symmetric, and hands out the environment the real engine gives
a worker it starts.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field

import pytest

from zuke._rpc import FAILED, MAX_LINE, Peer, RpcError, is_record
from zuke._worker import RunRequest

TOKEN = "t0k3n"


class FakeEngine:
    """Listens like the engine, records ``hello``, serves what a test registers."""

    def __init__(self) -> None:
        self.environ: dict[str, str] = {}
        self.hello: object = None
        self.peer: Peer | None = None
        self._connected = asyncio.Event()
        self._greeted = asyncio.Event()
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._accept, "127.0.0.1", 0, limit=MAX_LINE
        )
        port = self._server.sockets[0].getsockname()[1]
        self.environ = {
            "ZUKE_ENGINE_ADDR": f"127.0.0.1:{port}",
            "ZUKE_ENGINE_TOKEN": TOKEN,
            "ZUKE_PROTOCOL": "1",
        }

    async def _accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.peer = Peer(reader, writer)
        self.peer.on("hello", self._hello)
        self._connected.set()
        await self.peer.serve()

    async def _hello(self, params: object) -> object:
        self.hello = params
        if not is_record(params) or params.get("token") != TOKEN:
            # The worker closes on a refused greeting, as on the real engine's.
            raise RpcError(FAILED, "hello: token mismatch")
        self._greeted.set()
        return None

    async def greeted(self) -> Peer:
        """The worker's peer, once its ``hello`` was accepted."""
        await asyncio.wait_for(self._greeted.wait(), 5)
        assert self.peer is not None
        return self.peer

    async def connected(self) -> Peer:
        """The worker's peer, as soon as it connected."""
        await asyncio.wait_for(self._connected.wait(), 5)
        assert self.peer is not None
        return self.peer

    async def stop(self) -> None:
        if self.peer is not None:
            self.peer.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


@pytest.fixture
async def engine() -> AsyncIterator[FakeEngine]:
    """A listening fake engine, stopped after the test."""
    fake = FakeEngine()
    await fake.start()
    yield fake
    await fake.stop()


@dataclass
class Scripted:
    """A hosted build for the tests: a manifest, a body, and what it was asked."""

    manifest: object = field(default_factory=lambda: {"name": "Fake", "targets": []})
    configured: dict[str, str | None] | None = None
    requests: list[RunRequest] = field(default_factory=list[RunRequest])
    results: list[object] = field(default_factory=list[object])
    hold: asyncio.Event | None = None
    """When set, the body waits on it, so a test can cancel it mid-run."""
    fail: BaseException | None = None
    """When set, the body raises it."""

    def describe(self) -> object:
        return self.manifest

    def configure(self, parameters: Mapping[str, str | None]) -> None:
        self.configured = dict(parameters)

    async def run_target(self, request: RunRequest, engine: Peer) -> None:
        self.requests.append(request)
        if self.hold is not None:
            await self.hold.wait()
        if self.fail is not None:
            raise self.fail
        self.results.append(
            await engine.request("exec", {"target": request.target, "argv": ["true"]})
        )
