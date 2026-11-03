# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""This repository's own build: the gate, the case vendoring, the CI workflow.

Run it through the engine: ``./zuke ci`` is the gate, ``./zuke --list`` the
targets, and ``./zuke generate-ci`` writes the workflow declared below. The
engine starts this file as its worker, so every command here runs in the
engine with the worker's environment, which is the ``uv`` one.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from zuke import (
    Build,
    Context,
    StringParameter,
    invoke,
    parameter,
    run,
    target,
)
from zuke import (
    ci as cicd,
)
from zuke._generate import generate
from zuke._guard import is_list, record, string
from zuke.tools.ai import AiTasks, Reviewer, ReviewSettings
from zuke.tools.git import GitTasks

UV = ("uv", "run")
CASES = Path(__file__).parent / "tests" / "protocol" / "cases"
"""Where the engine's conformance cases are vendored."""
CONFORMANCE = "packages/engine/conformance"
"""The cases' directory in the engine repository."""
SPEC = Path(__file__).parent / "spec"
"""Where the engine's tool spec is vendored, with the tag and the wrappers' versions."""
TOOL_SPEC = "packages/engine/spec/tools.json"
"""The spec's path in the engine repository."""
TOOLS = Path(__file__).parent / "src" / "zuke" / "tools"
"""Where the facades the spec generates are committed."""
DIST = Path(__file__).parent / "dist"
"""Where uv build writes the sdist and the wheel, and their attestations go."""
ATTESTATIONS = "pypi-attestations==0.0.31"
"""The PyPA tool that signs a distribution's PEP 740 provenance, pinned."""
PINS = {
    "zuke-build/zuke": {
        "ref": "zuke-build/zuke@b0832247daa16321be405a10b71c022317d2c5a4",
        "version": "v1.0.8",
    },
    "step-security/harden-runner": {
        "ref": "step-security/harden-runner@46b06cea07f9e64621fdf066ba77ac6915163d43",
        "version": "v2.22.3",
    },
    "actions/checkout": {
        "ref": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "version": "v7.0.1",
    },
    "googleapis/release-please-action": {
        "ref": "googleapis/release-please-action"
        "@5c625bfb5d1ff62eadeeb3772007f7f66fdcf071",
        "version": "v4.4.1",
    },
}
"""The pinned actions the workflow uses: the Zuke prelude, and what it is made of."""
RUNNERS = ["ubuntu-latest", "macos-latest", "windows-latest"]
UV_STEPS = [
    {"name": "Install uv", "run": "pipx install uv", "shell": "bash"},
    {"name": "Sync the locked environment", "run": "uv sync --locked", "shell": "bash"},
]
"""The steps every job runs before a launcher: the environment the worker needs."""
ENDPOINTS = [
    "deno.land:443",
    "dl.deno.land:443",
    "jsr.io:443",
    "github.com:443",
    "api.github.com:443",
    "codeload.github.com:443",
    "objects.githubusercontent.com:443",
    "release-assets.githubusercontent.com:443",
    "pypi.org:443",
    "files.pythonhosted.org:443",
    "api.openai.com:443",
]
"""What a job holding the review's key may reach: the bootstrap, uv, GitHub, OpenAI."""
REVIEW_BASE = os.environ.get("ZUKE_REVIEW_BASE", "origin/main")
"""What the reviewers diff against; a commanded run reviews the pull request instead."""
REVIEW_CRITERIA = (
    "This is a strict, dependency-free Python SDK on 3.12, checked by pyright in "
    "strict mode: no `Any`, no `cast`, no `# type: ignore` in `src/`, every "
    "function annotated, and protocol input narrowed through the guards in "
    "`_guard.py` rather than trusted. The public API is task-shaped: the "
    "facades under `zuke.tools` and the context, never loose helpers. Flag "
    "duplicated logic: a helper retyped instead of imported, or a near-copy "
    "differing only by a constant or a message. The modules under "
    "`src/zuke/tools/` are generated from the engine's tool spec and never "
    "edited by hand, so a finding there belongs in the generator or the engine."
)
"""The project-specific notes the code-quality reviewer judges by, on its rubric."""
REVIEW_SECRETS = {
    "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
    "GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}",
}
"""What a review step holds: the provider's key and the token the comments post with."""
COMMAND_ENV = {
    "GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}",
    "ZUKE_REVIEW_PR": "${{ github.event.issue.number }}",
    "ZUKE_REVIEW_COMMENT": "${{ github.event.comment.id }}",
    "ZUKE_REVIEW_ACTOR": "${{ github.event.comment.user.login }}",
    "ZUKE_REVIEW_ROLE": "write",
}
"""What a commanded run tells the reviewers: the pull request and the comment."""


