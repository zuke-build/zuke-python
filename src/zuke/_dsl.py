# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The authoring surface: targets, parameters and groups as a build's fields.

Each builder is fluent, every setter returns the builder, and a hard
dependency is the sibling field itself, so the type checker sees it and a
forward reference is a ``NameError`` where it is written. The manifest the
engine reads is each builder's ``manifest()``: only what differs from the
engine's defaults is sent, so a bare target is just its name.

The ``name_`` field and ``manifest()`` are how :class:`~zuke.Build` reads a
field it discovered; a build author never touches them.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable
from typing import Literal, Self

from zuke._context import Context

Duration = str | int
"""A duration as the engine takes it: ``"5m"``, ``"250ms"`` or milliseconds."""

_DURATION = re.compile(r"^(\d+)(ms|s|m|h|d)$")
_UNIT_MS = {"ms": 1, "s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}


def _duration_ms(value: Duration, what: str) -> int:
    if isinstance(value, int):
        return value
    match = _DURATION.match(value)
    if match is None:
        raise ValueError(f'{what}: "{value}" is not a duration such as "5m" or "250ms"')
    return int(match.group(1)) * _UNIT_MS[match.group(2)]


Body = Callable[[Context], Awaitable[None] | None]
"""A target's body: sync or async, given the :class:`Context`."""


class Field:
    """A build field: named after the attribute it is assigned to."""

    def __init__(self) -> None:
        """Start unnamed; the build class names its fields when it is created."""
        self.name_: str | None = None
        """The field's name, once a build class has discovered it."""

    @property
    def name(self) -> str:
        """The field's name, which is its name on the command line too."""
        if self.name_ is None:
            raise RuntimeError(
                "a target, parameter or group is named by the Build it is a field of"
            )
        return self.name_


class Target(Field):
    """A unit of work the engine schedules. Start one with :func:`target`."""

    def __init__(self) -> None:
        """A bare target: no description, no dependencies, no body."""
        super().__init__()
        self.body_: Body | None = None
        """The body, or ``None`` for a target that only aggregates its dependencies."""
        self._description = ""
        self._depends_on: list[Target] = []
        self._unlisted = False
        self._inputs: list[str] = []
        self._outputs: list[str] = []
        self._produces: list[str] = []
        self._retry: tuple[int, int] | None = None
        self._timeout_ms: int | None = None
        self._before: list[Target | str] = []
        self._after: list[Target | str] = []
        self._triggers: list[Target | str] = []
        self._proceed_after_failure = False
        self._always = False
        self._dry_runnable = False
        self._requires: list[Parameter] = []
        self._on_cancel: Target | str | None = None
        self._on_failure: Target | str | None = None

    def description(self, text: str) -> Self:
        """The line ``--list`` shows for this target."""
        self._description = text
        return self

    def depends_on(self, *targets: Target) -> Self:
        """Targets that must succeed first; each is a sibling field declared above."""
        self._depends_on.extend(targets)
        return self

    def unlisted(self) -> Self:
        """Hide the target from ``--list`` and ``--help``."""
        self._unlisted = True
        return self

    def inputs(self, *paths: str) -> Self:
        """Paths whose contents key the cache."""
        self._inputs.extend(paths)
        return self

    def outputs(self, *paths: str) -> Self:
        """Paths that must exist for a cache hit."""
        self._outputs.extend(paths)
        return self

    def produces(self, *paths: str) -> Self:
        """Artifact paths this target produces."""
        self._produces.extend(paths)
        return self

    def retry(self, times: int, delay: Duration = 0) -> Self:
        """Run the body up to ``times`` more times after it fails, ``delay`` apart."""
        self._retry = (times, _duration_ms(delay, "retry"))
        return self

    def timeout(self, limit: Duration) -> Self:
        """Fail an attempt that runs longer than ``limit``."""
        self._timeout_ms = _duration_ms(limit, "timeout")
        return self

    def before(self, *targets: Target | str) -> Self:
        """Run before these when both are planned; a string names a later field."""
        self._before.extend(targets)
        return self

    def after(self, *targets: Target | str) -> Self:
        """Run after these when both are planned; a string names a later field."""
        self._after.extend(targets)
        return self

    def triggers(self, *targets: Target | str) -> Self:
        """Pull these in and run them after this one; a string names a later field."""
        self._triggers.extend(targets)
        return self

    def proceed_after_failure(self) -> Self:
        """Keep the build running after this target fails."""
        self._proceed_after_failure = True
        return self

    def always(self) -> Self:
        """Run even after the build has failed."""
        self._always = True
        return self

    def dry_runnable(self) -> Self:
        """Run the body under ``--dry-run`` too."""
        self._dry_runnable = True
        return self

    def requires(self, *parameters: Parameter) -> Self:
        """Parameters that must resolve before this target runs."""
        self._requires.extend(parameters)
        return self

    def on_cancel(self, compensation: Target | str) -> Self:
        """The target to run when the run is cancelled after this one succeeded."""
        self._on_cancel = compensation
        return self

    def on_failure(self, disposition: Target | str) -> Self:
        """On failure: a compensation target, ``"fail"`` or ``"cancel-run"``."""
        self._on_failure = disposition
        return self

    def executes(self, body: Body) -> Self:
        """The body, sync or async."""
        self.body_ = body
        return self

    def references(self) -> list[tuple[str, Target | str]]:
        """Every target this one names, and the setter that named it, for the build."""
        named: list[tuple[str, Target | str]] = [
            ("depends_on", t) for t in self._depends_on
        ]
        named += [("before", t) for t in self._before]
        named += [("after", t) for t in self._after]
        named += [("triggers", t) for t in self._triggers]
        if self._on_cancel is not None:
            named.append(("on_cancel", self._on_cancel))
        if self._on_failure is not None and self._on_failure not in (
            "fail",
            "cancel-run",
        ):
            named.append(("on_failure", self._on_failure))
        return named

    def parameters(self) -> list[Parameter]:
        """The parameters this target requires, for the build to check."""
        return list(self._requires)

    def manifest(self) -> dict[str, object]:
        """The target as the engine's manifest describes it."""
        m: dict[str, object] = {"name": self.name}
        if self._description:
            m["description"] = self._description
        if self._depends_on:
            m["dependsOn"] = [t.name for t in self._depends_on]
        for key, paths in (
            ("inputs", self._inputs),
            ("outputs", self._outputs),
            ("produces", self._produces),
        ):
            if paths:
                m[key] = list(paths)
        if self._retry is not None:
            m["retry"] = {"times": self._retry[0], "delayMs": self._retry[1]}
        for key, soft in (
            ("before", self._before),
            ("after", self._after),
            ("triggers", self._triggers),
        ):
            if soft:
                m[key] = [_name_of(t) for t in soft]
        for key, flag in (
            ("unlisted", self._unlisted),
            ("proceedAfterFailure", self._proceed_after_failure),
            ("always", self._always),
            ("dryRunnable", self._dry_runnable),
        ):
            if flag:
                m[key] = True
        if self._requires:
            m["requires"] = [p.name for p in self._requires]
        optional: tuple[tuple[str, object], ...] = (
            ("timeoutMs", self._timeout_ms),
            (
                "onCancel",
                None if self._on_cancel is None else _name_of(self._on_cancel),
            ),
            (
                "onFailure",
                None if self._on_failure is None else _name_of(self._on_failure),
            ),
        )
        m.update({key: value for key, value in optional if value is not None})
        return m

    async def run_body(self, ctx: Context) -> None:
        """Run the body, if any, awaiting it when it is async."""
        if self.body_ is None:
            return
        result = self.body_(ctx)
        if inspect.isawaitable(result):
            await result


def _name_of(reference: Target | str) -> str:
    return reference if isinstance(reference, str) else reference.name


Kind = Literal["string", "number", "boolean"]
"""A parameter's kind, as the manifest names it."""


class Parameter(Field):
    """What every parameter has, whatever its kind. Start one with :func:`parameter`."""

    def __init__(self, description: str, kind: Kind) -> None:
        """A parameter of ``kind`` with its ``--help`` description."""
        super().__init__()
        self._description = description
        self._kind: Kind = kind
        self._required = False
        self._secret = False
        self._flag: str | None = None
        self._env: str | None = None
        self._array = False
        self._options: list[str] = []
        self._default: str | float | bool | None = None
        self._resolved: str | None = None
        self._configured = False

    def required(self) -> Self:
        """A value must be supplied."""
        self._required = True
        return self

    def secret(self) -> Self:
        """Mask the value and redact it from everything the run prints or records."""
        self._secret = True
        return self

    def flag(self, name: str) -> Self:
        """The command-line flag, when it is not derived from the field name."""
        self._flag = name
        return self

    def env(self, name: str) -> Self:
        """The environment variable, when it is not derived from the field name."""
        self._env = name
        return self

    def _carry(self, other: Parameter) -> None:
        other._required = self._required
        other._secret = self._secret
        other._flag = self._flag
        other._env = self._env

    def resolve(self, value: str | None) -> None:
        """Take the value the engine resolved, in CLI form, or ``None`` when unset."""
        self._resolved = value
        self._configured = True

    def _raw(self) -> str | None:
        if not self._configured:
            raise RuntimeError(
                f'parameter "{self.name}" has no value before the engine configures it'
            )
        return self._resolved

    def manifest(self) -> dict[str, object]:
        """The parameter as the engine's manifest describes it."""
        m: dict[str, object] = {"name": self.name}
        if self._description:
            m["description"] = self._description
        if self._kind != "string":
            m["kind"] = self._kind
        if self._default is not None:
            m["default"] = self._default
        if self._options:
            m["options"] = list(self._options)
        if self._required:
            m["required"] = True
        if self._array:
            m["array"] = True
        if self._secret:
            m["secret"] = True
        if self._flag is not None:
            m["flag"] = self._flag
        if self._env is not None:
            m["env"] = self._env
        return m


def _number(text: str) -> float:
    try:
        return int(text)
    except ValueError:
        return float(text)


class StringParameter(Parameter):
    """A string parameter, the default kind."""

    def __init__(self, description: str) -> None:
        """A string parameter with its ``--help`` description."""
        super().__init__(description, "string")

    def default(self, value: str) -> Self:
        """The value when none is supplied."""
        self._default = value
        return self

    def options(self, *values: str) -> Self:
        """The only values accepted."""
        self._options.extend(values)
        return self

    def number(self) -> NumberParameter:
        """Make it a number parameter instead."""
        other = NumberParameter(self._description)
        self._carry(other)
        return other

    def boolean(self) -> BooleanParameter:
        """Make it a boolean parameter instead: a flag that takes no value."""
        other = BooleanParameter(self._description)
        self._carry(other)
        return other

    def array(self) -> StringListParameter:
        """Make it a list instead: a comma-separated value."""
        other = StringListParameter(self._description)
        self._carry(other)
        return other

    @property
    def value(self) -> str | None:
        """The resolved value, or ``None`` when unset."""
        return self._raw()


class NumberParameter(Parameter):
    """A number parameter."""

    def __init__(self, description: str) -> None:
        """A number parameter with its ``--help`` description."""
        super().__init__(description, "number")

    def default(self, value: float) -> Self:
        """The value when none is supplied."""
        self._default = value
        return self

    def array(self) -> NumberListParameter:
        """Make it a list instead: a comma-separated value."""
        other = NumberListParameter(self._description)
        self._carry(other)
        return other

    @property
    def value(self) -> float | None:
        """The resolved value, an ``int`` when it is whole, or ``None`` when unset."""
        raw = self._raw()
        return None if raw is None else _number(raw)


class BooleanParameter(Parameter):
    """A boolean parameter: a flag that takes no value."""

    def __init__(self, description: str) -> None:
        """A boolean parameter with its ``--help`` description."""
        super().__init__(description, "boolean")

    def default(self, value: bool) -> Self:
        """The value when the flag is not given."""
        self._default = value
        return self

    @property
    def value(self) -> bool | None:
        """The resolved value, or ``None`` when unset."""
        raw = self._raw()
        return None if raw is None else raw == "true"


class StringListParameter(Parameter):
    """A list of strings: a comma-separated value on the command line."""

    def __init__(self, description: str) -> None:
        """A string-list parameter with its ``--help`` description."""
        super().__init__(description, "string")
        self._array = True

    @property
    def value(self) -> list[str] | None:
        """The resolved values, or ``None`` when unset."""
        raw = self._raw()
        return None if raw is None else raw.split(",")


class NumberListParameter(Parameter):
    """A list of numbers: a comma-separated value on the command line."""

    def __init__(self, description: str) -> None:
        """A number-list parameter with its ``--help`` description."""
        super().__init__(description, "number")
        self._array = True

    @property
    def value(self) -> list[float] | None:
        """The resolved values, each an ``int`` when whole, or ``None`` when unset."""
        raw = self._raw()
        return None if raw is None else [_number(part) for part in raw.split(",")]


class Group(Field):
    """A parallel batch of targets, named like one. Start one with :func:`group`."""

    def __init__(self, members: tuple[Target, ...]) -> None:
        """A group of ``members``, each a sibling field."""
        super().__init__()
        self.members_ = members
        """The targets in the group."""

    def manifest(self) -> dict[str, object]:
        """The group as the engine's manifest describes it."""
        return {"name": self.name, "members": [t.name for t in self.members_]}


def target() -> Target:
    """A new target, to configure fluently and assign to a build field."""
    return Target()


def parameter(description: str = "") -> StringParameter:
    """A new string parameter; ``.number()``, ``.boolean()`` or ``.array()`` recast it.

    The description is what ``--help`` shows for it.
    """
    return StringParameter(description)


def group(*members: Target) -> Group:
    """A new group of ``members``, to assign to a build field."""
    return Group(members)
