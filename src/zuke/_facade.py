# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The runtime every generated tool facade shares: settings that record, and the call.

A facade's settings lambda never runs a wrapper's setter; it records the calls
it would make, and ``tool.call`` carries them to the engine as the list of
``[setter, [arguments]]`` pairs the engine replays on the wrapper's own
settings. :func:`call` is the one request, and :func:`exec_result` reads the
answer of a task that ran a command.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Self

from zuke._context import ExecResult, ServiceContext, exec_result_of
from zuke._settings import Configure


class Settings:
    """What every facade's settings class extends: a recorder of setter calls."""

    def __init__(self) -> None:
        """No call recorded yet."""
        self.calls_: list[list[object]] = []
        """The recorded calls, each a ``[setter, [arguments]]`` pair, in order."""

    def _record(self, name: str, *args: object) -> Self:
        """Record a call of ``name``; a trailing ``None`` is a parameter left unset."""
        arguments = list(args)
        while arguments and arguments[-1] is None:
            arguments.pop()
        self.calls_.append([name, arguments])
        return self

    def _switch[T: Settings](self, cls: type[T], name: str, *args: object) -> T:
        """Record a call of ``name`` answering a ``cls``, which carries every call."""
        switched = cls()
        switched.calls_ = list(self._record(name, *args).calls_)
        return switched


def configured[S: Settings](
    settings: S, configure: Configure[S] | None
) -> dict[str, object]:
    """A settings lambda as ``tool.call`` carries it: its calls on ``settings``."""
    if configure is not None:
        settings = configure(settings)
    return {"configure": settings.calls_}


async def call(
    ctx: ServiceContext,
    package: str,
    version: str,
    tasks: str,
    task: str,
    args: Sequence[object],
) -> object:
    """Run ``task`` of ``tasks`` of ``@zuke/<package>@<version>`` with ``args``.

    The engine imports the release and runs the task with the worker's
    environment and directory; a task that throws raises the engine's
    :class:`~zuke._rpc.RpcError` with its message.
    """
    return await ctx.call_(
        "tool.call",
        package=package,
        version=version,
        tasks=tasks,
        task=task,
        args=list(args),
    )


def exec_result(answer: object) -> ExecResult:
    """The command output a ``tool.call`` answered, each field guarded."""
    return exec_result_of(answer, "tool.call")