def required(p: StringParameter) -> str:
    """A parameter's value the target requires: unset is an error naming its flag."""
    value = p.value
    if value is None:
        raise ValueError(f"--{p.manifest()['flag']} is required")
    return value


async def vendor(ctx: Context) -> None:
    """Replace the vendored cases with the engine repository's at the given tag."""
    repo, tag = required(Zuke.engine_repo), required(Zuke.engine_tag)
    tree = f"{tag}:{CONFORMANCE}"
    listing = await ctx.sh("git", "-C", repo, "ls-tree", "--name-only", tree)
    for stale in CASES.glob("*.json"):
        stale.unlink()
    for name in listing.stdout.split():
        if name.endswith(".json"):
            shown = await ctx.sh("git", "-C", repo, "show", f"{tree}/{name}")
            (CASES / name).write_text(shown.stdout, encoding="utf-8")
    (CASES / "VERSION").write_text(f"{tag}\n", encoding="utf-8")
    await ctx.log(f"vendored the conformance cases at {tag}")


async def shown(ctx: Context, repo: str, ref: str, path: str) -> str:
    """The text of ``path`` in ``repo`` at ``ref``."""
    return (await ctx.sh("git", "-C", repo, "show", f"{ref}:{path}")).stdout


async def vendor_spec(ctx: Context) -> None:
    """Replace the vendored tool spec, and the wrappers' versions, with the tag's."""
    repo, tag = required(Zuke.engine_repo), required(Zuke.engine_tag)
    spec = await shown(ctx, repo, tag, TOOL_SPEC)
    packages = record(json.loads(spec), "spec").get("packages")
    versions: dict[str, str] = {}
    for entry in packages if is_list(packages) else []:
        name = string(entry, "name", "package")
        deno = json.loads(await shown(ctx, repo, tag, f"packages/{name}/deno.json"))
        versions[name] = string(deno, "version", name)
    SPEC.mkdir(exist_ok=True)
    (SPEC / "tools.json").write_text(spec, encoding="utf-8")
    engine = {"tag": tag, "versions": versions}
    (SPEC / "engine.json").write_text(
        json.dumps(engine, indent=2) + "\n", encoding="utf-8"
    )
    await ctx.log(f"vendored the tool spec at {tag}")


def generated() -> dict[str, str]:
    """The facades the vendored spec generates, by file name."""
    engine = record(
        json.loads((SPEC / "engine.json").read_text(encoding="utf-8")), "engine.json"
    )
    versions = record(engine.get("versions"), "engine.json versions")
    pinned = {name: string(versions, name, "versions") for name in versions}
    return generate(
        json.loads((SPEC / "tools.json").read_text(encoding="utf-8")), pinned
    )


async def write_facades(ctx: Context, into: Path) -> None:
    """Write the generated facades into ``into``, formatted as the gate expects."""
    into.mkdir(parents=True, exist_ok=True)
    for stale in into.glob("*.py"):
        stale.unlink()
    for name, text in generated().items():
        (into / name).write_text(text, encoding="utf-8")
    config = Path(__file__).parent / "pyproject.toml"
    await ctx.sh(*UV, "ruff", "format", "--quiet", "--config", str(config), str(into))


async def facades(ctx: Context) -> None:
    """Regenerate ``zuke.tools`` from the vendored spec."""
    await write_facades(ctx, TOOLS)
    await ctx.log(f"wrote {len(generated())} module(s) under {TOOLS}")


async def facades_check(ctx: Context) -> None:
    """Fail when ``zuke.tools`` differs from what the vendored spec generates."""
    fresh = Path(tempfile.mkdtemp(prefix="zuke-facades-"))
    try:
        await write_facades(ctx, fresh)
        names = {p.name for p in fresh.glob("*.py")} | {
            p.name for p in TOOLS.glob("*.py")
        }
        stale = sorted(
            name
            for name in names
            if not (fresh / name).exists()
            or not (TOOLS / name).exists()
            or (fresh / name).read_text(encoding="utf-8")
            != (TOOLS / name).read_text(encoding="utf-8")
        )
    finally:
        shutil.rmtree(fresh)
    if stale:
        raise ValueError(
            f"zuke.tools is out of date: {', '.join(stale)}; run ./zuke facades"
        )
    await ctx.log("zuke.tools matches the vendored spec")


def reviewer(s: Reviewer) -> Reviewer:
    """What both reviewers share: the provider, the diff, the depth, the discussion.

    The key is the ``openai_key`` parameter when it is set; without it the
    review is skipped and says so, as on a local run. Comments are appended,
    so earlier assessments and their finding ids stay on the thread, and a
    maintainer contests a finding by replying with its id quoted.
    """
    key = Zuke.openai_key.value
    s = s.provider("openai").skip_if_key_missing()
    if key is not None:
        s = s.api_key(key)
    return (
        s.comment("append")
        .diff(lambda d: d.base(REVIEW_BASE))
        .max_diff_tokens(20000)
        .conventions_file("AGENTS.md")
        .verify()
        .discussion(lambda d: d.threads().commands("@zuke-build"))
        .fail_when(lambda g: g.score_above(5))
        .on_error("warn")
    )


