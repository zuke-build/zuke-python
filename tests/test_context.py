# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The body context against the fake engine: each call, its params, its guard."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from conftest import FakeEngine
from zuke import Build, CommandError, Context, ExecResult, Outcome, Plan, target
from zuke._rpc import CANCELLED, FAILED, Handler, RpcError
from zuke._worker import serve

Body = Callable[[Context], Awaitable[None] | None]


class Harness:
    """Runs one body as target ``t`` of a build served to a fresh fake engine."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        """Every request the body made, as the engine saw it."""

    async def run(self, body: Body | None, *answers: tuple[str, object]) -> object:
        """Run ``body`` as ``t``; the target.run answer, or the RpcError it ended in."""
        fields: dict[str, object] = {
            "t": target() if body is None else target().executes(body)
        }
        build = type("B", (Build,), fields)
        engine = FakeEngine()
        await engine.start()
        serving = asyncio.ensure_future(serve(build(), engine.environ, "."))
        peer = await engine.greeted()
        for method, result in answers:
            peer.on(method, self._answering(method, result))
        try:
            return await peer.request(
                "target.run", {"target": "t", "runId": "r1", "dryRun": False}
            )
        except RpcError as error:
            return error
        finally:
            await peer.notify("run.exit", {"code": 0, "suspended": False})
            await asyncio.wait_for(serving, 5)
            await engine.stop()

    def _answering(self, method: str, result: object) -> Handler:
        async def handler(params: object) -> object:
            self.calls.append((method, params))
            if isinstance(result, RpcError):
                raise result
            return result

        return handler


@pytest.fixture
def harness() -> Harness:
    return Harness()


def failure(answer: object) -> tuple[int, str]:
    assert isinstance(answer, RpcError)
    return answer.code, str(answer)


OK = {"code": 0, "stdout": "out", "stderr": ""}


async def test_a_body_may_be_sync_async_or_absent_and_sees_the_run(
    harness: Harness,
) -> None:
    seen: list[tuple[str, str, bool]] = []

    def sync(ctx: Context) -> None:
        seen.append((ctx.target, ctx.run_id, ctx.dry_run))

    async def slow(ctx: Context) -> None:
        seen.append((ctx.target, ctx.run_id, ctx.dry_run))

    assert await harness.run(sync) is None
    assert await Harness().run(slow) is None
    assert await Harness().run(None) is None
    assert seen == [("t", "r1", False)] * 2


async def test_sh_runs_the_command_through_the_engine(harness: Harness) -> None:
    got: list[ExecResult] = []

    async def body(ctx: Context) -> None:
        got.append(await ctx.sh("echo", "hi"))

    assert await harness.run(body, ("exec", OK)) is None
    assert harness.calls == [("exec", {"target": "t", "argv": ["echo", "hi"]})]
    assert got == [ExecResult(code=0, stdout="out", stderr="")]


async def test_sh_passes_cwd_env_and_stdin_only_when_given(harness: Harness) -> None:
    async def body(ctx: Context) -> None:
        await ctx.sh("cat", cwd="/w", env={"A": "1"}, stdin="in")

    await harness.run(body, ("exec", OK))
    assert harness.calls == [
        (
            "exec",
            {
                "target": "t",
                "argv": ["cat"],
                "cwd": "/w",
                "env": {"A": "1"},
                "stdin": "in",
            },
        )
    ]


async def test_sh_fails_the_body_on_a_non_zero_code_unless_told_not_to(
    harness: Harness,
) -> None:
    failed = {"code": 3, "stdout": "", "stderr": "bad"}

    async def body(ctx: Context) -> None:
        await ctx.sh("make", "all")

    assert failure(await harness.run(body, ("exec", failed))) == (
        FAILED,
        "`make all` exited with code 3",
    )

    caught: list[CommandError] = []

    async def catching(ctx: Context) -> None:
        try:
            await ctx.sh("make", "all")
        except CommandError as error:
            caught.append(error)
        assert (await ctx.sh("make", check=False)).code == 3

    assert await Harness().run(catching, ("exec", failed)) is None
    assert caught[0].argv == ("make", "all")
    assert caught[0].result == ExecResult(3, "", "bad")


async def test_an_exec_the_engine_cancelled_unwinds_the_body_as_cancelled(
    harness: Harness,
) -> None:
    after: list[str] = []

    async def body(ctx: Context) -> None:
        await ctx.sh("sleep", "100")
        after.append("not reached")

    answer = await harness.run(body, ("exec", RpcError(CANCELLED, "cancelled")))
    assert failure(answer) == (CANCELLED, '"t" was cancelled')
    assert after == []


async def test_any_other_engine_refusal_fails_the_body_with_its_code_and_message(
    harness: Harness,
) -> None:
    async def body(ctx: Context) -> None:
        await ctx.sh()

    refusal = RpcError(-32602, "exec: argv must not be empty")
    # The engine's own code travels back out with the body's failure.
    assert failure(await harness.run(body, ("exec", refusal))) == (
        -32602,
        "exec: argv must not be empty",
    )


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ("not an object", 'exec: "code" must be an integer'),
        ({"code": True, "stdout": "", "stderr": ""}, 'exec: "code" must be an integer'),
        ({"code": 0, "stdout": 1, "stderr": ""}, 'exec: "stdout" must be a string'),
    ],
)
async def test_a_malformed_exec_answer_is_refused_naming_the_field(
    harness: Harness, answer: object, message: str
) -> None:
    async def body(ctx: Context) -> None:
        await ctx.sh("x")

    assert failure(await harness.run(body, ("exec", answer))) == (FAILED, message)


async def test_state_is_read_and_written_for_this_target_or_another(
    harness: Harness,
) -> None:
    got: list[object] = []

    async def body(ctx: Context) -> None:
        got.append(await ctx.state.get())
        await ctx.state.set({"revision": "r1"})
        got.append(await ctx.state.try_set({"seen": True}))
        got.append(await ctx.state_of("writer").get())
        got.append(await ctx.state_of("writer").try_set({"seen": True}))

    answers: tuple[tuple[str, object], ...] = (
        ("state.get", {"revision": "r0"}),
        ("state.set", {}),
        ("state.trySet", {"recorded": False}),
    )
    assert await harness.run(body, *answers) is None
    assert got == [{"revision": "r0"}, False, {"revision": "r0"}, False]
    assert harness.calls == [
        ("state.get", {"target": "t"}),
        ("state.set", {"target": "t", "patch": {"revision": "r1"}}),
        ("state.trySet", {"target": "t", "patch": {"seen": True}}),
        ("state.get", {"target": "t", "of": "writer"}),
        ("state.trySet", {"target": "t", "patch": {"seen": True}, "of": "writer"}),
    ]


async def test_a_state_answer_that_is_not_what_was_asked_is_refused(
    harness: Harness,
) -> None:
    async def reads(ctx: Context) -> None:
        await ctx.state.get()

    async def tries(ctx: Context) -> None:
        await ctx.state.try_set({})

    assert failure(await harness.run(reads, ("state.get", []))) == (
        FAILED,
        "state.get: the answer must be an object",
    )
    assert failure(await Harness().run(tries, ("state.trySet", {}))) == (
        FAILED,
        'state.trySet: "recorded" must be a boolean',
    )


async def test_outcomes_of_other_targets_are_read_by_name_or_all_at_once(
    harness: Harness,
) -> None:
    got: list[object] = []
    view = {"status": "succeeded", "startedAt": "2026-11-02T10:00:00Z"}

    async def body(ctx: Context) -> None:
        got.append(await ctx.outcome_of("lint"))
        got.append(await ctx.outcome_of("later"))
        got.append(await ctx.outcomes())

    outcome = Outcome(
        status="succeeded", error=None, started_at=view["startedAt"], ended_at=None
    )
    assert (
        await harness.run(body, ("outcome.of", view), ("outcomes", {"lint": view}))
        is None
    )
    assert got[0] == outcome
    assert got[2] == {"lint": outcome}
    assert harness.calls[:2] == [
        ("outcome.of", {"target": "t", "of": "lint"}),
        ("outcome.of", {"target": "t", "of": "later"}),
    ]


async def test_an_outcome_not_yet_known_is_none_and_a_malformed_one_is_refused(
    harness: Harness,
) -> None:
    got: list[object] = []

    async def body(ctx: Context) -> None:
        got.append(await ctx.outcome_of("later"))

    assert await harness.run(body, ("outcome.of", None)) is None
    assert got == [None]

    async def all_of_them(ctx: Context) -> None:
        await ctx.outcomes()

    bad = {"lint": {"status": "failed", "error": 7}}
    assert failure(await Harness().run(all_of_them, ("outcomes", bad))) == (
        FAILED,
        'outcomes: lint: "error" must be a string when present',
    )


async def test_summary_secret_and_log_carry_their_payloads(harness: Harness) -> None:
    async def body(ctx: Context) -> None:
        await ctx.summary({"Tests": 12, "Suite": "unit"})
        await ctx.secret("hunter2")
        await ctx.log("done")

    answers: tuple[tuple[str, object], ...] = (
        ("summary.report", {}),
        ("secret.register", {}),
        ("log", {}),
    )
    assert await harness.run(body, *answers) is None
    assert harness.calls == [
        ("summary.report", {"target": "t", "pairs": {"Tests": 12, "Suite": "unit"}}),
        ("secret.register", {"target": "t", "value": "hunter2"}),
        ("log", {"target": "t", "line": "done"}),
    ]


async def test_the_plan_and_the_signals_are_read_back(harness: Harness) -> None:
    got: list[object] = []

    async def body(ctx: Context) -> None:
        got.append(await ctx.plan())
        got.append(await ctx.signals())

    plan = {"targets": ["a", "b"], "dependencies": {"a": [], "b": ["a"]}}
    signals = {"approved": {"by": "alice"}}
    assert await harness.run(body, ("plan", plan), ("signals", signals)) is None
    assert got == [
        Plan(targets=["a", "b"], dependencies={"a": [], "b": ["a"]}),
        signals,
    ]


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ({"targets": ["a"]}, 'plan: "dependencies" must be an object'),
        (
            {"targets": "a", "dependencies": {}},
            'plan: "targets" must be a list of strings',
        ),
        (
            {"targets": [], "dependencies": {"a": [1]}},
            'plan: "a" must be a list of strings',
        ),
    ],
)
async def test_a_malformed_plan_is_refused_naming_the_field(
    harness: Harness, answer: object, message: str
) -> None:
    async def body(ctx: Context) -> None:
        await ctx.plan()

    assert failure(await harness.run(body, ("plan", answer))) == (FAILED, message)


async def test_malformed_signals_are_refused(harness: Harness) -> None:
    async def body(ctx: Context) -> None:
        await ctx.signals()

    assert failure(await harness.run(body, ("signals", 1))) == (
        FAILED,
        "signals: the answer must be an object",
    )
