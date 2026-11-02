# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The late settings a target declares: a lock, a wait gate, interval checks.

Each is configured through a lambda, the shape every Zuke setting takes, and
evaluated when the engine asks ``target.settings``, after the parameters have
resolved, so a key or a timeout may read a parameter's value.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Self

from zuke._duration import Duration
from zuke._field import Field, name_of

type Configure[S] = Callable[[S], S]
"""A settings lambda: given the settings, returns them configured."""

Check = Callable[[], bool | Awaitable[bool]]
"""A predicate the engine asks, sync or async."""

Validation = Callable[[], Awaitable[None] | None]
"""A check that raises to report a problem, sync or async."""


class LockSettings:
    """A cross-run lock, as ``.lock(lambda s: ...)`` configures it."""

    def __init__(self) -> None:
        """An unconfigured lock; ``key`` is required."""
        self._key: str | None = None
        self._ttl: Duration | None = None
        self._wait_up_to: Duration | None = None
        self._poll_every: Duration | None = None
        self._hold_for_run = False

    def key(self, key: str) -> Self:
        """The lock's key, shared by every run that must not overlap."""
        self._key = key
        return self

    def ttl(self, ttl: Duration) -> Self:
        """How long the lock may be held."""
        self._ttl = ttl
        return self

    def wait_up_to(self, limit: Duration) -> Self:
        """How long to wait for a held lock before giving up."""
        self._wait_up_to = limit
        return self

    def poll_every(self, interval: Duration) -> Self:
        """How often to poll a held lock."""
        self._poll_every = interval
        return self

    def hold_for_run(self) -> Self:
        """Keep the lock until the run ends rather than until the target does."""
        self._hold_for_run = True
        return self

    def manifest(self) -> dict[str, object]:
        """The ``lock`` section of ``target.settings``."""
        if self._key is None:
            raise ValueError("lock: a key is required")
        m: dict[str, object] = {"key": self._key}
        for name, value in (
            ("ttl", self._ttl),
            ("waitUpTo", self._wait_up_to),
            ("pollEvery", self._poll_every),
        ):
            if value is not None:
                m[name] = value
        if self._hold_for_run:
            m["holdForRun"] = True
        return m


class WaitSettings:
    """A wait gate, as ``.waits_for(lambda s: ...)`` configures it."""

    def __init__(self) -> None:
        """An unconfigured gate; ``external_signal`` or ``resume_when`` is required."""
        self._on: dict[str, object] | None = None
        self._check: Check | None = None
        self._timeout: Duration | None = None
        self._on_timeout: Field | str | None = None

    def external_signal(self, name: str) -> Self:
        """Wait for ``zuke resume <run> --signal <name>``."""
        self._on = {"kind": "externalSignal", "name": name}
        return self

    def resume_when(self, check: Check, every: Duration | None = None) -> Self:
        """Wait until ``check`` answers true, asked on ``every`` interval."""
        self._on = {"kind": "resumeWhen"}
        if every is not None:
            self._on["interval"] = every
        self._check = check
        return self

    def timeout(self, limit: Duration) -> Self:
        """How long to wait before the timeout disposition applies."""
        self._timeout = limit
        return self

    def on_timeout(self, disposition: Field | str) -> Self:
        """On timeout: a compensation target, ``"fail"`` or ``"cancel-run"``."""
        self._on_timeout = disposition
        return self

    @property
    def check(self) -> Check | None:
        """The ``resume_when`` predicate, when that is the trigger."""
        return self._check

    def manifest(self) -> dict[str, object]:
        """The ``waitsFor`` section of ``target.settings``."""
        if self._on is None:
            raise ValueError(
                "waits_for: name the trigger with external_signal or resume_when"
            )
        m: dict[str, object] = {"on": self._on}
        if self._timeout is not None:
            m["timeout"] = self._timeout
        if self._on_timeout is not None:
            m["onTimeout"] = name_of(self._on_timeout)
        return m


class ValidateDuringSettings:
    """Checks run on an interval while the body runs, from ``.validate_during``."""

    def __init__(self) -> None:
        """No checks yet."""
        self._every: Duration | None = None
        self._checks: dict[str, Validation] = {}

    def every(self, interval: Duration) -> Self:
        """The interval between rounds of checks."""
        self._every = interval
        return self

    def check(self, name: str, validation: Validation) -> Self:
        """A named check; it raises to report a problem."""
        self._checks[name] = validation
        return self

    @property
    def checks(self) -> dict[str, Validation]:
        """The checks by name, in the order declared."""
        return dict(self._checks)

    def manifest(self) -> dict[str, object]:
        """The ``validateDuring`` section of ``target.settings``."""
        m: dict[str, object] = {}
        if self._every is not None:
            m["every"] = self._every
        m["checks"] = list(self._checks)
        return m
