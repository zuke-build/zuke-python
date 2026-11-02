# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""This repository's own build: the gate, the case vendoring, the CI workflow.

Run it through the engine: ``./zuke ci`` is the gate, ``./zuke --list`` the
targets, and ``./zuke generate-ci`` writes the workflow declared below. The
engine starts this file as its worker, so every command here runs in the
engine with the worker's environment, which is the ``uv`` one.
"""

from __future__ import annotations

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

UV = ("uv", "run")
CASES = Path(__file__).parent / "tests" / "protocol" / "cases"
"""Where the engine's conformance cases are vendored."""
CONFORMANCE = "packages/engine/conformance"
"""The cases' directory in the engine repository."""
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


class Zuke(Build):
    """The gate this repository runs, hosted on the engine it is an SDK for."""

    engine_repo = parameter(
        "a checkout of zuke-build/zuke to vendor the cases from"
    ).flag("engine-repo")
    engine_tag = parameter(
        "the engine tag to vendor the cases at, such as engine-v1.0.0"
    ).flag("engine-tag")

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
    ci = (
        target()
        .description("The gate: formatting, lint, types, tests")
        .depends_on(fmt_check, lint, check, test)
    )
    vendor_cases = (
        target()
        .description("Vendor the engine's conformance cases at a tag")
        .requires(engine_repo, engine_tag)
        .executes(vendor)
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
