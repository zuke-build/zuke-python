# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""This repository's own build: the gate, the vendoring, the reference, the CI.

Run it through the engine: ``./zuke ci`` is the gate, ``./zuke --list`` the
targets, and ``./zuke generate-ci`` writes the workflow declared below. The
engine starts this file as its worker, so every command here runs in the
engine with the worker's environment, which is the ``uv`` one.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from zuke import (
    Build,
    Context,
    StringParameter,
    __version__,
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
from zuke._reference import reference
from zuke.tools.ai import AiTasks, Reviewer, ReviewSettings
from zuke.tools.gh import GhAppTokenSettings, GhTasks
from zuke.tools.git import GitTasks

UV = ("uv", "run")
PACKAGE = Path(__file__).parent / "src" / "zuke"
"""The package the API reference documents."""
REFERENCE = Path(__file__).parent / ".zuke" / "api.json"
"""Where ``api_reference`` writes the reference; ``.gitignore`` keeps it out."""
WEBSITE_REPO = "zuke-build/zuke-build.github.io"
"""The website the reference is synced to on a release."""
WEBSITE_API = "src/data/api-python.json"
"""Where the website reads the Python reference from."""
SYNC_BODY = (
    "Automated sync from zuke-python: the refreshed Python API reference, "
    "`src/data/api-python.json`, generated from the released package's "
    "docstrings. Idempotent: regenerated on each release."
)
"""The body of every sync pull request; it never varies, so a rerun changes nothing."""
BOT = ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")
"""The identity a sync commit is made under, since a runner has none."""
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
ENGINE_REPO = "zuke-build/zuke"
"""The engine repository this SDK follows."""
SDK_REPO = "zuke-build/zuke-python"
"""This repository, where the engine sync opens its pull request."""
SYNC_BRANCH = "sync/engine"
"""The one branch the engine sync pushes, so its pull request is updated in place."""
SYNC_ISSUE = "chore: keep zuke-python in sync with the engine"
"""The title of the issue an engine sync pull request closes."""
DIST = Path(__file__).parent / "dist"
"""Where uv build writes the sdist and the wheel, and their attestations go."""
ATTESTATIONS = "pypi-attestations==0.0.31"
"""The PyPA tool that signs a distribution's PEP 740 provenance, pinned."""
PINS = {
    "zuke-build/zuke": {
        "ref": "zuke-build/zuke@517dc954200eae7c54125406675c329fa8cfb811",
        "version": "v1.0.9",
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
        "@45996ed1f6d02564a971a2fa1b5860e934307cf7",
        "version": "v5.0.0",
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
    "github.com:443",
    "api.github.com:443",
    "codeload.github.com:443",
    "objects.githubusercontent.com:443",
    "release-assets.githubusercontent.com:443",
    "pypi.org:443",
    "files.pythonhosted.org:443",
    "api.openai.com:443",
]
"""What a job holding the review's key may reach: zuke's release, uv, GitHub, OpenAI."""
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
    "ZUKE_BUILD_APP_ID": "${{ secrets.ZUKE_BUILD_APP_ID }}",
    "ZUKE_BUILD_APP_KEY": "${{ secrets.ZUKE_BUILD_APP_KEY }}",
}
"""What a review step holds: the provider's key, and the tokens to post with."""
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
    await vendor_cases_at(ctx, required(Zuke.engine_repo), required(Zuke.engine_tag))


async def vendor_cases_at(ctx: Context, repo: str, tag: str) -> None:
    """Replace the vendored cases with those of the checkout ``repo`` at ``tag``."""
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
    await vendor_spec_at(ctx, required(Zuke.engine_repo), required(Zuke.engine_tag))


