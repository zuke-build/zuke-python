# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""Every Python source file opens with the copyright and license header.

This is the per-file identification the OpenSSF Best Practices criteria ask
for, mirrored from the main Zuke repository's test of the same name.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADER = "# Copyright (c) 2026 the Zuke contributors\n# SPDX-License-Identifier: MIT\n"
ROOTS = ("src", "tests", "scripts")


def python_files() -> list[Path]:
    return sorted(path for root in ROOTS for path in (ROOT / root).rglob("*.py"))


def test_every_source_file_carries_the_header() -> None:
    files = python_files()
    assert files, "no Python files found: the roots moved"
    missing = [
        str(path.relative_to(ROOT))
        for path in files
        if not path.read_text(encoding="utf-8").startswith(HEADER)
    ]
    assert missing == []
