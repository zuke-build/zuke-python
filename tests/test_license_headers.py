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
    missing = [str(path.relative_to(ROOT)) for path in files if not headed(path)]
    assert missing == []


def headed(path: Path) -> bool:
    """Whether the file opens with the header, after a shebang where one exists."""
    text = path.read_text(encoding="utf-8")
    if text.startswith("#!"):
        text = text.partition("\n")[2]
    return text.startswith(HEADER)
