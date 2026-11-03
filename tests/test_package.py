# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The package imports, and its one version is the one pyproject.toml publishes."""

import re
import tomllib
from pathlib import Path

import zuke

ROOT = Path(__file__).resolve().parent.parent


def test_the_version_lives_in_the_package_and_pyproject_reads_it() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["dynamic"] == ["version"]
    source = ROOT / pyproject["tool"]["hatch"]["version"]["path"]
    # What hatchling reads when it builds a distribution: the assignment in
    # that file, not the metadata of whatever install the environment holds,
    # which goes stale the moment a release bumps the version.
    found = re.search(r'^__version__ = "([^"]+)"', source.read_text(), re.MULTILINE)
    assert found is not None and found.group(1) == zuke.__version__


def test_public_surface_is_declared() -> None:
    assert zuke.__all__ == sorted(zuke.__all__)
    assert {"Build", "target", "parameter", "group", "run", "__version__"} <= set(
        zuke.__all__
    )
    assert all(hasattr(zuke, name) for name in zuke.__all__)