async def vendor_spec_at(ctx: Context, repo: str, tag: str) -> None:
    """Vendor the tool spec and wrapper versions of ``repo`` at ``tag``."""
    spec = await shown(ctx, repo, tag, TOOL_SPEC)
    packages = record(json.loads(spec), "spec").get("packages")
    versions: dict[str, str] = {}
    for entry in packages if is_list(packages) else []:
        name = string(entry, "name", "package")
        deno = json.loads(await shown(ctx, repo, tag, f"packages/{name}/deno.json"))
        versions[name] = string(deno, "version", name)
    release = json.loads(await shown(ctx, repo, tag, "packages/engine/deno.json"))
    SPEC.mkdir(exist_ok=True)
    (SPEC / "tools.json").write_text(spec, encoding="utf-8")
    engine = {
        "tag": tag,
        "engine": string(release, "version", "engine"),
        "versions": versions,
    }
    (SPEC / "engine.json").write_text(
        json.dumps(engine, indent=2) + "\n", encoding="utf-8"
    )
    await ctx.log(f"vendored the tool spec at {tag}")


def pinned() -> dict[str, str]:
    """The wrapper releases the vendored spec names, by package."""
    engine = record(
        json.loads((SPEC / "engine.json").read_text(encoding="utf-8")), "engine.json"
    )
    versions = record(engine.get("versions"), "engine.json versions")
    return {name: string(versions, name, "versions") for name in versions}


