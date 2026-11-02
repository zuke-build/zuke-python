# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The worker loop: connect to the engine, greet it, serve protocol v1.

The engine starts this process with ``ZUKE_ENGINE_ADDR``, ``ZUKE_ENGINE_TOKEN``
and ``ZUKE_PROTOCOL`` in its environment and accepts exactly one connection.
The worker greets it with ``hello``, then answers ``build.describe``,
``build.configure`` and ``target.run`` until ``run.exit``, or until the
connection ends without one, which is all a worker sees of an engine that
died. The engine drives shutdown, so SIGINT is ignored.
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Protocol

from zuke._rpc import CANCELLED, MAX_LINE, Peer, RpcError, is_record

SDK = "zuke-python"
"""What ``hello`` announces this SDK as."""

PROTOCOL = 1
"""The protocol version this worker speaks."""


@dataclass(frozen=True)
class RunRequest:
    """What ``target.run`` asks for."""

    target: str
    """The target whose body to run."""
    run_id: str
    """The run's id, as the run record names it."""
    dry_run: bool
    """Whether the run is a ``--dry-run``."""


class Hosted(Protocol):
    """The build a worker hosts: what the loop asks of it."""

    def describe(self) -> object:
        """The manifest, answered to ``build.describe``."""
        ...

    def configure(self, parameters: Mapping[str, str | None]) -> None:
        """Take the resolved parameters, each in its CLI form or ``None`` when unset."""
        ...

    def run_target(self, request: RunRequest, engine: Peer) -> Awaitable[None]:
        """Run one target's body; ``engine`` serves the calls it makes."""
        ...


class ProtocolError(Exception):
    """The environment or a request is not protocol v1 as this worker speaks it."""


def _string(params: object, field: str, method: str) -> str:
    if not is_record(params) or not isinstance(value := params.get(field), str):
        raise ProtocolError(f'{method}: "{field}" must be a string')
    return value


def _boolean(params: object, field: str, method: str) -> bool:
    if not is_record(params) or not isinstance(value := params.get(field), bool):
        raise ProtocolError(f'{method}: "{field}" must be a boolean')
    return value


def _parameters(params: object) -> dict[str, str | None]:
    values = params.get("parameters") if is_record(params) else None
    if not is_record(values):
        raise ProtocolError('build.configure: "parameters" must be an object')
    parsed: dict[str, str | None] = {}
    for name, value in values.items():
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

    def __init__(self, build: Hosted, peer: Peer) -> None:
        """Serve ``build`` over ``peer``."""
        self._build = build
        self._peer = peer
        self._running: dict[str, asyncio.Task[None]] = {}
        peer.on("build.describe", self._describe)
        peer.on("build.configure", self._configure)
        peer.on("target.run", self._run)
        peer.on("run.cancel", self._cancel)
        peer.on("run.exit", self._exit)

    async def _describe(self, _params: object) -> object:
        return self._build.describe()

    async def _configure(self, params: object) -> object:
        self._build.configure(_parameters(params))
        return None

    async def _run(self, params: object) -> object:
        request = RunRequest(
            target=_string(params, "target", "target.run"),
            run_id=_string(params, "runId", "target.run"),
            dry_run=_boolean(params, "dryRun", "target.run"),
        )
        body = asyncio.get_running_loop().create_task(
            _settle(self._build.run_target(request, self._peer))
        )
        self._running[request.target] = body
        try:
            await body
        except asyncio.CancelledError:
            raise RpcError(CANCELLED, f'"{request.target}" was cancelled') from None
        finally:
            self._running.pop(request.target, None)
        return None

    async def _cancel(self, params: object) -> object:
        body = self._running.get(_string(params, "target", "run.cancel"))
        if body is not None:
            body.cancel()
        return None

    async def _exit(self, _params: object) -> object:
        self._peer.close()
        return None


async def _settle(body: Awaitable[None]) -> None:
    await body


async def serve(build: Hosted, environ: Mapping[str, str], cwd: str) -> None:
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


def host(build: Hosted) -> None:
    """Run ``build`` as the worker of the engine that started this process."""
    # The engine drives shutdown: a Ctrl-C reaches it too, and it cancels the
    # run, answers the bodies, and stops this process when they have settled.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    asyncio.run(serve(build, os.environ, os.getcwd()))
