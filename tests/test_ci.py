# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""CI files: declared as fields, rendered by the engine from the manifest."""

from __future__ import annotations

import pytest

from zuke import Build, ci, invoke, target


class Pipelines(Build):
    lint = target()
    test = target().depends_on(lint)
    gate_workflow = (
        ci()
        .pipeline({"name": "Gate", "triggers": {"push": ["main"]}})
        .invokes(lint, invoke(test, after=[lint], matrix={"os": ["ubuntu-latest"]}))
    )
    release = (
        ci()
        .provider("gitlab")
        .path("ci/release.yml")
        .fan_out({"include": ["test"]})
        .pins({"actions/checkout": "actions/checkout@0000"})
    )
    nightly = ci().fan_out()


def test_ci_files_are_discovered_and_described() -> None:
    assert list(Pipelines.ci_) == ["gate_workflow", "release", "nightly"]
    assert Pipelines().describe()["ci"] == [
        {
            "name": "gate_workflow",
            "pipeline": {"name": "Gate", "triggers": {"push": ["main"]}},
            "invokes": [
                "lint",
                {
                    "target": "test",
                    "after": ["lint"],
                    "matrix": {"os": ["ubuntu-latest"]},
                },
            ],
        },
        {
            "name": "release",
            "provider": "gitlab",
            "path": "ci/release.yml",
            "fanOut": {"include": ["test"]},
            "pins": {"actions/checkout": "actions/checkout@0000"},
        },
        {"name": "nightly", "fanOut": True},
    ]


def test_invocations_may_name_targets_or_reference_them() -> None:
    assert invoke("test", after=["lint"], matrix={"os": []}) == {
        "target": "test",
        "after": ["lint"],
        "matrix": {"os": []},
    }
    assert invoke("lint") == {"target": "lint"}


def test_an_invoked_target_must_be_a_field_of_the_build() -> None:
    with pytest.raises(
        TypeError, match=r'Bad\.gate: invokes names no target named "nope"'
    ):
        type("Bad", (Build,), {"gate": ci().invokes("nope")})
    with pytest.raises(
        TypeError, match=r"Bad\.gate: invokes names a target that is not"
    ):
        type("Bad", (Build,), {"gate": ci().invokes(invoke(Pipelines.lint))})
    with pytest.raises(
        TypeError, match=r'Bad\.gate: invokes names no target named "later"'
    ):
        fields = {"a": target(), "gate": ci().invokes(invoke("a", after=["later"]))}
        type("Bad", (Build,), fields)
