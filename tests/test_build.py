# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The build class: field discovery, reference checks, what the worker asks of it."""

from __future__ import annotations

import asyncio

import pytest

from conftest import FakeEngine
from twins import records
from zuke import Build, group, parameter, target
from zuke._rpc import RpcError
from zuke._worker import serve


class CI(Build):
    """The README's shape, bodies aside."""

    tag = parameter("image tag").default("dev")
    count = parameter("how many").number()

    lint = target().description("ruff")
    test = target().depends_on(lint).requires(count)
    image = target().depends_on(test).requires(tag).after("publish")
    publish = target().depends_on(image).unlisted()
    verify = group(lint, test)

    deadline = "1h"
    unforceable = (publish,)


def test_fields_are_discovered_in_declaration_order_and_named() -> None:
    assert list(CI.targets_) == ["lint", "test", "image", "publish"]
    assert list(CI.parameters_) == ["tag", "count"]
    assert list(CI.groups_) == ["verify"]
    assert CI.lint.name == "lint"
    assert CI.tag.name == "tag"


def test_describe_is_the_manifest() -> None:
    assert CI().describe() == {
        "name": "CI",
        "targets": [
            {"name": "lint", "description": "ruff"},
            {"name": "test", "dependsOn": ["lint"], "requires": ["count"]},
            {
                "name": "image",
                "dependsOn": ["test"],
                "after": ["publish"],
                "requires": ["tag"],
            },
            {"name": "publish", "dependsOn": ["image"], "unlisted": True},
        ],
        "parameters": [
            {"name": "tag", "description": "image tag", "default": "dev"},
            {"name": "count", "description": "how many", "kind": "number"},
        ],
        "groups": [{"name": "verify", "members": ["lint", "test"]}],
        "config": {"deadline": "1h", "unforceable": ["publish"]},
    }


def test_a_subclass_inherits_its_parents_fields_first() -> None:
    class Base(Build):
        lint = target()

    class More(Base):
        test = target().depends_on(Base.lint)

    assert list(More.targets_) == ["lint", "test"]
    assert More().describe()["targets"] == [
        {"name": "lint"},
        {"name": "test", "dependsOn": ["lint"]},
    ]


def test_a_forward_dependency_is_a_name_error_where_it_is_written() -> None:
    source = "class Bad(Build):\n    first = target().depends_on(later)\n"
    source += "    later = target()\n"
    with pytest.raises(NameError, match="later"):
        exec(source, {"Build": Build, "target": target})


def test_a_dependency_on_a_target_of_another_build_is_refused() -> None:
    with pytest.raises(
        TypeError, match=r"Bad\.test: depends_on names a target that is not"
    ):
        type("Bad", (Build,), {"test": target().depends_on(CI.lint)})


@pytest.mark.parametrize(
    "setter", ["before", "after", "triggers", "on_cancel", "on_failure"]
)
def test_a_soft_reference_by_name_must_name_a_field(setter: str) -> None:
    t = target()
    getattr(t, setter)("nope")
    with pytest.raises(
        TypeError, match=rf'Bad\.a: {setter} names no target named "nope"'
    ):
        type("Bad", (Build,), {"a": t})


def test_the_dispositions_are_not_target_names() -> None:
    class Ok(Build):
        a = target().on_failure("fail")
        b = target().on_failure("cancel-run")

    assert [t["onFailure"] for t in records(Ok().describe()["targets"])] == [
        "fail",
        "cancel-run",
    ]


def test_a_required_parameter_of_another_build_is_refused() -> None:
    with pytest.raises(
        TypeError, match=r"Bad\.a: requires names a parameter that is not"
    ):
        type("Bad", (Build,), {"a": target().requires(CI.tag)})


def test_a_group_member_and_an_unforceable_target_must_be_fields() -> None:
    with pytest.raises(TypeError, match=r"Bad\.g: group names a target that is not"):
        type("Bad", (Build,), {"g": group(CI.lint)})
    with pytest.raises(
        TypeError, match=r"Worse\.unforceable: unforceable names a target"
    ):
        type("Worse", (Build,), {"unforceable": (CI.lint,)})


async def test_the_worker_serves_a_build_end_to_end(engine: FakeEngine) -> None:
    seen: list[tuple[str | None, float | None, str, str, bool]] = []

    class App(Build):
        tag = parameter().default("dev")
        count = parameter().number()
        show = target().executes(
            lambda ctx: seen.append(
                (App.tag.value, App.count.value, ctx.target, ctx.run_id, ctx.dry_run)
            )
        )

    serving = asyncio.ensure_future(serve(App(), engine.environ, "."))
    peer = await engine.greeted()
    assert await peer.request("build.describe", {}) == App().describe()
    await peer.request("build.configure", {"parameters": {"tag": "v1", "count": "3"}})
    run = {"target": "show", "runId": "r1", "dryRun": True}
    assert await peer.request("target.run", run) is None
    with pytest.raises(RpcError, match=r'target\.run: App has no target "nope"'):
        await peer.request("target.run", {**run, "target": "nope"})
    await peer.notify("run.exit", {"code": 0, "suspended": False})
    await asyncio.wait_for(serving, 5)
    assert seen == [("v1", 3, "show", "r1", True)]
