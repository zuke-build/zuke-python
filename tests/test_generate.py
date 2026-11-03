# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The facade generator: names, types, the goldens of a fixture spec, its refusals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zuke._generate import (
    SPEC_VERSION,
    Scope,
    annotation,
    docstring,
    generate,
    python_name,
    snake_case,
)

FIXTURES = Path(__file__).parent / "fixtures"
SPEC: object = json.loads((FIXTURES / "spec.json").read_text())
VERSIONS = {"widget": "0.1.0", "tally": "0.2.0"}


def test_names_are_snake_case_and_reserved_ones_suffixed() -> None:
    assert snake_case("noThrow") == "no_throw"
    assert snake_case("allowFFI") == "allow_ffi"
    assert snake_case("maxCapturedBytes") == "max_captured_bytes"
    assert python_name("pass") == "pass_"
    assert python_name("type") == "type_"
    assert python_name("match") == "match_"
    assert python_name("self") == "self_"
    assert python_name("toolPath") == "tool_path"


def test_annotation_of_every_kind() -> None:
    scope = Scope(frozenset({"ToolSettings"}))
    lit = {"kind": "literal", "value": "a"}
    cases: list[tuple[object, str]] = [
        ({"kind": "string"}, "str"),
        ({"kind": "number"}, "float"),
        ({"kind": "boolean"}, "bool"),
        ({"kind": "null"}, "None"),
        ({"kind": "unknown"}, "object"),
        (lit, 'Literal["a"]'),
        ({"kind": "literal", "value": True}, "Literal[True]"),
        ({"kind": "literal", "value": 2}, "Literal[2]"),
        ({"kind": "union", "members": [lit, {"kind": "null"}]}, 'Literal["a"] | None'),
        ({"kind": "union", "members": [{"kind": "null"}]}, "None"),
        ({"kind": "union", "members": []}, "object"),
        (
            {"kind": "union", "members": [{"kind": "string"}, {"kind": "unknown"}]},
            "object",
        ),
        ({"kind": "array", "element": {"kind": "string"}}, "Sequence[str]"),
        (
            {"kind": "record", "key": {"kind": "string"}, "value": {"kind": "number"}},
            "Mapping[str, float]",
        ),
        ({"kind": "object", "name": "Options"}, "Mapping[str, object]"),
        ({"kind": "settings", "name": "X"}, "X"),
        ({"kind": "settings", "name": "ToolSettings"}, "ToolSettings"),
        ({"kind": "configure", "settings": "X"}, "Callable[[X], X]"),
        ({"kind": "output"}, "ExecResult"),
        ({"kind": "self"}, "Self"),
    ]
    for node, expected in cases:
        assert annotation(node, scope) == expected, node
    assert scope.bases == {"ToolSettings"}
    with pytest.raises(ValueError, match="unknown kind 'tuple'"):
        annotation({"kind": "tuple"}, scope)
    with pytest.raises(ValueError, match="needs members"):
        annotation({"kind": "union"}, scope)


def test_docstring_escapes_and_falls_back() -> None:
    assert docstring("", "  ", "Fallback.") == ['  """Fallback."""']
    assert docstring('a \\ b """ c\n\nmore', "  ", "x") == [
        '  """a \\\\ b \\"\\"\\" c',
        "",
        "  more",
        '  """',
    ]


def test_fixture_spec_generates_the_goldens() -> None:
    out = generate(SPEC, VERSIONS)
    assert sorted(out) == ["__init__.py", "_tooling.py", "tally.py", "widget.py"]
    for name, text in out.items():
        golden = (FIXTURES / "facades" / name).read_text().replace("\r\n", "\n")
        assert text == golden, name


def test_refusals_name_what_is_wrong() -> None:
    with pytest.raises(ValueError, match=f"this generator reads {SPEC_VERSION}"):
        generate({"spec": 99, "tooling": [], "packages": []}, {})
    with pytest.raises(ValueError, match="tooling and packages must be lists"):
        generate({"spec": 1, "tooling": {}, "packages": []}, {})
    with pytest.raises(ValueError, match="no version for @zuke/widget"):
        generate(SPEC, {"tally": "0.2.0"})
    bad: dict[str, object] = {
        "spec": 1,
        "tooling": [],
        "packages": [
            {"name": "p", "summary": "", "tasks": [], "settings": "no"},
        ],
    }
    with pytest.raises(ValueError, match="p: settings and tasks must be lists"):
        generate(bad, {"p": "1.0.0"})
    tasks: dict[str, object] = {"name": "PTasks", "doc": "", "tasks": "no"}
    bad["packages"] = [{"name": "p", "summary": "", "tasks": [tasks], "settings": []}]
    with pytest.raises(ValueError, match="PTasks: tasks must be a list"):
        generate(bad, {"p": "1.0.0"})
    settings: dict[str, object] = {
        "name": "S",
        "doc": "",
        "extends": None,
        "setters": "no",
    }
    bad["packages"] = [
        {"name": "p", "summary": "", "tasks": [], "settings": [settings]}
    ]
    with pytest.raises(ValueError, match="S: setters must be a list"):
        generate(bad, {"p": "1.0.0"})
    member: dict[str, object] = {
        "name": "m",
        "doc": "",
        "params": "no",
        "returns": {"kind": "self"},
    }
    settings["setters"] = [member]
    with pytest.raises(ValueError, match="m: params must be a list"):
        generate(bad, {"p": "1.0.0"})
