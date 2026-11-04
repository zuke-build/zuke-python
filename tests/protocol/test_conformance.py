# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""Every conformance case of the engine, replayed against a real worker process.

The engine repository replays each case through the real engine against its
scripted fake worker. Here the sides swap: a fake engine drives this
package's worker, started as the process the real engine would start,
through the case's calls in order, answers the worker's own calls as the case
scripts, and checks each answer and each exit.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import deque
from pathlib import Path

import pytest

from twins import bools, cases, expected, manifest_of, records
from zuke._guard import is_list
from zuke._guard import strings as field_strings
from zuke._rpc import CANCELLED, MAX_LINE, Handler, Peer, RpcError, is_record

TESTS = Path(__file__).resolve().parent.parent
WORKER = Path(__file__).with_name("worker.py")
CASES = TESTS / "protocol" / "cases"
TOKEN = "c0nf0rm"
SERVED = (
    "exec",
    "tool.call",
    "state.get",
    "state.set",
    "state.trySet",
    "outcome.of",
    "outcomes",
    "summary.report",
    "secret.register",
    "log",
    "plan",
    "signals",
)
"""The calls a body makes, which the fake engine answers."""

DEFAULT_ANSWERS: dict[str, object] = {
    "state.get": {},
    "state.trySet": {"recorded": True},
    "outcome.of": None,
    "outcomes": {},
    "plan": {"targets": [], "dependencies": {}},
    "signals": {},
    "exec": {"code": 0, "stdout": "", "stderr": ""},
}
"""What a call the case does not script is answered with, in the engine's shape."""


def load(case: str) -> dict[str, object]:
    loaded: object = json.loads((CASES / f"{case}.json").read_text())
    assert is_record(loaded)
    return loaded


def answers_of(block: dict[str, object]) -> deque[tuple[str, object]]:
    """The ``answers`` a block scripts, each ``method json``."""
    parsed: deque[tuple[str, object]] = deque()
    lines = field_strings(block, "answers", "case") if "answers" in block else []
    for line in lines:
        method, _, text = line.partition(" ")
        answer: object
        if text.startswith("error "):
            # ``method error <code> <message>``: the engine refused the call.
            _, code, message = text.split(" ", 2)
            answer = RpcError(int(code), message)
        else:
            answer = json.loads(text)
        parsed.append((method, answer))
    return parsed


class Worker:
    """A worker process and the engine's peer to it."""

    def __init__(self, process: asyncio.subprocess.Process, peer: Peer) -> None:
        self.process = process
        self.peer = peer
        self.log: list[bytes] = []

    async def exited(self, within: float) -> int:
        """The exit code, once the process is gone, or a timeout with its output."""
        try:
            return await asyncio.wait_for(self.process.wait(), within)
        except TimeoutError:
            self.process.kill()
            pytest.fail(f"the worker did not exit within {within}s:\n{self.output()}")

    def output(self) -> str:
        return b"".join(self.log).decode(errors="replace")


