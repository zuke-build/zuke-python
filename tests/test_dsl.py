# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The builders: every setter in the manifest, parameter values, durations."""

from __future__ import annotations

import pytest

from zuke import Build, Group, Target, group, parameter, target


def named(t: Target, name: str) -> Target:
    t.name_ = name
    return t


def test_a_bare_target_is_only_its_name() -> None:
    assert named(target(), "lint").manifest() == {"name": "lint"}


def test_every_target_setting_reaches_the_manifest() -> None:
    lint = named(target(), "lint")
    rollback = named(target(), "rollback")
    tag = parameter("tag")
    tag.name_ = "tag"
    t = (
        target()
        .description("build it")
        .depends_on(lint)
        .unlisted()
        .inputs("src/**")
        .outputs("dist/app")
        .produces("dist/app")
        .retry(2, "10s")
        .timeout("5m")
        .before("publish")
        .after(lint)
        .triggers("smoke")
        .proceed_after_failure()
        .always()
        .dry_runnable()
        .requires(tag)
        .on_cancel(rollback)
        .on_failure("cancel-run")
    )
    assert named(t, "build").manifest() == {
        "name": "build",
        "description": "build it",
        "dependsOn": ["lint"],
        "unlisted": True,
        "inputs": ["src/**"],
        "outputs": ["dist/app"],
        "produces": ["dist/app"],
        "retry": {"times": 2, "delayMs": 10_000},
        "timeoutMs": 300_000,
        "before": ["publish"],
        "after": ["lint"],
        "triggers": ["smoke"],
        "proceedAfterFailure": True,
        "always": True,
        "dryRunnable": True,
        "requires": ["tag"],
        "onCancel": "rollback",
        "onFailure": "cancel-run",
    }


def test_a_compensation_target_is_named_in_the_manifest() -> None:
    rollback = named(target(), "rollback")
    assert (
        named(target().on_failure(rollback), "d").manifest()["onFailure"] == "rollback"
    )


@pytest.mark.parametrize(
    ("given", "ms"),
    [
        (250, 250),
        ("250ms", 250),
        ("90s", 90_000),
        ("5m", 300_000),
        ("2h", 7_200_000),
        ("1d", 86_400_000),
    ],
)
def test_durations_are_milliseconds_or_a_unit_suffix(given: str | int, ms: int) -> None:
    assert named(target().timeout(given), "t").manifest()["timeoutMs"] == ms


def test_a_malformed_duration_is_refused_by_the_setter() -> None:
    with pytest.raises(ValueError, match='retry: "soon" is not a duration'):
        target().retry(1, "soon")


def test_an_unnamed_field_says_how_it_gets_a_name() -> None:
    with pytest.raises(RuntimeError, match="named by the Build"):
        target().manifest()


def test_a_bare_parameter_is_a_string_with_only_its_name() -> None:
    p = parameter()
    p.name_ = "tag"
    assert p.manifest() == {"name": "tag"}


def test_every_parameter_setting_reaches_the_manifest() -> None:
    p = parameter("image tag").default("dev").options("dev", "prod").required().secret()
    p = p.flag("image-tag").env("IMAGE_TAG")
    p.name_ = "tag"
    assert p.manifest() == {
        "name": "tag",
        "description": "image tag",
        "default": "dev",
        "options": ["dev", "prod"],
        "required": True,
        "secret": True,
        "flag": "image-tag",
        "env": "IMAGE_TAG",
    }


def test_changing_the_kind_keeps_what_was_set_before() -> None:
    n = parameter("count").required().secret().flag("n").env("N").number().default(3)
    n.name_ = "count"
    assert n.manifest() == {
        "name": "count",
        "description": "count",
        "kind": "number",
        "default": 3,
        "required": True,
        "secret": True,
        "flag": "n",
        "env": "N",
    }
    b = parameter("verbose").required().boolean().default(True)
    b.name_ = "verbose"
    assert b.manifest() == {
        "name": "verbose",
        "description": "verbose",
        "kind": "boolean",
        "default": True,
        "required": True,
    }


def test_list_parameters_are_arrays_of_their_kind() -> None:
    tags = parameter().array()
    tags.name_ = "tags"
    counts = parameter().number().array()
    counts.name_ = "counts"
    assert tags.manifest() == {"name": "tags", "array": True}
    assert counts.manifest() == {"name": "counts", "kind": "number", "array": True}


def test_values_parse_the_cli_form_by_kind() -> None:
    s, n, f = parameter(), parameter().number(), parameter().number()
    b, sl, nl = parameter().boolean(), parameter().array(), parameter().number().array()
    for p, raw in (
        (s, "dev"),
        (n, "3"),
        (f, "2.5"),
        (b, "true"),
        (sl, "a,b"),
        (nl, "1,2.5"),
    ):
        p.resolve(raw)
    assert (s.value, n.value, f.value, b.value, sl.value, nl.value) == (
        "dev",
        3,
        2.5,
        True,
        ["a", "b"],
        [1, 2.5],
    )
    assert isinstance(n.value, int)
    b.resolve("false")
    assert b.value is False


def test_an_unset_value_is_none_once_configured_and_an_error_before() -> None:
    p = parameter()
    p.name_ = "tag"
    with pytest.raises(RuntimeError, match='parameter "tag" has no value before'):
        _ = p.value
    p.resolve(None)
    assert p.value is None


def test_a_group_names_its_members() -> None:
    a, b = named(target(), "a"), named(target(), "b")
    g = group(a, b)
    g.name_ = "both"
    assert isinstance(g, Group)
    assert g.manifest() == {"name": "both", "members": ["a", "b"]}


def test_build_is_the_base_class_users_extend() -> None:
    class Empty(Build):
        pass

    assert Empty().describe() == {"name": "Empty", "targets": []}
