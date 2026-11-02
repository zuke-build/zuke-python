# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The repository's own build file: its targets, and the vendoring body."""

from __future__ import annotations

import asyncio
from pathlib import Path

import build
import pytest
from build import Zuke

from conftest import served
from zuke._guard import is_list
from zuke._guard import strings as field_strings
from zuke._rpc import Handler, Peer


def test_the_gate_depends_on_every_check() -> None:
    manifest = Zuke().describe()
    assert [t["name"] for t in Zuke.targets_.values() for t in [t.manifest()]] == [
        "fmt",
        "fmt_check",
        "lint",
        "check",
        "test",
        "ci",
        "vendor_cases",
    ]
    assert Zuke.ci.manifest()["dependsOn"] == ["fmt_check", "lint", "check", "test"]
    assert Zuke.vendor_cases.manifest()["requires"] == ["engine_repo", "engine_tag"]
    assert is_list(manifest["ci"]) and len(manifest["ci"]) == 1


def test_the_workflow_is_declared_for_the_three_runners() -> None:
    declared = Zuke.ci_workflow.manifest()
    assert declared["path"] == ".github/workflows/ci.yml"
    invokes = declared["invokes"]
    assert isinstance(invokes, list) and isinstance(invokes[0], dict)
    assert invokes[0]["target"] == "ci"
    assert invokes[0]["matrix"] == {"os": build.RUNNERS}


def git(stdout_by_argv: dict[tuple[str, ...], str], seen: list[list[str]]) -> Handler:
    async def exec_(params: object) -> object:
        argv = field_strings(params, "argv", "exec")
        seen.append(argv)
        return {"code": 0, "stdout": stdout_by_argv[tuple(argv)], "stderr": ""}

    return exec_


async def test_vendor_cases_rewrites_the_cases_from_the_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build, "CASES", tmp_path)
    (tmp_path / "stale.json").write_text("{}")
    tree = "engine-v9.9.9:packages/engine/conformance"
    answers = {
        (
            "git",
            "-C",
            "../zuke",
            "ls-tree",
            "--name-only",
            tree,
        ): "README.md\na.json\nb.json\n",
        ("git", "-C", "../zuke", "show", f"{tree}/a.json"): '{"a": 1}',
        ("git", "-C", "../zuke", "show", f"{tree}/b.json"): '{"b": 2}',
    }
    seen: list[list[str]] = []
    logged: list[object] = []

    async def log(params: object) -> object:
        logged.append(params)
        return None

    peer: Peer
    async with served(Zuke()) as peer:
        peer.on("exec", git(answers, seen))
        peer.on("log", log)
        configure = {
            "parameters": {"engine_repo": "../zuke", "engine_tag": "engine-v9.9.9"}
        }
        await peer.request("build.configure", configure)
        run = {"target": "vendor_cases", "runId": "r1", "dryRun": False}
        assert await asyncio.wait_for(peer.request("target.run", run), 10) is None
    assert sorted(p.name for p in tmp_path.iterdir()) == ["VERSION", "a.json", "b.json"]
    assert (tmp_path / "a.json").read_text() == '{"a": 1}'
    assert (tmp_path / "VERSION").read_text() == "engine-v9.9.9\n"
    assert len(seen) == 3
    assert logged == [
        {
            "target": "vendor_cases",
            "line": "vendored the conformance cases at engine-v9.9.9",
        }
    ]


def test_a_parameter_the_target_needs_but_left_unset_is_named() -> None:
    Zuke.engine_tag.resolve(None)
    with pytest.raises(ValueError, match="--engine-tag is required"):
        build.required(Zuke.engine_tag)
