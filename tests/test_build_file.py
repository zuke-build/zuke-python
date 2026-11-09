# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The repository's own build file: its targets, and the vendoring body."""

from __future__ import annotations

import asyncio
import json
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
        "publish",
        "api_reference",
        "sync_website",
        "vendor_cases",
        "vendor_spec",
        "sync_engine",
    ]
    assert Zuke.ci.manifest()["dependsOn"] == [
        "fmt_check",
        "lint",
        "check",
        "test",
        "facades_check",
    ]
    assert Zuke.vendor_cases.manifest()["requires"] == ["engine_repo", "engine_tag"]
    assert is_list(manifest["ci"]) and len(manifest["ci"]) == 4
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
            f"{at}/engine/deno.json",
        ): '{"version":"1.4.0"}',
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

    cached: list[object] = []

    async def tool_call(params: object) -> object:
        cached.append(params)
        return {"code": 0, "stdout": "", "stderr": ""}

    peer: Peer
    async with served(Zuke()) as peer:
        peer.on("exec", exec_)
        peer.on("log", log)
        peer.on("tool.call", tool_call)
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
            '{\n  "tag": "engine-v9.9.9",\n  "engine": "1.4.0",\n  "versions": {\n'
            '    "widget": "0.1.0",\n    "tally": "0.2.0"\n  }\n}\n'
        )
        # Nothing is locked: the zuke binary carries the exact releases.
        assert cached == []
        assert "vendored the tool spec at engine-v9.9.9" in logged[-1]
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


def test_the_release_workflow_publishes_a_cut_release_from_main() -> None:
    declared = Zuke.release_workflow.manifest()
    assert declared["path"] == ".github/workflows/release.yml"
    pipeline = declared["pipeline"]
    assert isinstance(pipeline, dict)
    assert pipeline["triggers"] == {"push": ["main"]}
    invokes = declared["invokes"]
    assert is_list(invokes) and len(invokes) == 1
    (job,) = invokes
    assert is_record(job) and job["target"] == "publish"
    assert job["environment"] == "pypi"
    assert is_record(job["permissions"]) and job["permissions"]["id-token"] == "write"
    steps = job["steps"]
    assert is_list(steps) and len(steps) == 5
    first, *rest = steps
    assert is_record(first) and is_record(first["uses"])
    assert str(first["uses"]["version"]).startswith("v")
    assert [step["if"] for step in rest if is_record(step)] == [
        "steps.release.outputs.release_created"
    ] * 4
    assert is_record(rest[-2]) and rest[-2]["run"] == "./zuke publish"
    # The website sync runs after the upload, so a failed sync never holds it.
    assert is_record(rest[-1]) and rest[-1]["run"] == "./zuke sync_website"
    assert rest[-1]["env"] == {
        "ZUKE_BUILD_APP_ID": "${{ secrets.ZUKE_BUILD_APP_ID }}",
        "ZUKE_BUILD_APP_KEY": "${{ secrets.ZUKE_BUILD_APP_KEY }}",
    }


