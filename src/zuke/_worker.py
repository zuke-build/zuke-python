# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The worker loop: connect to the engine, greet it, serve protocol v1.

The engine starts this process with ``ZUKE_ENGINE_ADDR``, ``ZUKE_ENGINE_TOKEN``
and ``ZUKE_PROTOCOL`` in its environment and accepts exactly one connection.
The worker greets it with ``hello``, then answers everything the engine asks
of a build until ``run.exit``, or until the connection ends without one,
which is all a worker sees of an engine that died. The engine drives
shutdown, so SIGINT is ignored.
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Mapping

from zuke._awaited import awaited
from zuke._build import Build
from zuke._context import Context, ServiceContext
from zuke._dsl import Service, Target
from zuke._guard import ProtocolError, boolean, record, string
from zuke._rpc import CANCELLED, MAX_LINE, Peer, RpcError, is_record

SDK = "zuke-python"
"""What ``hello`` announces this SDK as."""

PROTOCOL = 1
"""The protocol version this worker speaks."""


def _parameters(params: object) -> dict[str, str | None]:
    values = params.get("parameters") if is_record(params) else None
    parsed: dict[str, str | None] = {}
    for name, value in record(values, 'build.configure: "parameters"').items():
        if value is not None and not isinstance(value, str):
            raise ProtocolError(
                f'build.configure: parameter "{name}" must be a string or null'
            )
        parsed[name] = value
    return parsed


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if value is None:
        raise ProtocolError(
            f"{name} is not set: a Zuke build runs through the engine, "
            "`./zuke <target>`, not on its own"
        )
    return value


class Worker:
    """One connection's worth of serving ``build``."""

    def __init__(self, build: Build, peer: Peer) -> None:
        """Serve ``build`` over ``peer``."""
        self._build = build
        self._peer = peer
        self._running: dict[str, asyncio.Task[None]] = {}
        peer.on("build.describe", self._describe)
        peer.on("build.configure", self._configure)
        peer.on("target.run", self._run)
        peer.on("run.cancel", self._cancel)
        peer.on("run.exit", self._exit)
        peer.on("target.condition", self._condition)
        peer.on("target.cacheKey", self._cache_key)
        peer.on("target.settings", self._settings)
        peer.on("wait.check", self._wait_check)
        peer.on("target.validate", self._validate)
        peer.on("service.start", self._service_start)
        peer.on("service.ready", self._service_ready)
        peer.on("service.stop", self._service_stop)
        peer.on("build.onStart", self._on_start)
        peer.on("build.onTargetStart", self._on_target_start)
        peer.on("build.onTargetEnd", self._on_target_end)
        peer.on("build.onFinish", self._on_finish)

    async def _describe(self, _params: object) -> object:
        return self._build.describe()

    async def _configure(self, params: object) -> object:
        self._build.configure(_parameters(params))
        return None

    def _target(self, params: object, method: str) -> Target:
        return self._build.target_(string(params, "target", method), method)

    def _service(self, params: object, method: str) -> tuple[Service, ServiceContext]:
        name = string(params, "target", method)
        return self._build.service_(name, method), ServiceContext(self._peer, name)

    async def _run(self, params: object) -> object:
        name = string(params, "target", "target.run")
        ctx = Context(
            self._peer,
            name,
            string(params, "runId", "target.run"),
            boolean(params, "dryRun", "target.run"),
        )
        t = self._build.target_(name, "target.run")
        body = asyncio.get_running_loop().create_task(t.run_body(ctx))
        self._running[name] = body
        try:
            await body
        except asyncio.CancelledError:
            raise RpcError(CANCELLED, f'"{name}" was cancelled') from None
        finally:
            self._running.pop(name, None)
        return None

    async def _cancel(self, params: object) -> object:
        body = self._running.get(string(params, "target", "run.cancel"))
        if body is not None:
            body.cancel()
        return None

    async def _exit(self, _params: object) -> object:
        self._peer.close()
        return None

    async def _condition(self, params: object) -> object:
        return await self._target(params, "target.condition").condition_()

    async def _cache_key(self, params: object) -> object:
        return await self._target(params, "target.cacheKey").cache_key_()

    async def _settings(self, params: object) -> object:
        return self._target(params, "target.settings").settings_()

    async def _wait_check(self, params: object) -> object:
        return await self._target(params, "wait.check").wait_check_()

    async def _validate(self, params: object) -> object:
        check = string(params, "check", "target.validate")
        await self._target(params, "target.validate").validate_(check)
        return None

    async def _service_start(self, params: object) -> object:
        s, ctx = self._service(params, "service.start")
        return {"handle": await s.start_(ctx)}

    async def _service_ready(self, params: object) -> object:
        s, ctx = self._service(params, "service.ready")
        return await s.ready_(ctx, string(params, "handle", "service.ready"))

    async def _service_stop(self, params: object) -> object:
        s, ctx = self._service(params, "service.stop")
        await s.stop_(ctx, string(params, "handle", "service.stop"))
        return None

    async def _on_start(self, _params: object) -> object:
        await awaited(self._build.on_start())
        return None

    async def _on_target_start(self, params: object) -> object:
        target = string(params, "target", "build.onTargetStart")
        await awaited(self._build.on_target_start(target))
        return None

    async def _on_target_end(self, params: object) -> object:
        target = string(params, "target", "build.onTargetEnd")
        status = string(params, "status", "build.onTargetEnd")
        await awaited(self._build.on_target_end(target, status))
        return None

    async def _on_finish(self, params: object) -> object:
        await awaited(self._build.on_finish(boolean(params, "ok", "build.onFinish")))
        return None


async def serve(build: Build, environ: Mapping[str, str], cwd: str) -> None:
    """Connect to the engine in ``environ``, greet it, and serve until the run ends.

    Raises :class:`ProtocolError` when the environment is not an engine's, and
    :class:`RpcError` when the engine refuses the greeting.
    """
    protocol = _required(environ, "ZUKE_PROTOCOL")
    if protocol != str(PROTOCOL):
        raise ProtocolError(
            f"{SDK} speaks protocol {PROTOCOL}; the engine asked for {protocol}"
        )
    host, _, port = _required(environ, "ZUKE_ENGINE_ADDR").rpartition(":")
    token = _required(environ, "ZUKE_ENGINE_TOKEN")
    reader, writer = await asyncio.open_connection(host, int(port), limit=MAX_LINE)
    peer = Peer(reader, writer)
    Worker(build, peer)
    serving = asyncio.get_running_loop().create_task(peer.serve())
    try:
        await peer.request(
            "hello",
            {
                "sdk": SDK,
                "protocol": PROTOCOL,
                "token": token,
                "env": dict(environ),
                "cwd": cwd,
            },
        )
        await serving
    finally:
        peer.close()
        await serving


def host(build: Build) -> None:
    """Run ``build`` as the worker of the engine that started this process."""
    # The engine drives shutdown: a Ctrl-C reaches it too, and it cancels the
    # run, answers the bodies, and stops this process when they have settled.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    asyncio.run(serve(build, os.environ, os.getcwd()))
