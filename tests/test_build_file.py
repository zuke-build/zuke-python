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
from zuke._rpc import Handler, Peer, RpcError, is_record


def test_the_gate_depends_on_every_check() -> None:
    manifest = Zuke().describe()
    assert [t["name"] for t in Zuke.targets_.values() for t in [t.manifest()]] == [
        "fmt",
        "fmt_check",
        "lint",
        "check",
        "test",
        "facades",
        "facades_check",
        "ci",
        "review_base",
        "review",
        "review_preflight",
        "vendor_cases",
        "vendor_spec",
    ]
    assert Zuke.ci.manifest()["dependsOn"] == [
        "fmt_check",
        "lint",
        "check",
        "test",
        "facades_check",
    ]
    assert Zuke.vendor_cases.manifest()["requires"] == ["engine_repo", "engine_tag"]
    assert is_list(manifest["ci"]) and len(manifest["ci"]) == 2
    assert Zuke.review.manifest()["dependsOn"] == ["review_base"]


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


async def test_vendor_spec_then_facades_then_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build, "SPEC", tmp_path / "spec")
    monkeypatch.setattr(build, "TOOLS", tmp_path / "tools")
    fixtures = Path(__file__).parent / "fixtures"
    spec = (fixtures / "spec.json").read_text()
    at = "engine-v9.9.9:packages"
    answers: dict[tuple[str, ...], str] = {
        ("git", "-C", "../zuke", "show", f"{at}/engine/spec/tools.json"): spec,
        (
            "git",
            "-C",
            "../zuke",
            "show",
            f"{at}/widget/deno.json",
        ): '{"version":"0.1.0"}',
        (
            "git",
            "-C",
            "../zuke",
            "show",
            f"{at}/tally/deno.json",
        ): '{"version":"0.2.0"}',
    }
    seen: list[list[str]] = []
    logged: list[str] = []

    async def exec_(params: object) -> object:
        argv = field_strings(params, "argv", "exec")
        seen.append(argv)
        # A ruff format run answers nothing; a git show answers the file.
        return {"code": 0, "stdout": answers.get(tuple(argv), ""), "stderr": ""}

    async def log(params: object) -> object:
        logged.append(str(params))
        return None

    peer: Peer
    async with served(Zuke()) as peer:
        peer.on("exec", exec_)
        peer.on("log", log)
        configure = {
            "parameters": {"engine_repo": "../zuke", "engine_tag": "engine-v9.9.9"}
        }
        await peer.request("build.configure", configure)

        async def run(target: str) -> object:
            params = {"target": target, "runId": "r1", "dryRun": False}
            return await asyncio.wait_for(peer.request("target.run", params), 10)

        assert await run("vendor_spec") is None
        assert (tmp_path / "spec" / "tools.json").read_text() == spec
        assert (tmp_path / "spec" / "engine.json").read_text() == (
            '{\n  "tag": "engine-v9.9.9",\n  "versions": {\n'
            '    "widget": "0.1.0",\n    "tally": "0.2.0"\n  }\n}\n'
        )
        assert await run("facades") is None
        written = sorted(p.name for p in (tmp_path / "tools").iterdir())
        assert written == ["__init__.py", "_tooling.py", "tally.py", "widget.py"]
        golden = (fixtures / "facades" / "widget.py").read_text()
        assert (tmp_path / "tools" / "widget.py").read_text() == golden
        assert seen[-1][:5] == ["uv", "run", "ruff", "format", "--quiet"]
        assert seen[-1][-1] == str(tmp_path / "tools")
        assert await run("facades_check") is None
        (tmp_path / "tools" / "tally.py").write_text("stale")
        (tmp_path / "tools" / "extra.py").write_text("")
        with pytest.raises(RpcError, match=r"out of date: extra\.py, tally\.py"):
            await run("facades_check")
    assert "matches the vendored spec" in logged[-1]


