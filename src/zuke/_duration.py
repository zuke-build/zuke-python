# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""Durations as the engine takes them: ``"5m"``, ``"250ms"`` or milliseconds."""

from __future__ import annotations

import re

Duration = str | int
"""A duration as the engine takes it: ``"5m"``, ``"250ms"`` or milliseconds."""

_DURATION = re.compile(r"^(\d+)(ms|s|m|h|d)$")
_UNIT_MS = {"ms": 1, "s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}


def duration_ms(value: Duration, what: str) -> int:
    """``value`` in milliseconds, or a ``ValueError`` naming ``what``."""
    if isinstance(value, int):
        return value
    match = _DURATION.match(value)
    if match is None:
        raise ValueError(f'{what}: "{value}" is not a duration such as "5m" or "250ms"')
    return int(match.group(1)) * _UNIT_MS[match.group(2)]