def reviewers(r: ReviewSettings) -> ReviewSettings:
    """The two reviewers this repository's pull requests get: security, then quality."""
    return r.security(lambda s: reviewer(s).file_context()).generic(
        lambda s: reviewer(s).criteria(REVIEW_CRITERIA)
    )


async def publish(ctx: Context) -> None:
    """Build the sdist and the wheel, sign their provenance, and upload them.

    The signing takes the job's OIDC identity, the same one trusted publishing
    presents to PyPI, and writes a PEP 740 attestation beside each file, which
    uv publish uploads along with it: the Security tab on PyPI then verifies
    the files back to this workflow.
    """
    await ctx.sh("uv", "build")
    files = sorted(str(p) for p in DIST.iterdir() if p.suffix in {".whl", ".gz"})
    await ctx.sh("uvx", "--from", ATTESTATIONS, "pypi-attestations", "sign", *files)
    await ctx.sh("uv", "publish", "--trusted-publishing", "always")


async def fetch_review_base(ctx: Context) -> None:
    """Fetch the branch the reviewers diff against, which a shallow checkout lacks."""
    result = await GitTasks.fetch(
        ctx,
        lambda s: (
            s.remote("origin")
            .refspec("+main:refs/remotes/origin/main")
            .no_tags()
            .depth(1)
            .no_throw()
            .quiet()
        ),
    )
    await ctx.log(
        "fetched origin/main for the review diff"
        if result.code == 0
        else f"could not fetch origin/main, exit {result.code}; reviewing as is"
    )


