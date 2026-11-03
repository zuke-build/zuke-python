# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""Every conformance manifest can be written here, and describes back the same."""

from __future__ import annotations

import pytest

from twins import CASES, cases, expected, manifest_of, twin


def test_the_vendored_cases_name_the_engine_release() -> None:
    assert (CASES / "VERSION").read_text().strip() == "engine-v1.2.0"
    assert len(cases()) == 23


@pytest.mark.parametrize("case", cases())
def test_the_twin_describes_the_cases_manifest(case: str) -> None:
    manifest = manifest_of(case)
    build = twin(manifest)
    assert build().describe() == expected(manifest)
