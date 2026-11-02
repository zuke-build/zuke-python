# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The JSON-RPC peer, both sides of one loopback connection."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from zuke._rpc import FAILED, METHOD_NOT_FOUND, Peer, RpcError


class Pair:
    """Two peers over one connection, both serving."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.client: Peer
        self.server: Peer
        self.server_writer: asyncio.StreamWriter
        self.client_writer: asyncio.StreamWriter
        self._accepted = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    async def open(self) -> None:
        listener = await asyncio.start_server(
            self._accept, "127.0.0.1", 0, limit=self.limit
        )
        port = listener.sockets[0].getsockname()[1]
        reader, self.client_writer = await asyncio.open_connection(
            "127.0.0.1", port, limit=self.limit
        )
        self.client = Peer(reader, self.client_writer)
        self._tasks.append(asyncio.ensure_future(self.client.serve()))
        await self._accepted.wait()
        listener.close()

    async def _accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.server_writer = writer
        self.server = Peer(reader, writer)
        self._accepted.set()
        await self.server.serve()

    async def settled(self) -> None:
        await asyncio.wait_for(asyncio.gather(*self._tasks), 5)


@pytest.fixture
async def pair() -> AsyncIterator[Pair]:
    p = Pair(limit=1 << 16)
    await p.open()
    yield p
    p.client.close()
    p.server.close()
    await p.settled()


async def closed(peer: Peer) -> None:
    """Wait for the peer's serve loop to notice the end."""
    async with asyncio.timeout(5):
        while not peer.closed:
            await asyncio.sleep(0.01)


async def echo(params: object) -> object:
    return {"echoed": params}


async def nothing(_params: object) -> object:
    return None


async def test_a_request_is_answered_with_the_handlers_result(pair: Pair) -> None:
    pair.server.on("echo", echo)
    assert await pair.client.request("echo", {"n": 1}) == {"echoed": {"n": 1}}


async def test_a_handler_with_nothing_to_say_answers_null(pair: Pair) -> None:
    pair.server.on("ping", nothing)
    assert await pair.client.request("ping", {}) is None


async def test_both_sides_request_each_other(pair: Pair) -> None:
    pair.server.on("echo", echo)
    pair.client.on("echo", echo)
    assert await pair.server.request("echo", 1) == {"echoed": 1}
    assert await pair.client.request("echo", 2) == {"echoed": 2}


async def test_a_notification_reaches_its_handler_and_is_not_answered(
    pair: Pair,
) -> None:
    seen: list[object] = []

    async def note(params: object) -> object:
        seen.append(params)
        return "ignored"

    pair.server.on("note", note)
    await pair.client.notify("note", {"a": 1})
    while not seen:
        await asyncio.sleep(0.01)
    assert seen == [{"a": 1}]


async def test_an_unknown_method_is_refused_by_name(pair: Pair) -> None:
    with pytest.raises(RpcError) as caught:
        await pair.client.request("nope", {})
    assert caught.value.code == METHOD_NOT_FOUND
    assert str(caught.value) == 'unknown method "nope"'


async def test_a_notification_for_an_unknown_method_is_dropped(pair: Pair) -> None:
    pair.server.on("echo", echo)
    await pair.client.notify("nope", {})
    assert await pair.client.request("echo", 1) == {"echoed": 1}


async def test_a_handler_raising_an_rpc_error_keeps_its_code(pair: Pair) -> None:
    async def refuse(_params: object) -> object:
        raise RpcError(-32001, "cancelled")

    pair.server.on("refuse", refuse)
    with pytest.raises(RpcError) as caught:
        await pair.client.request("refuse", {})
    assert (caught.value.code, str(caught.value)) == (-32001, "cancelled")


async def test_any_other_exception_in_a_handler_is_a_failure_with_its_message(
    pair: Pair,
) -> None:
    async def boom(_params: object) -> object:
        raise ValueError("boom")

    pair.server.on("boom", boom)
    with pytest.raises(RpcError) as caught:
        await pair.client.request("boom", {})
    assert (caught.value.code, str(caught.value)) == (FAILED, "boom")


