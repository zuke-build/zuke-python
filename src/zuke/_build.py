# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The build class: its fields are its targets, parameters and groups.

A subclass is read when it is created: every field holding a target, parameter
or group is named after its attribute, in declaration order, and every target
a field names must be a field of the same build, or the class fails to be
made with the offending field named. The instance is what the worker hosts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from zuke._context import Context
from zuke._dsl import Duration, Group, Parameter, Target
from zuke._guard import ProtocolError
from zuke._rpc import Peer
from zuke._worker import RunRequest


class Build:
    """Extend this with targets as fields; see :func:`~zuke.target`."""

    deadline: ClassVar[Duration | None] = None
    """How long the whole run may take, as a duration or milliseconds."""
    unforceable: ClassVar[tuple[Target, ...]] = ()
    """Targets ``--force`` may never re-run."""

    targets_: ClassVar[dict[str, Target]] = {}
    """The targets by name, in declaration order; set when the subclass is made."""
    parameters_: ClassVar[dict[str, Parameter]] = {}
    """The parameters by name, in declaration order; set when the subclass is made."""
    groups_: ClassVar[dict[str, Group]] = {}
    """The groups by name, in declaration order; set when the subclass is made."""

    def __init_subclass__(cls) -> None:
        """Discover and name the fields, then check every reference between them."""
        super().__init_subclass__()
        cls.targets_, cls.parameters_, cls.groups_ = {}, {}, {}
        for klass in reversed(cls.__mro__):
            if klass is Build or klass is object:
                continue
            for name, value in vars(klass).items():
                if isinstance(value, Target):
                    value.name_ = name
                    cls.targets_[name] = value
                elif isinstance(value, Parameter):
                    value.name_ = name
                    cls.parameters_[name] = value
                elif isinstance(value, Group):
                    value.name_ = name
                    cls.groups_[name] = value
        cls._check_references()

    @classmethod
    def _check_references(cls) -> None:
        targets = list(cls.targets_.values())
        for name, t in cls.targets_.items():
            for setter, reference in t.references():
                if isinstance(reference, str):
                    if reference not in cls.targets_:
                        cls._refuse(name, setter, f'no target named "{reference}"')
                elif reference not in targets:
                    cls._refuse(
                        name, setter, "a target that is not a field of this build"
                    )
            for p in t.parameters():
                if p not in cls.parameters_.values():
                    cls._refuse(
                        name,
                        "requires",
                        "a parameter that is not a field of this build",
                    )
        for name, g in cls.groups_.items():
            for member in g.members_:
                if member not in targets:
                    cls._refuse(
                        name, "group", "a target that is not a field of this build"
                    )
        for t in cls.unforceable:
            if t not in targets:
                cls._refuse(
                    "unforceable",
                    "unforceable",
                    "a target that is not a field of this build",
                )

    @classmethod
    def _refuse(cls, field: str, setter: str, what: str) -> None:
        raise TypeError(f"{cls.__name__}.{field}: {setter} names {what}")

    def describe(self) -> dict[str, object]:
        """The manifest: what ``build.describe`` answers."""
        m: dict[str, object] = {
            "name": type(self).__name__,
            "targets": [t.manifest() for t in self.targets_.values()],
        }
        if self.parameters_:
            m["parameters"] = [p.manifest() for p in self.parameters_.values()]
        if self.groups_:
            m["groups"] = [g.manifest() for g in self.groups_.values()]
        config: dict[str, object] = {}
        if self.deadline is not None:
            config["deadline"] = self.deadline
        if self.unforceable:
            config["unforceable"] = [t.name for t in self.unforceable]
        if config:
            m["config"] = config
        return m

    def configure(self, parameters: Mapping[str, str | None]) -> None:
        """Take the resolved parameters from ``build.configure``."""
        for name, p in self.parameters_.items():
            p.resolve(parameters.get(name))

    async def run_target(self, request: RunRequest, engine: Peer) -> None:
        """Run the named target's body for ``target.run``."""
        t = self.targets_.get(request.target)
        if t is None:
            raise ProtocolError(
                f'target.run: {type(self).__name__} has no target "{request.target}"'
            )
        await t.run_body(
            Context(engine, request.target, request.run_id, request.dry_run)
        )
