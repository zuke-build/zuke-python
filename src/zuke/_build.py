# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The build class: its fields are its targets, parameters, groups and CI files.

A subclass is read when it is created: every field holding one of those is
named after its attribute, in declaration order, and every target a field
names must be a field of the same build, or the class fails to be made with
the offending field named. The instance is what the worker hosts; the hooks
a subclass overrides are the ones the manifest flags and the engine calls.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import ClassVar

from zuke._ci import Ci
from zuke._dsl import Group, Parameter, Service, Target
from zuke._duration import Duration
from zuke._field import Field
from zuke._guard import ProtocolError


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
    ci_: ClassVar[dict[str, Ci]] = {}
    """The CI files by name, in declaration order; set when the subclass is made."""

    def __init_subclass__(cls) -> None:
        """Discover and name the fields, then check every reference between them."""
        super().__init_subclass__()
        cls.targets_, cls.parameters_, cls.groups_, cls.ci_ = {}, {}, {}, {}
        for klass in reversed(cls.__mro__):
            if klass is Build or klass is object:
                continue
            for name, value in vars(klass).items():
                if isinstance(value, Target):
                    cls.targets_[name] = value
                elif isinstance(value, Parameter):
                    cls.parameters_[name] = value
                elif isinstance(value, Group):
                    cls.groups_[name] = value
                elif isinstance(value, Ci):
                    cls.ci_[name] = value
                else:
                    continue
                value.name_ = name
        cls._check_references()

    @classmethod
    def _check_references(cls) -> None:
        targets = list(cls.targets_.values())
        for name, t in cls.targets_.items():
            for setter, reference in t.references():
                cls._check(name, setter, reference, targets)
            for p in t.parameters():
                if p not in cls.parameters_.values():
                    cls._refuse(
                        name,
                        "requires",
                        "a parameter that is not a field of this build",
                    )
        for name, g in cls.groups_.items():
            for member in g.members_:
                cls._check(name, "group", member, targets)
        for name, c in cls.ci_.items():
            for reference in c.references():
                cls._check(name, "invokes", reference, targets)
        for t in cls.unforceable:
            cls._check("unforceable", "unforceable", t, targets)

    @classmethod
    def _check(
        cls, field: str, setter: str, reference: Field | str, targets: list[Target]
    ) -> None:
        if isinstance(reference, str):
            if reference not in cls.targets_:
                cls._refuse(field, setter, f'no target named "{reference}"')
        elif reference not in targets:
            cls._refuse(field, setter, "a target that is not a field of this build")

    @classmethod
    def _refuse(cls, field: str, setter: str, what: str) -> None:
        raise TypeError(f"{cls.__name__}.{field}: {setter} names {what}")

    def on_start(self) -> Awaitable[None] | None:
        """Override to run before the first target; sync or async."""
        return None

    def on_target_start(self, target: str) -> Awaitable[None] | None:
        """Override to run before each target; sync or async."""
        return None

    def on_target_end(self, target: str, status: str) -> Awaitable[None] | None:
        """Override to run after each target settles, with its status; sync or async."""
        return None

    def on_finish(self, ok: bool) -> Awaitable[None] | None:
        """Override to run when the build is done, told whether it succeeded."""
        return None

    def hooks_(self) -> dict[str, bool]:
        """Which hooks this build overrides: the ones the engine will call."""
        cls = type(self)
        flagged = {
            "onStart": cls.on_start is not Build.on_start,
            "onTargetStart": cls.on_target_start is not Build.on_target_start,
            "onTargetEnd": cls.on_target_end is not Build.on_target_end,
            "onFinish": cls.on_finish is not Build.on_finish,
        }
        return {name: True for name, overridden in flagged.items() if overridden}

    def describe(self) -> dict[str, object]:
        """The manifest: what ``build.describe`` answers."""
        m: dict[str, object] = {
            "name": type(self).__name__,
            "targets": [t.manifest() for t in self.targets_.values()],
        }
        for key, fields in (
            ("parameters", self.parameters_),
            ("groups", self.groups_),
            ("ci", self.ci_),
        ):
            if fields:
                m[key] = [f.manifest() for f in fields.values()]
        hooks = self.hooks_()
        if hooks:
            m["hooks"] = hooks
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

    def target_(self, name: str, method: str) -> Target:
        """The target ``method`` asks about, or a :class:`ProtocolError` naming it."""
        t = self.targets_.get(name)
        if t is None:
            raise ProtocolError(
                f'{method}: {type(self).__name__} has no target "{name}"'
            )
        return t

    def service_(self, name: str, method: str) -> Service:
        """The service ``method`` asks about, or a :class:`ProtocolError` naming it."""
        t = self.target_(name, method)
        if not isinstance(t, Service):
            raise ProtocolError(f'{method}: "{name}" is not a service')
        return t
