# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The package imports and agrees with pyproject.toml about its version."""

import tomllib
from pathlib import Path

import zuke

ROOT = Path(__file__).resolve().parent.parent


def test_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert zuke.__version__ == pyproject["project"]["version"]


def test_public_surface_is_declared() -> None:
    assert zuke.__all__ == sorted(zuke.__all__)
    assert {"Build", "target", "parameter", "group", "run", "__version__"} <= set(
        zuke.__all__
    )
    assert all(hasattr(zuke, name) for name in zuke.__all__)