def test_the_ai_review_workflow_runs_on_pull_requests_and_on_command() -> None:
    declared = Zuke.ai_review.manifest()
    assert declared["path"] == ".github/workflows/ai-review.yml"
    pipeline = declared["pipeline"]
    assert isinstance(pipeline, dict)
    assert pipeline["triggers"] == {"pullRequest": [], "issueComment": ["created"]}
    invokes = declared["invokes"]
    assert is_list(invokes) and len(invokes) == 2
    push, command = invokes
    assert is_record(push) and is_record(command)
    assert [push["target"], command["target"]] == ["review", "review"]
    assert [push["id"], command["id"]] == ["review", "commandReview"]
    assert "github.event_name == 'pull_request'" in str(push["if"])
    assert "@zuke-build review" in str(command["if"])
    steps = command["steps"]
    assert is_list(steps) and len(steps) == 4
    assert [step["run"] for step in steps if is_record(step)] == [
        "pipx install uv",
        "uv sync --locked",
        "./zuke review_preflight",
        "./zuke review",
    ]


def configure_calls(params: object) -> list[object]:
    """The setter calls a ``tool.call`` carries in its first argument."""
    assert is_record(params) and is_list(params["args"])
    first = params["args"][0]
    assert is_record(first) and is_list(first["configure"])
    return first["configure"]


async def test_review_base_fetches_main_and_the_review_calls_the_reviewers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    logged: list[object] = []

    async def tool_call(params: object) -> object:
        calls.append(params)
        return {"code": 1, "stdout": "", "stderr": ""}

    async def log(params: object) -> object:
        logged.append(params)
        return None

    peer: Peer
    async with served(Zuke()) as peer:
        peer.on("tool.call", tool_call)
        peer.on("log", log)
        await peer.request("build.configure", {"parameters": {"openai_key": "sk"}})
        for target in ("review_base", "review", "review_preflight"):
            params = {"target": target, "runId": "r1", "dryRun": False}
            ran = peer.request("target.run", params)
            assert await asyncio.wait_for(ran, 10) is None
    fetch, review, preflight = calls
    assert is_record(fetch) and (fetch["package"], fetch["task"]) == ("git", "fetch")
    assert configure_calls(fetch) == [
        ["remote", ["origin"]],
        ["refspec", ["+main:refs/remotes/origin/main"]],
        ["noTags", []],
        ["depth", [1]],
        ["noThrow", []],
        ["quiet", []],
    ]
    assert str(logged[-1]).startswith("{'target': 'review_base', 'line': 'could not")
    assert is_record(review) and (review["package"], review["task"]) == ("ai", "review")
    assert is_record(preflight) and preflight["task"] == "preflight"
    assert configure_calls(review) == configure_calls(preflight)
    security, generic = configure_calls(review)
    assert is_list(security) and security[0] == "security"
    assert is_list(generic) and generic[0] == "generic"
    assert is_list(security[1]) and is_record(security[1][0])
    setters = security[1][0]["configure"]
    assert is_list(setters)
    names = [call[0] for call in setters if is_list(call)]
    assert names == [
        "provider",
        "skipIfKeyMissing",
        "apiKey",
        "comment",
        "diff",
        "maxDiffTokens",
        "conventionsFile",
        "verify",
        "discussion",
        "failWhen",
        "onError",
        "fileContext",
    ]
    assert setters[2] == ["apiKey", ["sk"]]
    assert setters[4] == ["diff", [{"configure": [["base", ["origin/main"]]]}]]
    assert setters[9] == ["failWhen", [{"configure": [["scoreAbove", [5]]]}]]


async def test_the_review_leaves_the_key_out_when_the_parameter_is_unset() -> None:
    calls: list[object] = []

    async def tool_call(params: object) -> object:
        calls.append(params)
        return None

    peer: Peer
    async with served(Zuke()) as peer:
        peer.on("tool.call", tool_call)
        await peer.request("build.configure", {"parameters": {}})
        params = {"target": "review_preflight", "runId": "r1", "dryRun": False}
        assert await asyncio.wait_for(peer.request("target.run", params), 10) is None
    security, _ = configure_calls(calls[0])
    assert is_list(security) and is_list(security[1]) and is_record(security[1][0])
    setters = security[1][0]["configure"]
    assert is_list(setters)
    assert "apiKey" not in [call[0] for call in setters if is_list(call)]