class Engine:
    """The fake engine: listens, starts workers, serves a body's calls as scripted."""

    def __init__(self, case: str) -> None:
        self.case = case
        self.answers: deque[tuple[str, object]] = deque()
        self.calls: list[tuple[str, object]] = []
        self.workers: list[Worker] = []
        self._connections: asyncio.Queue[tuple[Peer, asyncio.Future[object]]] = (
            asyncio.Queue()
        )
        self._server: asyncio.Server | None = None
        self._drains: list[asyncio.Task[None]] = []
        self.port = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._accept, "127.0.0.1", 0, limit=MAX_LINE
        )
        self.port = self._server.sockets[0].getsockname()[1]

    async def _accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = Peer(reader, writer)
        greeted: asyncio.Future[object] = asyncio.get_running_loop().create_future()

        async def hello(params: object) -> object:
            greeted.set_result(params)
            return None

        peer.on("hello", hello)
        for method in SERVED:
            peer.on(method, self._serving(method))
        self._connections.put_nowait((peer, greeted))
        await peer.serve()

    def _serving(self, method: str) -> Handler:
        async def handler(params: object) -> object:
            self.calls.append((method, params))
            if self.answers:
                scripted, answer = self.answers[0]
                assert scripted == method, (
                    f"{self.case}: the worker called {method}; expected {scripted}"
                )
                self.answers.popleft()
                if isinstance(answer, RpcError):
                    raise answer
                return answer
            return DEFAULT_ANSWERS.get(method, {})

        return handler

    async def spawn(self) -> Worker:
        """Start a worker as the engine would, and wait for its greeting."""
        env = {
            **os.environ,
            "ZUKE_ENGINE_ADDR": f"127.0.0.1:{self.port}",
            "ZUKE_ENGINE_TOKEN": TOKEN,
            "ZUKE_PROTOCOL": "1",
            "ZUKE_CONFORMANCE_CASE": self.case,
            "PYTHONPATH": str(TESTS),
        }
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(WORKER),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        peer, greeted = await asyncio.wait_for(self._connections.get(), 15)
        worker = Worker(process, peer)
        self.workers.append(worker)
        assert process.stdout is not None
        self._drains.append(asyncio.ensure_future(_drain(process.stdout, worker.log)))
        hello = await asyncio.wait_for(greeted, 15)
        assert is_record(hello)
        assert (hello["sdk"], hello["protocol"], hello["token"]) == (
            "zuke-python",
            1,
            TOKEN,
        )
        return worker

    async def close(self) -> None:
        for worker in self.workers:
            worker.peer.close()
            if worker.process.returncode is None:
                worker.process.kill()
                await worker.process.wait()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        for drain in self._drains:
            await drain


async def _drain(stream: asyncio.StreamReader, into: list[bytes]) -> None:
    while chunk := await stream.read(4096):
        into.append(chunk)