async def test_publish_builds_signs_the_distributions_then_uploads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    monkeypatch.setattr(build, "DIST", dist)
    dist.mkdir()
    (dist / "zuke-0.9.0.tar.gz").write_text("")  # left by an earlier build
    seen: list[list[str]] = []

    async def exec_(params: object) -> object:
        argv = field_strings(params, "argv", "exec")
        seen.append(argv)
        if argv == ["uv", "build"]:
            dist.mkdir()
            for name in ("zuke-1.0.0.tar.gz", "zuke-1.0.0-py3-none-any.whl", "x.txt"):
                (dist / name).write_text("")
        return {"code": 0, "stdout": "", "stderr": ""}

    peer: Peer
    async with served(Zuke()) as peer:
        peer.on("exec", exec_)
        await peer.request("build.configure", {"parameters": {}})
        params = {"target": "publish", "runId": "r1", "dryRun": False}
        assert await asyncio.wait_for(peer.request("target.run", params), 10) is None
    wheel = str(dist / "zuke-1.0.0-py3-none-any.whl")
    sdist = str(dist / "zuke-1.0.0.tar.gz")
    assert not (dist / "zuke-0.9.0.tar.gz").exists()
    assert seen == [
        ["uv", "build"],
        # Only this build's distributions are signed, by path, in a fixed order.
        [
            "uvx",
            "--from",
            build.ATTESTATIONS,
            "pypi-attestations",
            "sign",
            wheel,
            sdist,
        ],
        ["uv", "publish", "--trusted-publishing", "always"],
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


async def test_the_review_posts_as_the_app_when_its_credentials_are_set() -> None:
    calls: list[object] = []

    async def tool_call(params: object) -> object:
        calls.append(params)
        assert is_record(params)
        if params["package"] == "gh":
            return {"token": "ghs_app", "expiresAt": "", "installationId": 1}
        return None

    peer: Peer
    async with served(Zuke()) as peer:
        peer.on("tool.call", tool_call)
        configured = {"app_id": "42", "app_key": "PEM"}
        await peer.request("build.configure", {"parameters": configured})
        params = {"target": "review", "runId": "r1", "dryRun": False}
        assert await asyncio.wait_for(peer.request("target.run", params), 10) is None
    mint, review = calls
    assert is_record(mint) and (mint["package"], mint["task"]) == ("gh", "appToken")
    assert configure_calls(mint) == [
        ["appId", ["42"]],
        ["privateKey", ["PEM"]],
        ["owner", ["zuke-build"]],
        ["repositories", ["zuke-python"]],
        ["permission", ["pull_requests", "write"]],
        ["permission", ["issues", "write"]],
        ["permission", ["contents", "write"]],
    ]
    for reviewer in configure_calls(review):
        assert is_list(reviewer) and is_list(reviewer[1]) and is_record(reviewer[1][0])
        setters = reviewer[1][0]["configure"]
        assert is_list(setters) and ["commentToken", ["ghs_app"]] in setters


@pytest.mark.parametrize(
    "parameters", [{"app_id": "42"}, {"app_id": "", "app_key": ""}]
)
async def test_the_review_posts_with_the_actions_token_without_the_app(
    parameters: dict[str, str],
) -> None:
    calls: list[object] = []

    async def tool_call(params: object) -> object:
        calls.append(params)
        return None

    peer: Peer
    async with served(Zuke()) as peer:
        peer.on("tool.call", tool_call)
        # The id alone is not enough, and a Dependabot run's empty ones are unset.
        await peer.request("build.configure", {"parameters": parameters})
        params = {"target": "review", "runId": "r1", "dryRun": False}
        assert await asyncio.wait_for(peer.request("target.run", params), 10) is None
    [review] = calls
    assert is_record(review) and review["package"] == "ai"
    for reviewer in configure_calls(review):
        assert is_list(reviewer) and is_list(reviewer[1]) and is_record(reviewer[1][0])
        setters = reviewer[1][0]["configure"]
        assert is_list(setters)
        assert "commentToken" not in [call[0] for call in setters if is_list(call)]


async def run_target(
    name: str, handlers: dict[str, Handler], parameters: dict[str, object] | None = None
) -> None:
    """Run one target of the build against a fake engine serving ``handlers``."""
    peer: Peer
    async with served(Zuke()) as peer:
        for method, handler in handlers.items():
            peer.on(method, handler)
        await peer.request("build.configure", {"parameters": parameters or {}})
        params = {"target": name, "runId": "r1", "dryRun": False}
        assert await asyncio.wait_for(peer.request("target.run", params), 10) is None


async def test_api_reference_writes_the_reference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    written = tmp_path / ".zuke" / "api.json"
    monkeypatch.setattr(build, "REFERENCE", written)
    await run_target("api_reference", {"log": lambda _: asyncio.sleep(0)})
    reference = json.loads(written.read_text(encoding="utf-8"))
    assert reference["generated"] == f"zuke@{build.__version__}"
    assert reference["packages"][0]["name"] == "zuke"


async def test_sync_website_is_skipped_without_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WEBSITE_SYNC_TOKEN", raising=False)
    logged: list[object] = []
    calls: list[object] = []

    async def log(params: object) -> object:
        logged.append(params)
        return None

    async def tool_call(params: object) -> object:
        calls.append(params)
        return {}

    await run_target("sync_website", {"log": log, "tool.call": tool_call})
    assert calls == []
    assert "skipping the sync" in str(logged)


async def test_sync_website_mints_a_website_token_from_the_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WEBSITE_SYNC_TOKEN", raising=False)
    calls: list[dict[str, object]] = []
    secrets: list[object] = []

    async def tool_call(params: object) -> object:
        assert is_record(params)
        calls.append(params)
        if params["package"] == "gh":
            return {"token": "ghs_site", "expiresAt": "", "installationId": 1}
        # An empty status ends the sync before the push.
        return {"code": 0, "stdout": "", "stderr": ""}

    async def secret(params: object) -> object:
        secrets.append(params)
        return None

    await run_target(
        "sync_website",
        {
            "tool.call": tool_call,
            "secret.register": secret,
            "log": lambda _: asyncio.sleep(0),
        },
        {"app_id": "42", "app_key": "PEM"},
    )
    mint = calls[0]
    assert (mint["package"], mint["task"]) == ("gh", "appToken")
    assert configure_calls(mint) == [
        ["appId", ["42"]],
        ["privateKey", ["PEM"]],
        ["owner", ["zuke-build"]],
        ["repositories", ["zuke-build.github.io"]],
        ["permission", ["contents", "write"]],
        ["permission", ["pull_requests", "write"]],
    ]
    assert next(s["value"] for s in secrets if is_record(s)) == "ghs_site"


@pytest.mark.parametrize(
    ("status", "opened"),
    [("M src/data/api-python.json\n", 0), ("M src/data/api-python.json\n", 1), ("", 0)],
)
async def test_sync_website_pushes_opens_and_queues_the_merge(
    monkeypatch: pytest.MonkeyPatch, status: str, opened: int
) -> None:
    monkeypatch.setenv("WEBSITE_SYNC_TOKEN", "tok")
    calls: list[dict[str, object]] = []
    secrets: list[object] = []
    logged: list[object] = []
    written: list[bool] = []

    async def tool_call(params: object) -> object:
        assert is_record(params)
        calls.append(params)
        task = (params["package"], params["task"])
        if task == ("git", "add"):
            setters = configure_calls(params)
            assert is_list(setters[0]) and is_list(setters[0][1])
            into = Path(str(setters[0][1][0]))
            written.append((into / build.WEBSITE_API).is_file())
        if task == ("git", "status"):
            return {"code": 0, "stdout": status, "stderr": ""}
        if task == ("gh", "run"):
            return {"code": opened, "stdout": "https://github.com/pr/1\n", "stderr": ""}
        return {"code": 0, "stdout": "", "stderr": ""}

    async def secret(params: object) -> object:
        secrets.append(params)
        return None

    async def log(params: object) -> object:
        logged.append(params)
        return None

    await run_target(
        "sync_website", {"tool.call": tool_call, "secret.register": secret, "log": log}
    )
    tasks = [(c["package"], c["task"]) for c in calls]
    clone, checkout = calls[0], calls[1]
    version = build.__version__
    branch = f"zuke-python-sync/{version}"
    assert configure_calls(clone)[0] == [
        "repository",
        ["https://github.com/zuke-build/zuke-build.github.io.git"],
    ]
    assert configure_calls(checkout)[1:] == [["ref", [branch]], ["create", []]]
    assert written == [True]
    # The token is redacted once it is held, and the header it rides in before
    # the push it is made for; with nothing to push, no header is made.
    header = "AUTHORIZATION: basic eC1hY2Nlc3MtdG9rZW46dG9r"
    assert [s["value"] for s in secrets if is_record(s)] == (
        ["tok", header] if status else ["tok"]
    )
    if not status:
        assert tasks == [("git", t) for t in ("clone", "checkout", "add", "status")]
        assert "already has this reference" in str(logged)
        return
    assert tasks == [
        *[("git", t) for t in ("clone", "checkout", "add", "status", "commit", "run")],
        ("gh", "run"),
        ("gh", "run"),
    ]
    push, create, merge = calls[5], calls[6], calls[7]
    assert configure_calls(push)[1:] == [
        [
            "config",
            ["http.extraheader", "AUTHORIZATION: basic eC1hY2Nlc3MtdG9rZW46dG9r"],
        ],
        ["command", ["push", "--force", "origin", branch]],
    ]
    message = f"chore: sync the python api reference for zuke@{version}"
    assert configure_calls(create)[:5] == [
        ["command", ["pr", "create"]],
        ["repo", ["zuke-build/zuke-build.github.io"]],
        ["flag", ["head", branch]],
        ["flag", ["title", message]],
        ["flag", ["body", build.SYNC_BODY]],
    ]
    assert ["env", [{"GH_TOKEN": "tok"}]] in configure_calls(create)
    assert configure_calls(merge)[:4] == [
        ["command", ["pr", "merge", branch]],
        ["repo", ["zuke-build/zuke-build.github.io"]],
        ["flag", ["auto"]],
        ["flag", ["squash"]],
    ]
    assert ["noThrow", []] not in configure_calls(merge)
    expected = "https://github.com/pr/1" if opened == 0 else "was already open"
    assert expected in str(logged)


def test_newest_release_picks_the_highest_exact_tag_with_the_prefix() -> None:
    refs = (
        "a1\trefs/tags/cli-v2.9.0\n"
        "a2\trefs/tags/cli-v2.10.0\n"
        "a3\trefs/tags/cli-v2.10.0^{}\n"
        "a4\trefs/tags/cli-v3.0.0-rc.1\n"
        "a5\trefs/tags/engine-v9.0.0\n"
    )
    assert build.newest_release(refs, "cli-v") == "cli-v2.10.0"
    assert build.newest_release("", "cli-v") is None


def sync_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point everything the sync writes into ``tmp_path``, vendored at cli-v2.0.0."""
    tmp_path.mkdir(exist_ok=True)
    for name, path in {
        "SPEC": tmp_path / "spec",
        "CASES": tmp_path / "cases",
        "TOOLS": tmp_path / "tools",
    }.items():
        monkeypatch.setattr(build, name, path)
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "engine.json").write_text('{"tag": "cli-v2.0.0"}')
    (tmp_path / "cases").mkdir()
    (tmp_path / "cases" / "VERSION").write_text("cli-v2.0.0\n")


REFS = "a1\trefs/tags/cli-v2.0.0\na2\trefs/tags/cli-v2.1.0\n"
"""What ls-remote answers: one release newer than the vendored one."""


async def test_sync_engine_does_nothing_when_already_on_the_newest_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sync_paths(tmp_path, monkeypatch)
    calls: list[object] = []
    logged: list[object] = []

    async def tool_call(params: object) -> object:
        calls.append(params)
        return {"code": 0, "stdout": "a1\trefs/tags/cli-v2.0.0\n", "stderr": ""}

    async def log(params: object) -> object:
        logged.append(params)
        return None

    await run_target("sync_engine", {"tool.call": tool_call, "log": log})
    (ls_remote,) = calls
    assert is_record(ls_remote) and ls_remote["task"] == "lsRemote"
    assert configure_calls(ls_remote)[:3] == [
        ["remote", ["https://github.com/zuke-build/zuke.git"]],
        ["tags", []],
        ["patterns", ["cli-v*"]],
    ]
    assert "already in sync with cli-v2.0.0" in str(logged)


async def sync_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: str,
    open_pr: str = "",
    credentials: bool = True,
) -> tuple[list[dict[str, object]], list[object], list[list[str]]]:
    """Run ``sync_engine`` to a release newer than the vendored one.

    Answers what the sync asks: the tags, the checkout's files at the tag, the
    work tree's status, the App token and the open pull requests. Returns the
    ``tool.call`` params in order, the log lines, and the commands it ran.
    """
    sync_paths(tmp_path, monkeypatch)
    spec = (Path(__file__).parent / "fixtures" / "spec.json").read_text()
    shown = {
        "packages/engine/conformance/case.json": '{"case": 1}',
        "packages/engine/deno.json": '{"version": "1.4.0"}',
        "packages/engine/spec/tools.json": spec,
        "packages/widget/deno.json": '{"version": "0.1.0"}',
        "packages/tally/deno.json": '{"version": "0.2.0"}',
    }
    calls: list[dict[str, object]] = []
    logged: list[object] = []
    execs: list[list[str]] = []

    async def exec_(params: object) -> object:
        argv = field_strings(params, "argv", "exec")
        execs.append(argv)
        if argv[3:4] == ["ls-tree"]:
            return {"code": 0, "stdout": "case.json\n", "stderr": ""}
        if argv[3:4] == ["show"]:
            path = argv[4].split(":", 1)[1]
            return {"code": 0, "stdout": shown[path], "stderr": ""}
        return {"code": 0, "stdout": "", "stderr": ""}

    async def tool_call(params: object) -> object:
        assert is_record(params)
        calls.append(params)
        task = (params["package"], params["task"])
        if task == ("git", "lsRemote"):
            return {"code": 0, "stdout": REFS, "stderr": ""}
        if task == ("git", "status"):
            return {"code": 0, "stdout": status, "stderr": ""}
        if task == ("gh", "appToken"):
            return {"token": "ghs_sync", "expiresAt": "", "installationId": 1}
        if task == ("gh", "run"):
            command = configure_calls(params)[0]
            assert is_list(command) and is_list(command[1])
            answers = {
                "list": open_pr,
                "create": "https://github.com/zuke-build/zuke-python/issues/9\n",
            }
            return {
                "code": 0,
                "stdout": answers.get(str(command[1][1]), ""),
                "stderr": "",
            }
        return {"code": 0, "stdout": "", "stderr": ""}

    async def log(params: object) -> object:
        logged.append(params)
        return None

    await run_target(
        "sync_engine",
        {
            "exec": exec_,
            "tool.call": tool_call,
            "log": log,
            "secret.register": lambda _: asyncio.sleep(0),
        },
        {"app_id": "42", "app_key": "PEM"} if credentials else {},
    )
    return calls, logged, execs


def gh_commands(calls: list[dict[str, object]]) -> list[list[object]]:
    """The ``gh`` subcommands the sync ran, each with its flags."""
    out: list[list[object]] = []
    for call in calls:
        if (call["package"], call["task"]) == ("gh", "run"):
            out.append(configure_calls(call))
    return out


async def test_sync_engine_vendors_the_release_and_opens_an_issue_and_its_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, _, execs = await sync_run(
        tmp_path, monkeypatch, status=" M spec/engine.json\n?? src/zuke/tools/x.py\n"
    )
    # The checkout is the release tag, shallow.
    clone = next(c for c in calls if c["task"] == "clone")
    setters = configure_calls(clone)
    assert ["branch", ["cli-v2.1.0"]] in setters and ["depth", [1]] in setters
    # Everything is vendored at that tag, and the launchers and the engine pin
    # moved to that release by the zuke command that writes them.
    assert (tmp_path / "cases" / "VERSION").read_text() == "cli-v2.1.0\n"
    assert (tmp_path / "cases" / "case.json").read_text() == '{"case": 1}'
    assert json.loads((tmp_path / "spec" / "engine.json").read_text())["tag"] == (
        "cli-v2.1.0"
    )
    launcher = str(Path(build.__file__).parent / "zuke")
    assert [launcher, "upgrade", "--engine", "2.1.0"] in execs
    assert (tmp_path / "tools" / "widget.py").is_file()
    # The branch is created, never forced over local changes.
    checkout = next(c for c in calls if c["task"] == "checkout")
    assert configure_calls(checkout)[1:] == [["ref", ["sync/engine"]], ["create", []]]
    issue, pr = gh_commands(calls)[1:]
    assert issue[0] == ["command", ["issue", "create"]]
    assert ["flag", ["title", build.SYNC_ISSUE]] in issue
    assert pr[0] == ["command", ["pr", "create"]]
    # New facades are new API: a minor release, closing the issue just opened.
    assert ["flag", ["title", "feat: sync with the engine at cli-v2.1.0"]] in pr
    body = next(
        f[1][1] for f in pr if is_list(f) and is_list(f[1]) and f[1][0] == "body"
    )
    assert str(body).endswith(
        "Closes https://github.com/zuke-build/zuke-python/issues/9"
    )


async def test_sync_engine_updates_the_open_pr_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, logged, _ = await sync_run(
        tmp_path, monkeypatch, status=" M zuke.json\n", open_pr="7\n"
    )
    listed, edited = gh_commands(calls)
    assert listed[0] == ["command", ["pr", "list"]]
    assert edited[0] == ["command", ["pr", "edit", "7"]]
    # Only versions moved: a patch release.
    assert ["flag", ["title", "fix: sync with the engine at cli-v2.1.0"]] in edited
    assert "updated pull request #7 to cli-v2.1.0" in str(logged)


async def test_sync_engine_never_takes_the_spec_backwards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A spec vendored at a newer engine tag than the newest CLI release
    # carries: the sync waits, rather than lose what the newer spec gave.
    sync_paths(tmp_path, monkeypatch)
    (tmp_path / "spec" / "engine.json").write_text('{"tag": "engine-v1.5.0"}')
    monkeypatch.setattr(build, "SPEC", tmp_path / "spec")
    calls: list[dict[str, object]] = []
    logged: list[object] = []

    async def exec_(params: object) -> object:
        return {"code": 0, "stdout": '{"version": "1.4.0"}', "stderr": ""}

    async def tool_call(params: object) -> object:
        assert is_record(params)
        calls.append(params)
        return {"code": 0, "stdout": REFS, "stderr": ""}

    async def log(params: object) -> object:
        logged.append(params)
        return None

    await run_target("sync_engine", {"exec": exec_, "tool.call": tool_call, "log": log})
    assert [c["task"] for c in calls] == ["lsRemote", "clone"]
    assert (tmp_path / "cases" / "VERSION").read_text() == "cli-v2.0.0\n"
    assert "older than the vendored 1.5.0: waiting for a newer CLI release" in str(
        logged
    )


def test_vendored_engine_reads_the_record_or_an_engine_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build, "SPEC", tmp_path)
    for text, engine in [
        ('{"tag": "cli-v2.3.0", "engine": "1.3.0"}', "1.3.0"),
        ('{"tag": "engine-v1.2.2"}', "1.2.2"),
        ('{"tag": "cli-v2.2.0"}', None),
    ]:
        (tmp_path / "engine.json").write_text(text)
        assert build.vendored_engine() == engine
    assert build.release_numbers("1.10.2") == (1, 10, 2)
    assert build.release_numbers("1.10") is None


async def test_sync_engine_proposes_nothing_without_changes_or_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, logged, _ = await sync_run(tmp_path, monkeypatch, status="")
    assert gh_commands(calls) == []
    assert "cli-v2.1.0 changes nothing vendored here" in str(logged)
    calls, logged, _ = await sync_run(
        tmp_path / "again",
        monkeypatch,
        status=" M zuke.json\n",
        credentials=False,
    )
    assert gh_commands(calls) == []
    assert all(c["task"] != "push" for c in calls)
    assert "no App credentials, so no pull request" in str(logged)
