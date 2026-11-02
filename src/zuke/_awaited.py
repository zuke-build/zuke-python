# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""Settle what a user's function returned: awaited when it chose to be async."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable


async def awaited[T](value: T | Awaitable[T]) -> T:
    """``value`` itself, or its result when it is awaitable."""
    if inspect.isawaitable(value):
        return await value
    return value