class Replay:
    """One case, driven call by call."""

    def __init__(self, case: str) -> None:
        self.name = case
        self.cancels = False
        self.case = load(case)
        self.manifest = manifest_of(case)
        self.scripts = {str(t["name"]): t for t in records(self.manifest["targets"])}
        self.attempts: dict[str, int] = {}
        self.ready: dict[str, list[bool]] = {}
        self.engine = Engine(case)
        self.worker: Worker

    async def run(self) -> None:
        await self.engine.start()
        try:
            if "engineDies" in self.case:
                await self.death()
                return
            await self.spawn_described(self.manifest)
            await self.drive(self.case)
            for then in records(self.case.get("then", [])):
                override = then.get("manifest")
                await self.spawn_described(
                    override if is_record(override) else self.manifest
                )
                await self.drive(then)
        finally:
            await self.engine.close()

    async def spawn_described(self, manifest: dict[str, object]) -> None:
        """A fresh worker, which must describe the build the case names."""
        self.worker = await self.engine.spawn()
        described = await self.ask("build.describe", {})
        assert described == expected(manifest), self.worker.output()

    async def ask(self, method: str, params: object) -> object:
        return await asyncio.wait_for(self.worker.peer.request(method, params), 10)

    async def drive(self, block: dict[str, object]) -> None:
        self.engine.answers = answers_of(block)
        self.cancels = any(
            isinstance(answer, RpcError) and answer.code == CANCELLED
            for _, answer in answers_of(block)
        )
        for line in field_strings(block, "calls", self.name):
            await self.call(line, block)
        assert not self.engine.answers, (
            f"{self.name}: answers left: {self.engine.answers}"
        )

    async def call(self, line: str, block: dict[str, object]) -> None:
        method, *args = line.split(" ")
        target = args[0] if args else ""
        script = self.scripts.get(target, {})
        if method == "build.configure":
            configure = block.get("configure")
            assert is_record(configure)
            assert await self.ask(method, configure) is None
        elif method == "target.run":
            await self.run_target(target, script)
        elif method == "target.condition":
            assert await self.ask(method, {"target": target}) == script.get(
                "condition_answer", True
            )
        elif method == "target.cacheKey":
            assert await self.ask(method, {"target": target}) == script.get(
                "cacheKey_answer", ""
            )
        elif method == "target.settings":
            assert await self.ask(method, {"target": target}) == script.get(
                "settings", {}
            )
        elif method == "wait.check":
            assert await self.ask(method, {"target": target}) == script.get(
                "wait_answer", False
            )
        elif method.startswith(("service.", "build.on")):
            await self.call_phase(method, target, args, script)
        elif method == "run.exit":
            code = block.get("code", 0)
            suspended = args[0] == "suspended"
            await self.worker.peer.notify(
                method, {"code": code, "suspended": suspended}
            )
            assert await self.worker.exited(5) == 0, self.worker.output()
        else:
            pytest.fail(f"{self.name}: the replay has no step for {line}")

    async def call_phase(
        self, method: str, target: str, args: list[str], script: dict[str, object]
    ) -> None:
        """A service phase or a build hook: its payload, and the expected answer."""
        if method == "service.start":
            handle = script.get("service_handle", "h1")
            assert await self.ask(method, {"target": target}) == {"handle": handle}
        elif method == "service.ready":
            answers = self.ready.setdefault(
                target, bools(script.get("ready_answers", [True]))
            )
            want = answers.pop(0) if len(answers) > 1 else answers[0]
            assert await self.ask(method, {"target": target, "handle": args[1]}) is want
        elif method == "service.stop":
            assert await self.ask(method, {"target": target, "handle": args[1]}) is None
        elif method == "build.onStart":
            assert await self.ask(method, {}) is None
        elif method == "build.onTargetStart":
            assert await self.ask(method, {"target": target}) is None
        elif method == "build.onTargetEnd":
            assert await self.ask(method, {"target": target, "status": args[1]}) is None
        elif method == "build.onFinish":
            assert await self.ask(method, {"ok": args[0] == "ok"}) is None
        else:
            pytest.fail(f"{self.name}: the replay has no step for {method}")

    async def run_target(self, target: str, script: dict[str, object]) -> None:
        attempt = self.attempts[target] = self.attempts.get(target, 0) + 1
        fail_times = script.get("failTimes", 0)
        assert isinstance(fail_times, int)
        crash = script.get("crash_exit")
        params = {"target": target, "runId": "r1", "dryRun": False}
        if isinstance(crash, int):
            with pytest.raises(RpcError):
                await self.ask("target.run", params)
            assert await self.worker.exited(5) == crash, self.worker.output()
            await self.spawn_described(self.manifest)
            return
        failure = (
            f"attempt {attempt} of {target} failed"
            if attempt <= fail_times
            else script.get("fail")
        )
        if isinstance(failure, str):
            with pytest.raises(RpcError, match=failure):
                await self.ask("target.run", params)
        elif self.cancels:
            # The engine cancelled a call the body made: the body unwinds, and
            # the worker answers the run as cancelled.
            with pytest.raises(RpcError, match="was cancelled") as cancelled:
                await self.ask("target.run", params)
            assert cancelled.value.code == CANCELLED
        else:
            assert await self.ask("target.run", params) is None, self.worker.output()

    async def death(self) -> None:
        """The engine dies mid-body: the worker's process must go within the bound."""
        dies = self.case.get("engineDies")
        assert is_record(dies)
        within = dies.get("workerExitsWithinMs")
        assert isinstance(within, int)
        await self.spawn_described(self.manifest)
        assert await self.ask("build.configure", {"parameters": {}}) is None
        _, target = str(dies.get("after")).split(" ")
        running = asyncio.ensure_future(
            self.worker.peer.request(
                "target.run", {"target": target, "runId": "r1", "dryRun": False}
            )
        )
        running.add_done_callback(lambda done: done.exception())
        await asyncio.sleep(0.2)
        self.worker.peer.close()
        assert await self.worker.exited(within / 1000) == 0, self.worker.output()


def test_the_cases_are_the_vendored_set() -> None:
    # Not a count, since the engine sync adds cases; an empty set passes vacuously.
    assert is_list(json.loads(json.dumps(cases()))) and len(cases()) > 0


@pytest.mark.parametrize("case", cases())
async def test_the_worker_passes_the_case(case: str) -> None:
    await Replay(case).run()
