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
}
"""The pinned actions the workflow uses: the Zuke prelude, and what it is made of."""
RUNNERS = ["ubuntu-latest", "macos-latest", "windows-latest"]


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
            (CASES / name).write_text(shown.stdout)
    (CASES / "VERSION").write_text(f"{tag}\n")
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
    (SPEC / "tools.json").write_text(spec)
    engine = {"tag": tag, "versions": versions}
    (SPEC / "engine.json").write_text(json.dumps(engine, indent=2) + "\n")
    await ctx.log(f"vendored the tool spec at {tag}")


def generated() -> dict[str, str]:
    """The facades the vendored spec generates, by file name."""
    engine = record(json.loads((SPEC / "engine.json").read_text()), "engine.json")
    versions = record(engine.get("versions"), "engine.json versions")
    pinned = {name: string(versions, name, "versions") for name in versions}
    return generate(json.loads((SPEC / "tools.json").read_text()), pinned)


async def write_facades(ctx: Context, into: Path) -> None:
    """Write the generated facades into ``into``, formatted as the gate expects."""
    into.mkdir(parents=True, exist_ok=True)
    for stale in into.glob("*.py"):
        stale.unlink()
    for name, text in generated().items():
        (into / name).write_text(text)
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
            or (fresh / name).read_text() != (TOOLS / name).read_text()
        )
    finally:
        shutil.rmtree(fresh)
    if stale:
        raise ValueError(
            f"zuke.tools is out of date: {', '.join(stale)}; run ./zuke facades"
        )
    await ctx.log("zuke.tools matches the vendored spec")


class Zuke(Build):
    """The gate this repository runs, hosted on the engine it is an SDK for."""

    engine_repo = parameter("a checkout of zuke-build/zuke to vendor from").flag(
        "engine-repo"
    )
    engine_tag = parameter("the engine tag to vendor at, such as engine-v1.1.1").flag(
        "engine-tag"
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
                    {"name": "Install uv", "run": "pipx install uv", "shell": "bash"},
                    {
                        "name": "Sync the locked environment",
                        "run": "uv sync --locked",
                        "shell": "bash",
                    },
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
