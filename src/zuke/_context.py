# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The contexts a body and a service phase are handed, every call served by the engine.

A body never spawns a process or touches the run's state itself. Each method
here is a request the engine serves inside the caller's own scope, so its
dry-run echo, redaction and cancellation apply, and each is named as the
engine's protocol names it. A service phase gets the smaller context, since
the engine serves it no body-only call. The engine's answers are untrusted
and narrowed field by field.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from zuke._guard import boolean, integer, record, string, string_or_none, strings
from zuke._rpc import CANCELLED, Peer, RpcError


@dataclass(frozen=True)
class ExecResult:
    """What a command the engine ran for the body came back with."""

    code: int
    """The exit code."""
    stdout: str
    """What it printed to stdout."""
    stderr: str
    """What it printed to stderr."""


class CommandError(Exception):
    """A command :meth:`ServiceContext.sh` ran exited with a code other than zero."""

    def __init__(self, argv: tuple[str, ...], result: ExecResult) -> None:
        """Name the command and its code."""
        super().__init__(f"`{' '.join(argv)}` exited with code {result.code}")
        self.argv = argv
        """The command, as discrete arguments."""
        self.result = result
        """Its exit code and output."""


@dataclass(frozen=True)
class Outcome:
    """What another target in this run did, as :meth:`Context.outcome_of` tells."""

    status: str
    """The record's status: ``succeeded``, ``failed``, ``skipped``, ``waiting``, …"""
    error: str | None
    """The failure's message, when it failed."""
    started_at: str | None
    """When it started, ISO-8601, if it did."""
    ended_at: str | None
    """When it settled, ISO-8601, if it has."""


@dataclass(frozen=True)
class Plan:
    """The run's plan, as :meth:`Context.plan` reports it."""

    targets: list[str]
    """The planned targets, in order."""
    dependencies: dict[str, list[str]]
    """Each planned target's dependencies."""


class StateHandle:
    """Durable state of one target, kept by the engine across runs and resumes."""

    def __init__(self, ctx: Context, of: str | None) -> None:
        """State of ``of``, or of the body's own target when ``None``."""
        self._ctx = ctx
        self._of = {} if of is None else {"of": of}

    async def get(self) -> dict[str, object]:
        """The state as last written."""
        return record(
            await self._ctx.call_("state.get", **self._of), "state.get: the answer"
        )

    async def set(self, patch: Mapping[str, object]) -> None:
        """Merge ``patch`` into the state."""
        await self._ctx.call_("state.set", patch=dict(patch), **self._of)

    async def try_set(self, patch: Mapping[str, object]) -> bool:
        """Merge ``patch`` if the engine will record it now; whether it did."""
        answer = await self._ctx.call_("state.trySet", patch=dict(patch), **self._of)
        return boolean(answer, "recorded", "state.trySet")


class ServiceContext:
    """What a service phase is handed: the engine's services a phase may use."""

    def __init__(self, engine: Peer, target: str) -> None:
        """A context for a phase of ``target``."""
        self._engine = engine
        self.target = target
        """The target whose phase or body this is."""

    async def call_(self, method: str, **params: object) -> object:
        """Ask the engine as this target; an engine-side cancel unwinds the caller."""
        try:
            return await self._engine.request(method, {"target": self.target, **params})
        except RpcError as error:
            if error.code == CANCELLED:
                raise asyncio.CancelledError(str(error)) from None
            raise

    async def sh(
        self,
        *argv: str,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        check: bool = True,
    ) -> ExecResult:
        """Run ``argv`` through the engine, in the worker's directory and environment.

        ``cwd`` and ``env`` adjust those for this command; ``stdin`` is fed to it.
        Raises :class:`CommandError` on a non-zero code unless ``check`` is off.
        """
        params: dict[str, object] = {"argv": list(argv)}
        if cwd is not None:
            params["cwd"] = cwd
        if env is not None:
            params["env"] = dict(env)
        if stdin is not None:
            params["stdin"] = stdin
        answer = await self.call_("exec", **params)
        result = ExecResult(
            code=integer(answer, "code", "exec"),
            stdout=string(answer, "stdout", "exec"),
            stderr=string(answer, "stderr", "exec"),
        )
        if check and result.code != 0:
            raise CommandError(argv, result)
        return result

    async def secret(self, value: str) -> None:
        """Redact ``value`` from everything the run prints or records from now on."""
        await self.call_("secret.register", value=value)

    async def log(self, line: str) -> None:
        """Log a line attributed to this target."""
        await self.call_("log", line=line)


class Context(ServiceContext):
    """What a body is handed: the run it is part of, and all the engine serves it."""

    def __init__(self, engine: Peer, target: str, run_id: str, dry_run: bool) -> None:
        """A context for ``target``'s body in the run ``run_id``."""
        super().__init__(engine, target)
        self.run_id = run_id
        """The run's id, as the run record and ``zuke resume`` name it."""
        self.dry_run = dry_run
        """Whether the run is a ``--dry-run``."""

    @property
    def state(self) -> StateHandle:
        """This target's durable state."""
        return StateHandle(self, None)

    def state_of(self, target: str) -> StateHandle:
        """Another target's durable state."""
        return StateHandle(self, target)

    async def outcome_of(self, target: str) -> Outcome | None:
        """What ``target`` did in this run, or ``None`` if it has not run."""
        answer = await self.call_("outcome.of", of=target)
        return None if answer is None else _outcome(answer, "outcome.of")

    async def outcomes(self) -> dict[str, Outcome]:
        """What every settled target did in this run, by name."""
        answer = record(await self.call_("outcomes"), "outcomes: the answer")
        return {
            name: _outcome(view, f"outcomes: {name}") for name, view in answer.items()
        }

    async def summary(self, pairs: Mapping[str, str | float]) -> None:
        """Report notes into this target's row of the build summary."""
        await self.call_("summary.report", pairs=dict(pairs))

    async def plan(self) -> Plan:
        """The run's plan: the planned targets and each one's dependencies."""
        answer = record(await self.call_("plan"), "plan: the answer")
        dependencies = record(answer.get("dependencies"), 'plan: "dependencies"')
        return Plan(
            targets=strings(answer, "targets", "plan"),
            dependencies={
                name: strings(dependencies, name, "plan") for name in dependencies
            },
        )

    async def signals(self) -> dict[str, object]:
        """The external signals this run has received, by name."""
        return record(await self.call_("signals"), "signals: the answer")


def _outcome(value: object, what: str) -> Outcome:
    return Outcome(
        status=string(value, "status", what),
        error=string_or_none(value, "error", what),
        started_at=string_or_none(value, "startedAt", what),
        ended_at=string_or_none(value, "endedAt", what),
    )