async def test_a_handler_may_request_back_while_its_request_is_open(pair: Pair) -> None:
    async def ask_back(_params: object) -> object:
        return await pair.server.request("echo", "inner")

    pair.server.on("ask", ask_back)
    pair.client.on("echo", echo)
    assert await pair.client.request("ask", {}) == {"echoed": "inner"}


async def forever(_params: object) -> object:
    await asyncio.Event().wait()
    return None


async def test_closing_rejects_every_pending_request_with_the_reason(
    pair: Pair,
) -> None:
    pair.server.on("wait", forever)
    waiting = asyncio.ensure_future(pair.client.request("wait", {}))
    await asyncio.sleep(0.05)
    pair.client.close("going away")
    with pytest.raises(RpcError, match="going away"):
        await waiting
    assert pair.client.closed


async def test_a_request_on_a_closed_peer_fails_at_once_and_a_notify_is_dropped(
    pair: Pair,
) -> None:
    pair.client.close()
    pair.client.close()  # Twice is nothing.
    with pytest.raises(RpcError, match="connection closed"):
        await pair.client.request("echo", {})
    await pair.client.notify("echo", {})


async def test_the_remote_end_closing_ends_serve_and_fails_the_pending(
    pair: Pair,
) -> None:
    pending = asyncio.ensure_future(pair.client.request("never", {}))
    pair.server.close()
    with pytest.raises(RpcError):
        await pending
    await closed(pair.client)
    assert pair.client.closed


async def test_lines_that_are_not_requests_or_answers_are_ignored(pair: Pair) -> None:
    pair.server.on("echo", echo)
    pair.client_writer.write(b"not json\n")
    pair.client_writer.write(b"[1, 2]\n")
    pair.client_writer.write(b'{"neither": "request nor answer"}\n')
    pair.client_writer.write(b'{"jsonrpc": "2.0", "id": 999, "result": 1}\n')
    pair.client_writer.write(b'{"jsonrpc": "2.0", "id": "s", "method": "echo"}\n')
    pair.client_writer.write(b"\n")
    assert await pair.client.request("echo", 1) == {"echoed": 1}


async def test_a_request_whose_awaiter_was_cancelled_is_dropped_on_close(
    pair: Pair,
) -> None:
    pair.server.on("wait", forever)
    waiting = asyncio.ensure_future(pair.client.request("wait", {}))
    await asyncio.sleep(0.02)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    pair.client.close()  # Must not touch the cancelled future.


async def test_an_error_answer_without_code_or_message_still_fails(pair: Pair) -> None:
    pair.server.on("x", forever)
    pending = asyncio.ensure_future(pair.client.request("x", {}))
    await asyncio.sleep(0.02)
    pair.server_writer.write(
        json.dumps({"jsonrpc": "2.0", "id": 1, "error": {}}).encode() + b"\n"
    )
    with pytest.raises(RpcError) as caught:
        await pending
    assert (caught.value.code, str(caught.value)) == (FAILED, "error")


async def test_a_line_past_the_limit_ends_the_connection() -> None:
    p = Pair(limit=64)
    await p.open()
    p.client_writer.write(b"x" * 100)
    await p.client_writer.drain()
    await closed(p.server)
    assert p.server.closed
    with pytest.raises(RpcError, match="limit"):
        await p.server.request("echo", {})
    p.client.close()
    await p.settled()


async def test_a_write_that_fails_closes_the_peer(
    pair: Pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def lost() -> None:
        raise ConnectionResetError("Connection lost")

    monkeypatch.setattr(pair.client_writer, "drain", lost)
    await pair.client.notify("echo", {})
    assert pair.client.closed
    with pytest.raises(RpcError, match="Connection lost"):
        await pair.client.request("echo", {})
