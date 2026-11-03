# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The facade runtime: settings that record, the configure form, the call."""

from __future__ import annotations

import pytest

from conftest import Harness
from zuke import Context, ExecResult
from zuke._facade import Settings, call, configured, exec_result
from zuke._guard import ProtocolError


class Base(Settings):
    """Settings with a plain setter, an optional one, a rest one and a switch."""

    def name(self, value: str) -> Base:
        return self._record("name", value)

    def strict(self, on: bool | None = None) -> Base:
        return self._record("strict", on)

    def tags(self, *values: str) -> Base:
        return self._record("tags", *values)

    def inspecting(self) -> Inspect:
        return self._switch(Inspect, "inspecting")


class Inspect(Base):
    """What a kind-changing setter answers."""

    def fields(self, *names: str) -> Inspect:
        return self._record("fields", *names)


def test_record_keeps_order_and_drops_a_trailing_none() -> None:
    s = Base().name("w").strict().tags("a", "b").strict(False)
    assert s.calls_ == [
        ["name", ["w"]],
        ["strict", []],
        ["tags", ["a", "b"]],
        ["strict", [False]],
    ]


def test_switch_carries_every_call_into_the_new_settings() -> None:
    switched = Base().name("w").inspecting().fields("x")
    assert isinstance(switched, Inspect)
    assert switched.calls_ == [["name", ["w"]], ["inspecting", []], ["fields", ["x"]]]


def test_configured_is_the_lambda_calls_or_empty() -> None:
    assert configured(Base(), lambda s: s.name("w").tags()) == {
        "configure": [["name", ["w"]], ["tags", []]]
    }
    assert configured(Base(), None) == {"configure": []}
    # A lambda that switches answers the switched settings' calls.
    assert configured(Base(), lambda s: s.inspecting()) == {
        "configure": [["inspecting", []]]
    }


async def test_call_sends_tool_call_as_the_engine_names_it(harness: Harness) -> None:
    answers: list[object] = []

    async def body(ctx: Context) -> None:
        answers.append(
            await call(ctx, "widget", "1.2.3", "WidgetTasks", "build", ["x", {"a": 1}])
        )

    assert await harness.run(body, ("tool.call", {"code": 0})) is None
    assert harness.calls == [
        (
            "tool.call",
            {
                "target": "t",
                "package": "widget",
                "version": "1.2.3",
                "tasks": "WidgetTasks",
                "task": "build",
                "args": ["x", {"a": 1}],
            },
        )
    ]
    assert answers == [{"code": 0}]


def test_exec_result_reads_a_command_output_and_refuses_another() -> None:
    assert exec_result({"code": 1, "stdout": "o", "stderr": "e"}) == ExecResult(
        1, "o", "e"
    )
    with pytest.raises(ProtocolError, match=r'tool\.call: "code"'):
        exec_result({"stdout": "o", "stderr": "e"})
