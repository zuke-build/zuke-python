#!/usr/bin/env python3
# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""Vendor the engine's conformance cases at a tag into ``tests/protocol/cases``.

Usage: ``uv run scripts/vendor_cases.py <path to a zuke checkout> <tag>``. The
tag is recorded in ``tests/protocol/cases/VERSION``; the twins and the replay
then test against that engine release.
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
from io import BytesIO
from pathlib import Path

CASES = Path(__file__).resolve().parent.parent / "tests" / "protocol" / "cases"
PREFIX = "packages/engine/conformance/"


def main(checkout: str, tag: str) -> None:
    """Replace the vendored cases with the ones at ``tag`` in ``checkout``."""
    archive = subprocess.run(
        ["git", "-C", checkout, "archive", tag, PREFIX.rstrip("/")],
        check=True,
        capture_output=True,
    ).stdout
    for stale in CASES.glob("*.json"):
        stale.unlink()
    with tarfile.open(fileobj=BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if member.isfile() and member.name.endswith(".json"):
                data = tar.extractfile(member)
                if data is None:
                    raise ValueError(f"{member.name}: not a file in the archive")
                (CASES / Path(member.name).name).write_bytes(data.read())
    (CASES / "VERSION").write_text(f"{tag}\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