def generated() -> dict[str, str]:
    """The facades the vendored spec generates, by file name."""
    return generate(
        json.loads((SPEC / "tools.json").read_text(encoding="utf-8")), pinned()
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


def reviewer(s: Reviewer, token: str | None) -> Reviewer:
    """What both reviewers share: the provider, the diff, the depth, the discussion.

    The key is the ``openai_key`` parameter when it is set; without it the
    review is skipped and says so, as on a local run. Comments are appended,
    so earlier assessments and their finding ids stay on the thread, and a
    maintainer contests a finding by replying with its id quoted. They post
    with ``token`` when there is one, and with ``GITHUB_TOKEN`` otherwise.
    """
    key = Zuke.openai_key.value
    s = s.provider("openai").skip_if_key_missing()
    if key is not None:
        s = s.api_key(key)
    if token is not None:
        s = s.comment_token(token)
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


def reviewers(r: ReviewSettings, token: str | None = None) -> ReviewSettings:
    """The two reviewers this repository's pull requests get: security, then quality."""
    return r.security(lambda s: reviewer(s, token).file_context()).generic(
        lambda s: reviewer(s, token).criteria(REVIEW_CRITERIA)
    )


async def app_token(ctx: Context, repository: str, *write: str) -> str | None:
    """A ``zuke-build`` App installation token, when its credentials are set.

    The token is narrowed to one ``zuke-build`` repository and write access to
    the ``write`` permissions. Without the credentials, or with empty ones as on
    a fork or a Dependabot run, there is none.
    """
    app, key = Zuke.app_id.value, Zuke.app_key.value
    if not app or not key:
        return None

    def scoped(s: GhAppTokenSettings) -> GhAppTokenSettings:
        s = s.app_id(app).private_key(key).owner("zuke-build").repositories(repository)
        for permission in write:
            s = s.permission(permission, "write")
        return s

    return string(await GhTasks.app_token(ctx, scoped), "token", "appToken")


async def review(ctx: Context) -> None:
    """Run both reviewers, posting as the App when it can.

    Posting as the App makes the assessments come from ``zuke-build[bot]``,
    the account a maintainer addresses, and lets the reviewer resolve the
    threads it answers: GitHub allows that to repository write access, which
    for an installation token is ``contents: write``, and refuses the Actions
    token. Without the App, the reviews post with ``GITHUB_TOKEN``.
    """
    token = await app_token(ctx, "zuke-python", "pull_requests", "issues", "contents")
    await AiTasks.review(ctx, lambda r: reviewers(r, token))


async def publish(ctx: Context) -> None:
    """Build the sdist and the wheel, sign their provenance, and upload them.

    The signing takes the job's OIDC identity, the same one trusted publishing
    presents to PyPI, and writes a PEP 740 attestation beside each file, which
    uv publish uploads along with it: the Security tab on PyPI then verifies
    the files back to this workflow.
    """
    # A fresh dist/, so what is signed and uploaded is exactly this build.
    shutil.rmtree(DIST, ignore_errors=True)
    await ctx.sh("uv", "build")
    files = sorted(str(p) for p in DIST.iterdir() if p.suffix in {".whl", ".gz"})
    await ctx.sh("uvx", "--from", ATTESTATIONS, "pypi-attestations", "sign", *files)
    await ctx.sh("uv", "publish", "--trusted-publishing", "always")


def write_reference(path: Path) -> None:
    """Write the package's API reference, in the website's ``api.json`` shape."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(reference(PACKAGE, __version__), indent=2, ensure_ascii=False)
    # LF everywhere, so the file a Windows run writes diffs to nothing.
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


async def api_reference(ctx: Context) -> None:
    """Write the reference to ``.zuke/api.json``, to look at before a release."""
    write_reference(REFERENCE)
    await ctx.log(f"wrote the API reference of zuke@{__version__} to {REFERENCE}")


async def push_branch(ctx: Context, token: str, clone: str, branch: str) -> None:
    """Force-push ``branch`` of the checkout ``clone`` to its origin with ``token``.

    The token rides as a one-off header rather than in the remote URL, so git
    never writes it to ``.git/config``. The caller registered the token as a
    secret when it got it; the header spelling is registered here.
    """
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    auth = f"AUTHORIZATION: basic {basic}"
    await ctx.secret(auth)
    await GitTasks.run(
        ctx,
        lambda s: (
            s.dir(clone)
            .config("http.extraheader", auth)
            .command("push", "--force", "origin", branch)
        ),
    )


async def sync_website(ctx: Context) -> None:
    """Open a website pull request with the refreshed reference, and queue its merge.

    The same flow as the engine repository's ``syncWebsite``: clone the
    website, write the reference where it reads it, push a branch per release,
    open the pull request and enable auto-merge, so the website's own build
    check decides whether it lands. ``GITHUB_TOKEN`` cannot push to another
    repository, so this mints a ``zuke-build`` App token scoped to the website
    with contents and pull-requests write, what the engine repository's sync
    requests; ``WEBSITE_SYNC_TOKEN``, when set, is used instead. With neither,
    as locally or on a fork, the sync is skipped.
    """
    token = os.environ.get("WEBSITE_SYNC_TOKEN") or await app_token(
        ctx, "zuke-build.github.io", "contents", "pull_requests"
    )
    if not token:
        await ctx.log("no App credentials or WEBSITE_SYNC_TOKEN: skipping the sync")
        return
    await ctx.secret(token)
    branch = f"zuke-python-sync/{__version__}"
    message = f"chore: sync the python api reference for zuke@{__version__}"
    gh_env = {"GH_TOKEN": token}
    with tempfile.TemporaryDirectory(prefix="zuke-python-sync-") as into:
        await GitTasks.clone(
            ctx,
            lambda s: (
                s.repository(f"https://github.com/{WEBSITE_REPO}.git")
                .directory(into)
                .depth(1)
            ),
        )
        await GitTasks.checkout(ctx, lambda s: s.dir(into).ref(branch).create())
        write_reference(Path(into, WEBSITE_API))
        await GitTasks.add(ctx, lambda s: s.dir(into).all())
        status = await GitTasks.status(ctx, lambda s: s.dir(into).porcelain().quiet())
        if not status.stdout.strip():
            await ctx.log("the website already has this reference")
            return
        await GitTasks.commit(
            ctx,
            lambda s: (
                s.dir(into)
                .config("user.name", BOT[0])
                .config("user.email", BOT[1])
                .message(message)
            ),
        )
        await push_branch(ctx, token, into, branch)
        # gh refuses a second PR for the same head; the push updated that one.
        opened = await GhTasks.run(
            ctx,
            lambda s: (
                s.command("pr", "create")
                .repo(WEBSITE_REPO)
                .flag("head", branch)
                .flag("title", message)
                .flag("body", SYNC_BODY)
                .cwd(into)
                .env(gh_env)
                .no_throw()
            ),
        )
        await ctx.log(
            opened.stdout.strip()
            if opened.code == 0
            else f"the sync PR for {branch} was already open; the push updated it"
        )
        # Auto-merge, so the website's required build check gates the landing;
        # failing to enable it fails the job, since nobody watches the website.
        await GhTasks.run(
            ctx,
            lambda s: (
                s.command("pr", "merge", branch)
                .repo(WEBSITE_REPO)
                .flag("auto")
                .flag("squash")
                .cwd(into)
                .env(gh_env)
            ),
        )


def newest_release(refs: str, prefix: str) -> str | None:
    """The newest ``<prefix><major>.<minor>.<patch>`` tag in ``git ls-remote`` output.

    A peeled ``^{}`` entry, a prerelease and any other tag are passed over.
    """
    best: tuple[tuple[int, int, int], str] | None = None
    for line in refs.splitlines():
        tag = line.rsplit("\t", 1)[-1].removeprefix("refs/tags/")
        match = re.fullmatch(rf"{re.escape(prefix)}(\d+)\.(\d+)\.(\d+)", tag)
        if match is None:
            continue
        version = (int(match[1]), int(match[2]), int(match[3]))
        if best is None or version > best[0]:
            best = (version, tag)
    return None if best is None else best[1]


def vendored_at() -> tuple[str, str]:
    """The tags the tool spec and the conformance cases were vendored at."""
    engine = record(
        json.loads((SPEC / "engine.json").read_text(encoding="utf-8")), "engine.json"
    )
    cases = (CASES / "VERSION").read_text(encoding="utf-8").strip()
    return string(engine, "tag", "engine.json"), cases


def release_numbers(version: str) -> tuple[int, int, int] | None:
    """An exact ``major.minor.patch`` release's numbers, or ``None``."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    return None if match is None else (int(match[1]), int(match[2]), int(match[3]))


def vendored_engine() -> str | None:
    """The engine release the vendored spec came from, as ``engine.json`` records it.

    A spec vendored before the release was recorded is known by an
    ``engine-v<version>`` tag; at any other tag, it is unknown.
    """
    engine = record(
        json.loads((SPEC / "engine.json").read_text(encoding="utf-8")), "engine.json"
    )
    recorded = engine.get("engine")
    if isinstance(recorded, str):
        return recorded
    tag = string(engine, "tag", "engine.json")
    return tag.removeprefix("engine-v") if tag.startswith("engine-v") else None


async def sync_engine(ctx: Context) -> None:
    """Vendor the engine's newest CLI release, and propose it as one pull request.

    The ``zuke`` binary carries the engine and every wrapper release of the
    commit its CLI release is tagged at, so that commit is what this SDK
    follows: its tool spec and wrapper versions, its conformance cases, and
    its engine as the pin, and its binary as the one the launchers run.
    Following an older tag would leave a fix out; following a newer commit
    would ask the binary for releases it lacks. With nothing new, nothing
    happens. Otherwise the facades are regenerated, ``zuke upgrade --engine``
    moves the launchers and the pin to that release and, with the
    ``zuke-build`` App's credentials, the change is
    pushed to one standing branch whose pull request is opened, or updated,
    with an issue for it to close. The gate on that pull request decides: a
    red protocol replay or facades check is the SDK work the release needs.
    A CLI release carrying an older engine than the vendored spec came from
    is passed over: following it would take the facades backwards.
    """
    url = f"https://github.com/{ENGINE_REPO}.git"
    refs = await GitTasks.ls_remote(
        ctx, lambda s: s.remote(url).tags().patterns("cli-v*").quiet()
    )
    tag = newest_release(refs.stdout, "cli-v")
    if tag is None:
        raise ValueError(f"{ENGINE_REPO} has no cli-v release tag")
    if vendored_at() == (tag, tag):
        await ctx.log(f"already in sync with {tag}")
        return
    with tempfile.TemporaryDirectory(prefix="zuke-engine-") as checkout:
        await GitTasks.clone(
            ctx,
            lambda s: s.repository(url).directory(checkout).branch(tag).depth(1),
        )
        release = string(
            json.loads(await shown(ctx, checkout, tag, "packages/engine/deno.json")),
            "version",
            "engine",
        )
        # Never backwards: a spec vendored at a newer engine tag than the
        # newest CLI release carries waits for a CLI release that catches up,
        # or the facades would lose what the newer spec gave them.
        have, carried = (
            release_numbers(vendored_engine() or ""),
            release_numbers(release),
        )
        if have is not None and carried is not None and carried < have:
            await ctx.log(
                f"{tag} carries @zuke/engine {release}, older than the vendored "
                f"{vendored_engine()}: waiting for a newer CLI release"
            )
            return
        await vendor_cases_at(ctx, checkout, tag)
        await vendor_spec_at(ctx, checkout, tag)
    # The launchers run that very release, so they and the engine pin in
    # zuke.json move together, through the zuke command that writes them.
    await ctx.sh(
        str(Path(__file__).parent / "zuke"),
        "upgrade",
        "--engine",
        tag.removeprefix("cli-v"),
    )
    await facades(ctx)
    await propose_sync(ctx, tag)


async def propose_sync(ctx: Context, tag: str) -> None:
    """Commit what the sync vendored to ``SYNC_BRANCH`` and open or update its PR."""
    root = str(Path(__file__).parent)
    status = await GitTasks.status(ctx, lambda s: s.dir(root).porcelain().quiet())
    changed = [line[3:] for line in status.stdout.splitlines() if line.strip()]
    if not changed:
        await ctx.log(f"{tag} changes nothing vendored here")
        return
    token = await app_token(ctx, "zuke-python", "contents", "pull_requests", "issues")
    if token is None:
        await ctx.log(f"vendored {tag}; no App credentials, so no pull request")
        return
    await ctx.secret(token)
    # New or changed facades are new API for the SDK's users: a minor release.
    kind = "feat" if any(p.startswith("src/zuke/tools/") for p in changed) else "fix"
    title = f"{kind}: sync with the engine at {tag}"
    gh_env = {"GH_TOKEN": token}
    await GitTasks.checkout(ctx, lambda s: s.dir(root).ref(SYNC_BRANCH).create())
    await GitTasks.add(ctx, lambda s: s.dir(root).all())
    await GitTasks.commit(
        ctx,
        lambda s: (
            s.dir(root)
            .config("user.name", BOT[0])
            .config("user.email", BOT[1])
            .message(title)
        ),
    )
    await push_branch(ctx, token, root, SYNC_BRANCH)
    open_prs = await GhTasks.run(
        ctx,
        lambda s: (
            s.command("pr", "list")
            .repo(SDK_REPO)
            .flag("head", SYNC_BRANCH)
            .flag("state", "open")
            .flag("json", "number")
            .flag("jq", ".[].number")
            .env(gh_env)
        ),
    )
    number = open_prs.stdout.strip()
    if number:
        await GhTasks.run(
            ctx,
            lambda s: (
                s.command("pr", "edit", number)
                .repo(SDK_REPO)
                .flag("title", title)
                .env(gh_env)
            ),
        )
        await ctx.log(f"updated pull request #{number} to {tag}")
        return
    issue = await GhTasks.run(
        ctx,
        lambda s: (
            s.command("issue", "create")
            .repo(SDK_REPO)
            .flag("title", SYNC_ISSUE)
            .flag("body", sync_issue_body(tag))
            .env(gh_env)
        ),
    )
    issue_url = issue.stdout.strip()
    opened = await GhTasks.run(
        ctx,
        lambda s: (
            s.command("pr", "create")
            .repo(SDK_REPO)
            .flag("head", SYNC_BRANCH)
            .flag("base", "main")
            .flag("title", title)
            .flag("body", sync_pr_body(tag, issue_url))
            .env(gh_env)
        ),
    )
    await ctx.log(f"opened {opened.stdout.strip()} for {tag}")


def sync_issue_body(tag: str) -> str:
    """The issue an engine sync's pull request closes."""
    return (
        f"The engine repository released `{tag}`, which this SDK does not "
        "follow yet: its tool spec and wrapper versions, its conformance cases "
        "and its engine release. The engine sync vendored them on the "
        f"`{SYNC_BRANCH}` branch; its pull request closes this issue once it "
        "is merged. A red gate there names the SDK work the release needs."
    )


def sync_pr_body(tag: str, issue_url: str) -> str:
    """The body of an engine sync's pull request, closing ``issue_url``."""
    return (
        f"Automated sync with `{ENGINE_REPO}` at `{tag}`, the commit the "
        "`zuke` binary of that release is compiled from: the tool spec and "
        "the wrapper versions under `spec/`, the conformance cases under "
        "`tests/protocol/cases/`, and the launchers and the engine pin in "
        "`zuke.json` moved to that release, with the facades regenerated. A "
        "red gate means the SDK needs "
        "work for this release: a failing protocol replay names a protocol "
        "change, a failing facades check a spec shape the generator does not "
        "handle yet. Later releases update this pull request in place.\n\n"
        f"Closes {issue_url}"
    )


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
    app_id = parameter(
        "the id of the zuke-build GitHub App the review and sync use"
    ).env("ZUKE_BUILD_APP_ID")
    app_key = (
        parameter("the private key, PEM, of the zuke-build GitHub App")
        .env("ZUKE_BUILD_APP_KEY")
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
        .executes(review)
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
    api_reference = (
        target()
        .description("Write the API reference the website renders to .zuke/api.json")
        .executes(api_reference)
    )
    sync_website = (
        target()
        .description("Open and merge a website PR with the refreshed API reference")
        .executes(sync_website)
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
    sync_engine = (
        target()
        .description(
            "Vendor the engine's newest CLI release and propose it as a pull request"
        )
        .executes(sync_engine)
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
                    {
                        "name": "Sync the API reference to the website with Zuke",
                        "if": "steps.release.outputs.release_created",
                        "run": "./zuke sync_website",
                        "env": {
                            "ZUKE_BUILD_APP_ID": "${{ secrets.ZUKE_BUILD_APP_ID }}",
                            "ZUKE_BUILD_APP_KEY": "${{ secrets.ZUKE_BUILD_APP_KEY }}",
                        },
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

    sync_workflow = (
        cicd()
        .path(".github/workflows/sync.yml")
        .pipeline(
            {
                "name": "Engine sync",
                # On dispatch only: the engine repository's release pipeline
                # starts it once a CLI release is published, and it can be run
                # by hand. The App token the target mints does the writes, so
                # the job's own token only reads.
                "triggers": {"manual": True},
                "concurrency": {"group": "engine-sync", "cancelInProgress": False},
                "harden": {"egress": "audit"},
            }
        )
        .invokes(
            invoke(
                sync_engine,
                name="Sync with the engine's newest release",
                timeoutMinutes=15,
                permissions={"contents": "read"},
                steps=[
                    *UV_STEPS,
                    {
                        "name": "Sync with Zuke",
                        "run": "./zuke sync_engine",
                        "env": {
                            "ZUKE_BUILD_APP_ID": "${{ secrets.ZUKE_BUILD_APP_ID }}",
                            "ZUKE_BUILD_APP_KEY": "${{ secrets.ZUKE_BUILD_APP_KEY }}",
                        },
                    },
                ],
            )
        )
        .pins(PINS)
    )


run(Zuke)
