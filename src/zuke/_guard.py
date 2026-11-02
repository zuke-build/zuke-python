# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""Guards for what arrives from the engine: each names the field it rejects.

Everything read from the socket is untrusted, a request's params and an
answer alike, so the worker narrows every field through one of these rather
than trusting a shape. The message names the method and the field, since a
worker author sees it while writing against the engine.
"""

from __future__ import annotations

from typing import TypeGuard

from zuke._rpc import is_record


class ProtocolError(Exception):
    """The environment, a request or an answer is not protocol v1 as spoken here."""


def record(value: object, what: str) -> dict[str, object]:
    """``value`` as a JSON object, or a :class:`ProtocolError` naming ``what``."""
    if not is_record(value):
        raise ProtocolError(f"{what} must be an object")
    return value


def string(params: object, field: str, method: str) -> str:
    """The string at ``field``, or a :class:`ProtocolError` naming it."""
    if not is_record(params) or not isinstance(value := params.get(field), str):
        raise ProtocolError(f'{method}: "{field}" must be a string')
    return value


def string_or_none(params: object, field: str, method: str) -> str | None:
    """The string at ``field``, ``None`` when absent or null, else a ProtocolError."""
    value = params.get(field) if is_record(params) else None
    if value is not None and not isinstance(value, str):
        raise ProtocolError(f'{method}: "{field}" must be a string when present')
    return value


def is_list(value: object) -> TypeGuard[list[object]]:
    """Whether ``value`` is a JSON array."""
    return isinstance(value, list)


def strings(params: object, field: str, method: str) -> list[str]:
    """The list of strings at ``field``, or a :class:`ProtocolError` naming it."""
    value = params.get(field) if is_record(params) else None
    if not is_list(value) or not all(isinstance(item, str) for item in value):
        raise ProtocolError(f'{method}: "{field}" must be a list of strings')
    return [item for item in value if isinstance(item, str)]


def boolean(params: object, field: str, method: str) -> bool:
    """The boolean at ``field``, or a :class:`ProtocolError` naming it."""
    if not is_record(params) or not isinstance(value := params.get(field), bool):
        raise ProtocolError(f'{method}: "{field}" must be a boolean')
    return value


def integer(params: object, field: str, method: str) -> int:
    """The integer at ``field``, or a :class:`ProtocolError` naming it."""
    value = params.get(field) if is_record(params) else None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f'{method}: "{field}" must be an integer')
    return value
