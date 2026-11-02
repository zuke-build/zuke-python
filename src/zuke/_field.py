# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""A build field: a target, parameter, group or CI file named after its attribute."""

from __future__ import annotations


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


def name_of(reference: Field | str) -> str:
    """The name a reference stands for: a field's, or the name itself."""
    return reference if isinstance(reference, str) else reference.name
