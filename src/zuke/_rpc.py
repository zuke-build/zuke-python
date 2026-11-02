# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""A symmetric JSON-RPC 2.0 peer over one newline-delimited connection.

Both sides send requests and notifications and answer the other's, one JSON
object per line, as the engine's own peer does. Everything read from the
socket is untrusted: a message that is not a JSON object is ignored, and a
handler sees its params as a plain ``object`` to narrow itself.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Self, TypeGuard

MAX_LINE = 16 * 1024 * 1024
"""The longest line a peer buffers, in bytes; a longer one ends the connection."""

FAILED = -32000
"""The error code of a handler that raised anything but an :class:`RpcError`."""

CANCELLED = -32001
"""The error code of a cancelled ``exec``, and of a body the engine cancelled."""

METHOD_NOT_FOUND = -32601
"""The error code of a request for a method no handler is registered for."""

Handler = Callable[[object], Awaitable[object]]
"""A request handler: awaits the result, or raises to produce an error answer."""


class RpcError(Exception):
    """An error the remote side answered a request with, or a connection's end."""

    def __init__(self, code: int, message: str) -> None:
        """Keep the remote error's code and message."""
        super().__init__(message)
        self.code = code
        """The JSON-RPC error code."""


def is_record(value: object) -> TypeGuard[dict[str, object]]:
    """Whether ``value`` is a JSON object, the one shape a message or params take."""
    return isinstance(value, dict)


class Peer:
    """The JSON-RPC peer. Call :meth:`serve` once to start reading."""

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Wrap an open connection; the reader's limit should be :data:`MAX_LINE`."""
        self._reader = reader
        self._writer = writer
        self._next = 1
        self._pending: dict[int, asyncio.Future[object]] = {}
        self._handlers: dict[str, Handler] = {}
        self._handling: set[asyncio.Task[None]] = set()
        self._closed = False
        self._close_reason = "connection closed"

    @property
    def closed(self) -> bool:
        """Whether the connection has been closed, by either side."""
        return self._closed

    def on(self, method: str, handler: Handler) -> Self:
        """Register the handler for ``method``."""
        self._handlers[method] = handler
        return self

    async def request(self, method: str, params: object) -> object:
        """Send a request and await its result; a closed connection answers at once."""
        if self._closed:
            raise RpcError(FAILED, self._close_reason)
        request_id = self._next
        self._next += 1
        result: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = result
        await self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        return await result

    async def notify(self, method: str, params: object) -> None:
        """Send a notification: no answer is expected."""
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def serve(self) -> None:
        """Read until the connection ends, dispatching every message."""
        try:
            while True:
                line = await self._reader.readline()
                if line == b"":
                    break
                self._dispatch(line)
        except (ValueError, OSError) as error:
            # A line past the reader's limit, or the remote vanishing: either
            # way nothing is left to read.
            self.close(str(error))
        finally:
            self.close()

    def close(self, reason: str = "connection closed") -> None:
        """Close the connection; every pending request fails with ``reason``."""
        if self._closed:
            return
        self._closed = True
        self._close_reason = reason
        self._writer.close()
        for pending in self._pending.values():
            if not pending.done():
                pending.set_exception(RpcError(FAILED, reason))
        self._pending.clear()

    def _dispatch(self, line: bytes) -> None:
        try:
            message: object = json.loads(line)
        except ValueError:
            return  # Not JSON: the other side spoke on the wrong channel.
        if not is_record(message):
            return
        method = message.get("method")
        request_id = message.get("id")
        if isinstance(method, str):
            task = asyncio.get_running_loop().create_task(
                self._handle(method, message.get("params"), request_id)
            )
            self._handling.add(task)
            task.add_done_callback(self._handling.discard)
        elif isinstance(request_id, int):
            self._settle(request_id, message)

    def _settle(self, request_id: int, message: dict[str, object]) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        error = message.get("error")
        if is_record(error):
            code = error.get("code")
            text = error.get("message")
            pending.set_exception(
                RpcError(
                    code if isinstance(code, int) else FAILED,
                    text if isinstance(text, str) else "error",
                )
            )
        else:
            pending.set_result(message.get("result"))

    async def _handle(self, method: str, params: object, request_id: object) -> None:
        answer = isinstance(request_id, int)
        handler = self._handlers.get(method)
        if handler is None:
            if answer:
                await self._fail(
                    request_id, METHOD_NOT_FOUND, f'unknown method "{method}"'
                )
            return
        try:
            result = await handler(params)
        except RpcError as error:
            if answer:
                await self._fail(request_id, error.code, str(error))
            return
        except Exception as error:  # A body's failure is its answer.
            if answer:
                await self._fail(request_id, FAILED, str(error))
            return
        if answer:
            # A handler with nothing to say answers ``{}``, as the engine does.
            await self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {} if result is None else result,
                }
            )

    async def _fail(self, request_id: object, code: int, message: str) -> None:
        await self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            }
        )

    async def _send(self, message: dict[str, object]) -> None:
        if self._closed:
            return
        self._writer.write(json.dumps(message).encode() + b"\n")
        try:
            await self._writer.drain()
        except OSError as error:
            self.close(str(error))