class Zuke(Build):
    """The gate this repository runs, hosted on the engine it is an SDK for."""

    engine_repo = parameter("a checkout of zuke-build/zuke to vendor from").flag(
        "engine-repo"
    )
    engine_tag = parameter("the engine tag to vendor at, such as engine-v1.1.1").flag(
        "engine-tag"
    )
    openai_key = (
        parameter("the OpenAI API key the AI review runs with")
        .env("OPENAI_API_KEY")
        .secret()
    )

    fmt = (
        target()
        .description("Format with ruff")
        .executes(lambda ctx: ctx.sh(*UV, "ruff", "format", "."))
    )
    fmt_check = (
        target()
        .description("Check the formatting")
        .executes(lambda ctx: ctx.sh(*UV, "ruff", "format", "--check", "."))
    )
    lint = (
        target()
        .description("Lint with ruff")
        .executes(lambda ctx: ctx.sh(*UV, "ruff", "check", "."))
    )
    check = (
        target()
        .description("Type-check with pyright, strict")
        .executes(lambda ctx: ctx.sh(*UV, "pyright"))
    )
    test = (
        target()
        .description("Run the tests with coverage")
        .executes(lambda ctx: ctx.sh(*UV, "pytest"))
    )
    facades = (
        target()
        .description("Regenerate zuke.tools from the vendored tool spec")
        .executes(facades)
    )
    facades_check = (
        target()
        .description("Check zuke.tools matches the vendored tool spec")
        .executes(facades_check)
    )
    ci = (
        target()
        .description("The gate: formatting, lint, types, tests, the facades")
        .depends_on(fmt_check, lint, check, test, facades_check)
    )
    review_base = (
        target()
        .description("Fetch the base branch the AI review diffs against")
        .executes(fetch_review_base)
    )
    review = (
        target()
        .description("AI review of the diff: security and code quality")
        .depends_on(review_base)
        .executes(lambda ctx: AiTasks.review(ctx, reviewers))
    )
    review_preflight = (
        target()
        .description("Check the commenter may start a review")
        .executes(lambda ctx: AiTasks.preflight(ctx, reviewers))
    )
    publish = (
        target()
        .description("Build, sign and publish the distributions to PyPI")
        .executes(publish)
    )
    vendor_cases = (
        target()
        .description("Vendor the engine's conformance cases at a tag")
        .requires(engine_repo, engine_tag)
        .executes(vendor)
    )
    vendor_spec = (
        target()
        .description(
            "Vendor the engine's tool spec and the wrappers' versions at a tag"
        )
        .requires(engine_repo, engine_tag)
        .executes(vendor_spec)
    )

    ai_review = (
        cicd()
        .path(".github/workflows/ai-review.yml")
        .pipeline(
            {
                "name": "AI Review",
                "triggers": {"pullRequest": [], "issueComment": ["created"]},
                # One group per pull request, whichever event started the
                # run, so a push supersedes the review of the one before it.
                "concurrency": {
                    "group": "ai-review-${{ github.event.pull_request.number "
                    "|| github.event.issue.number }}",
                    "cancelInProgress": True,
                },
                "harden": {"egress": "block", "allowedEndpoints": ENDPOINTS},
            }
        )
        .invokes(
            {
                "target": review,
                "id": "review",
                "name": "AI review",
                "permissions": {"contents": "read", "pull-requests": "write"},
                "if": (
                    "${{ github.event_name == 'pull_request' && "
                    "github.event.pull_request.head.repo.full_name == "
                    "github.repository }}"
                ),
                "timeoutMinutes": 15,
                "steps": [
                    *UV_STEPS,
                    {
                        "name": "AI review with Zuke",
                        "run": "./zuke review",
                        "env": REVIEW_SECRETS,
                    },
                ],
            },
            {
                "target": review,
                "id": "commandReview",
                "name": "AI review on command",
                "permissions": {"contents": "read", "pull-requests": "write"},
                "if": (
                    "${{ github.event_name == 'issue_comment' && "
                    "github.event.issue.pull_request && "
                    "github.event.comment.user.type != 'Bot' && "
                    "(startsWith(github.event.comment.body, '@zuke-build review') || "
                    "startsWith(github.event.comment.body, '@zuke-build accept')) }}"
                ),
                "timeoutMinutes": 15,
                "steps": [
                    *UV_STEPS,
                    {
                        "name": "Check the commenter may start a review",
                        "id": "callers",
                        "run": "./zuke review_preflight",
                        "env": COMMAND_ENV,
                        "continueOnError": True,
                    },
                    {
                        "name": "AI review with Zuke",
                        "if": "steps.callers.outcome == 'success'",
                        "run": "./zuke review",
                        "env": {**REVIEW_SECRETS, **COMMAND_ENV},
                    },
                ],
            },
        )
        .pins(PINS)
    )

    release_workflow = (
        cicd()
        .path(".github/workflows/release.yml")
        .pipeline(
            {
                "name": "Release",
                "triggers": {"push": ["main"]},
                "concurrency": {
                    "group": "release-${{ github.ref }}",
                    "cancelInProgress": False,
                },
                "harden": {"egress": "audit"},
            }
        )
        .invokes(
            {
                "target": publish,
                "id": "release",
                "name": "Maintain the release PR, and publish a cut release",
                # The trusted publisher PyPI knows is this workflow under this
                # environment; the token is minted from the job's identity, and
                # so are the provenance attestations the upload step signs.
                "environment": "pypi",
                "permissions": {
                    "contents": "write",
                    "pull-requests": "write",
                    "id-token": "write",
                },
                "timeoutMinutes": 15,
                "steps": [
                    {
                        "name": "Maintain the release PR and cut the release",
                        "id": "release",
                        "uses": PINS["googleapis/release-please-action"],
                        "with": {
                            "config-file": ".release-please-config.json",
                            "manifest-file": ".release-please-manifest.json",
                        },
                    },
                    *[
                        {**step, "if": "steps.release.outputs.release_created"}
                        for step in UV_STEPS
                    ],
                    {
                        "name": "Publish to PyPI with Zuke",
                        "if": "steps.release.outputs.release_created",
                        "run": "./zuke publish",
                    },
                ],
            }
        )
        .pins(PINS)
    )

    ci_workflow = (
        cicd()
        .path(".github/workflows/ci.yml")
        .pipeline(
            {
                "name": "CI",
                "triggers": {"push": ["main"], "pullRequest": ["main"]},
                "concurrency": {
                    "group": "ci-${{ github.ref }}",
                    "cancelInProgress": True,
                },
                "harden": {"egress": "audit"},
            }
        )
        .invokes(
            invoke(
                ci,
                name="Gate (${{ matrix.os }})",
                matrix={"os": RUNNERS},
                failFast=False,
                timeoutMinutes=15,
                # The launchers are the point, so each OS runs its own rather
                # than the derived command, as the engine repository's matrix
                # job does.
                steps=[
                    *UV_STEPS,
                    {
                        "name": "Run the gate with the bash launcher",
                        "if": "runner.os != 'Windows'",
                        "run": "./zuke ci",
                    },
                    {
                        "name": "Run the gate with the PowerShell launcher",
                        "if": "runner.os == 'Windows'",
                        "shell": "pwsh",
                        "run": "./zuke.ps1 ci",
                    },
                    {
                        "name": "Check the generated workflow is current",
                        "if": "runner.os != 'Windows'",
                        "run": "./zuke generate-ci --check",
                    },
                ],
            )
        )
        .pins(PINS)
    )


run(Zuke)
