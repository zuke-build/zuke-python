# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""Conditions, cache keys and the late settings: lock, wait gate, interval checks."""

from __future__ import annotations

import pytest

from conftest import served
from zuke import (
    Build,
    LockSettings,
    ValidateDuringSettings,
    WaitSettings,
    parameter,
    target,
)
from zuke._rpc import FAILED, RpcError


def failing() -> None:
    raise RuntimeError("check healthy found a problem")


class Gated(Build):
    env = parameter("environment").default("dev")

    on = target().condition(lambda: True)
    off = target().condition(lambda: False)
    keyed = target().cache_key(lambda: "k1")
    deploy = target().lock(
        lambda s: s.key(f"deploy-{Gated.env.value}").ttl("1h").hold_for_run()
    )
    gate = target().waits_for(lambda s: s.external_signal("approved").timeout("72h"))
    poll = target().waits_for(lambda s: s.resume_when(lambda: True, every="1s"))
    watched = target().validate_during(
        lambda s: s.every("1m").check("healthy", failing).check("fine", lambda: None)
    )
    plain = target()


def test_the_manifest_flags_what_the_engine_must_ask() -> None:
    flags = {
        t["name"]: {k for k in t if k != "name"}
        for t in Gated.targets_.values()
        for t in [t.manifest()]
    }
    assert flags == {
        "on": {"condition"},
        "off": {"condition"},
        "keyed": {"cacheKey"},
        "deploy": {"lock"},
        "gate": {"waitsFor"},
        "poll": {"waitsFor"},
        "watched": {"validateDuring"},
        "plain": set(),
    }


async def test_condition_and_cache_key_are_answered() -> None:
    async with served(Gated()) as peer:
        assert await peer.request("target.condition", {"target": "on"}) is True
        assert await peer.request("target.condition", {"target": "off"}) is False
        assert await peer.request("target.cacheKey", {"target": "keyed"}) == "k1"


async def test_late_settings_are_evaluated_after_configure() -> None:
    async with served(Gated()) as peer:
        await peer.request("build.configure", {"parameters": {"env": "prod"}})
        assert await peer.request("target.settings", {"target": "deploy"}) == {
            "lock": {"key": "deploy-prod", "ttl": "1h", "holdForRun": True}
        }
        assert await peer.request("target.settings", {"target": "gate"}) == {
            "waitsFor": {
                "on": {"kind": "externalSignal", "name": "approved"},
                "timeout": "72h",
            }
        }
        assert await peer.request("target.settings", {"target": "poll"}) == {
            "waitsFor": {"on": {"kind": "resumeWhen", "interval": "1s"}}
        }
        assert await peer.request("target.settings", {"target": "watched"}) == {
            "validateDuring": {"every": "1m", "checks": ["healthy", "fine"]}
        }
        assert await peer.request("target.settings", {"target": "plain"}) == {}


async def test_wait_check_and_validate_run_the_declared_functions() -> None:
    async with served(Gated()) as peer:
        assert await peer.request("wait.check", {"target": "poll"}) is True
        assert (
            await peer.request(
                "target.validate", {"target": "watched", "check": "fine"}
            )
            is None
        )
        with pytest.raises(RpcError) as caught:
            await peer.request(
                "target.validate", {"target": "watched", "check": "healthy"}
            )
        assert (caught.value.code, str(caught.value)) == (
            FAILED,
            "check healthy found a problem",
        )


@pytest.mark.parametrize(
    ("method", "params", "message"),
    [
        ("target.condition", {"target": "plain"}, '"plain" declared no condition'),
        ("target.cacheKey", {"target": "plain"}, '"plain" declared no cache key'),
        ("wait.check", {"target": "gate"}, '"gate" declared no resume_when check'),
        ("wait.check", {"target": "plain"}, '"plain" declared no resume_when check'),
        (
            "target.validate",
            {"target": "watched", "check": "nope"},
            'declared no check "nope"',
        ),
        (
            "target.validate",
            {"target": "plain", "check": "x"},
            '"plain" declared no check "x"',
        ),
        ("target.validate", {"target": "plain"}, '"check" must be a string'),
        ("target.condition", {"target": "nope"}, 'Gated has no target "nope"'),
    ],
)
async def test_an_undeclared_answer_is_refused_by_name(
    method: str, params: object, message: str
) -> None:
    async with served(Gated()) as peer:
        with pytest.raises(RpcError, match=f"{method}: .*{message}"):
            await peer.request(method, params)


def test_every_lock_and_wait_setter_reaches_the_section() -> None:
    lock = (
        LockSettings()
        .key("k")
        .ttl("1h")
        .wait_up_to("5m")
        .poll_every(100)
        .hold_for_run()
    )
    assert lock.manifest() == {
        "key": "k",
        "ttl": "1h",
        "waitUpTo": "5m",
        "pollEvery": 100,
        "holdForRun": True,
    }
    wait = WaitSettings().external_signal("go").timeout("1d").on_timeout("cancel-run")
    assert wait.manifest() == {
        "on": {"kind": "externalSignal", "name": "go"},
        "timeout": "1d",
        "onTimeout": "cancel-run",
    }
    assert wait.check is None
    assert ValidateDuringSettings().manifest() == {"checks": []}


async def test_a_lock_without_a_key_and_a_gate_without_a_trigger_are_refused() -> None:
    class Bad(Build):
        locked = target().lock(lambda s: s.ttl("1h"))
        gated = target().waits_for(lambda s: s.timeout("1h"))

    async with served(Bad()) as peer:
        with pytest.raises(RpcError, match="lock: a key is required"):
            await peer.request("target.settings", {"target": "locked"})
        with pytest.raises(RpcError, match="waits_for: name the trigger"):
            await peer.request("target.settings", {"target": "gated"})
