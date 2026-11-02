# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""CI files a build declares, which ``zuke generate-ci`` renders from the manifest.

A CI file is a build field like a target, named after its attribute, which
names its default path: ``releaseWorkflow`` writes
``.github/workflows/release.yml``. The engine renders it from the manifest
exactly as it renders a TypeScript build's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, Self

from zuke._field import Field, name_of
from zuke._guard import is_list

Provider = Literal["github", "gitlab", "azure", "bitbucket"]
"""A CI provider the engine renders for."""

# shortcut: the pipeline, the invocation adjustments, the fan-out options and
# the pins are mappings passed through as given, which the engine validates
# field by field and refuses by name; typed builders for them arrive with the
# facade generator, which can emit them from core's own CI types.


class Ci(Field):
    """One CI file. Start one with :func:`ci`."""

    def __init__(self) -> None:
        """A CI file with nothing declared yet."""
        super().__init__()
        self._provider: Provider | None = None
        self._path: str | None = None
        self._pipeline: dict[str, object] | None = None
        self._invokes: list[Field | str | dict[str, object]] = []
        self._fan_out: bool | dict[str, object] | None = None
        self._pins: dict[str, object] | None = None

    def provider(self, provider: Provider) -> Self:
        """The provider to render for; GitHub when not set."""
        self._provider = provider
        return self

    def path(self, path: str) -> Self:
        """The output path, overriding the one the field name implies."""
        self._path = path
        return self

    def pipeline(self, fields: Mapping[str, object]) -> Self:
        """The pipeline fields, and the jobs unless ``invokes`` or ``fan_out`` do."""
        self._pipeline = dict(fields)
        return self

    def invokes(self, *entries: Field | str | Mapping[str, object]) -> Self:
        """The targets to run as jobs: bare, or through :func:`invoke` to adjust."""
        self._invokes.extend(
            dict(entry) if isinstance(entry, Mapping) else entry for entry in entries
        )
        return self

    def fan_out(self, options: bool | Mapping[str, object] = True) -> Self:
        """One job per target in the graph, with the fan-out options."""
        self._fan_out = dict(options) if isinstance(options, Mapping) else options
        return self

    def pins(self, pins: Mapping[str, object]) -> Self:
        """Pinned action references by action name."""
        self._pins = dict(pins)
        return self

    def references(self) -> list[Field | str]:
        """Every target the file invokes, for the build to check."""
        named: list[Field | str] = []
        for entry in self._invokes:
            if isinstance(entry, dict):
                target = entry.get("target")
                if isinstance(target, (Field, str)):
                    named.append(target)
                after = entry.get("after")
                if is_list(after):
                    named.extend(
                        item for item in after if isinstance(item, (Field, str))
                    )
            else:
                named.append(entry)
        return named

    def manifest(self) -> dict[str, object]:
        """The file as the manifest's ``ci`` list carries it."""
        m: dict[str, object] = {"name": self.name}
        for key, value in (
            ("provider", self._provider),
            ("path", self._path),
            ("pipeline", self._pipeline),
        ):
            if value is not None:
                m[key] = value
        if self._invokes:
            m["invokes"] = [_invocation(entry) for entry in self._invokes]
        if self._fan_out is not None:
            m["fanOut"] = self._fan_out
        if self._pins is not None:
            m["pins"] = self._pins
        return m


def _invocation(entry: Field | str | dict[str, object]) -> object:
    if not isinstance(entry, dict):
        return name_of(entry)
    resolved = dict(entry)
    target = resolved.get("target")
    if isinstance(target, (Field, str)):
        resolved["target"] = name_of(target)
    after = resolved.get("after")
    if is_list(after):
        resolved["after"] = [
            name_of(item) if isinstance(item, (Field, str)) else item for item in after
        ]
    return resolved


def ci() -> Ci:
    """A new CI file, to configure fluently and assign to a build field."""
    return Ci()


def invoke(
    target: Field | str, *, after: Sequence[Field | str] = (), **adjustments: object
) -> dict[str, object]:
    """An invoked target with the runner's adjustments, for :meth:`Ci.invokes`.

    ``after`` adds ``needs:`` edges; the other keywords, such as ``matrix``, are
    the invocation's fields as the engine names them.
    """
    entry: dict[str, object] = {"target": target}
    if after:
        entry["after"] = list(after)
    entry.update(adjustments)
    return entry
