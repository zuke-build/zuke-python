# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The API reference: the real package's surface, and the edges of a fake one."""

from __future__ import annotations

import json
from pathlib import Path

import zuke
from zuke._reference import (
    SCHEMA,
    ApiPackage,
    ApiReference,
    ApiSymbol,
    markdown,
    reference,
)

ROOT = Path(zuke.__file__).parent


def _package(ref: ApiReference, slug: str) -> ApiPackage:
    return next(p for p in ref["packages"] if p["dir"] == slug)


def _symbol(package: ApiPackage, name: str) -> ApiSymbol:
    return next(s for s in package["symbols"] if s["name"] == name)


def test_markdown_turns_roles_and_literals_into_backticks() -> None:
    assert markdown("See :class:`Target` and ``ctx.sh``.") == (
        "See `Target` and `ctx.sh`."
    )
    assert markdown(":func:`~zuke._dsl.target`") == "`target`"
    assert markdown(":mod:`zuke._facade`") == "`zuke._facade`"


def test_the_root_package_is_every_name_the_init_imports() -> None:
    ref = reference(ROOT, "9.9.9")
    assert ref["version"] == SCHEMA
    assert ref["generated"] == "zuke@9.9.9"
    root = ref["packages"][0]
    assert (root["name"], root["dir"]) == ("zuke", "zuke")
    assert root["summary"].startswith("Zuke for Python: author your build")
    names = [s["name"] for s in root["symbols"]]
    assert sorted(names) == sorted(n for n in zuke.__all__ if n != "__version__")
    assert names == sorted(names, key=lambda n: (n.lower(), n))


def test_signatures_are_spelled_as_the_source_writes_them() -> None:
    root = reference(ROOT, "1.0.0")["packages"][0]
    assert _symbol(root, "target")["signature"] == "def target() -> Target"
    assert _symbol(root, "Target")["signature"] == "class Target(Field)"
    assert _symbol(root, "Build")["signature"] == "class Build"
    duration = _symbol(root, "Duration")
    assert duration["kind"] == "typeAlias"
    assert duration["signature"] == "Duration = str | int"
    assert duration["doc"].startswith("A duration as the engine takes it: `")


def test_members_drop_self_and_say_async_and_static() -> None:
    ref = reference(ROOT, "1.0.0")
    target = _symbol(ref["packages"][0], "Target")
    depends = next(m for m in target.get("members", []) if m["name"] == "depends_on")
    assert depends["signature"] == "depends_on(*targets: Target) -> Self"
    assert depends["kind"] == "method"
    context = _symbol(ref["packages"][0], "ServiceContext")
    sh = next(m for m in context.get("members", []) if m["name"] == "sh")
    assert sh["signature"].startswith("async sh(*argv: str, cwd: str | None=None")
    tasks = _symbol(_package(ref, "docker"), "DockerTasks")
    build = next(m for m in tasks.get("members", []) if m["name"] == "build")
    assert build["signature"].startswith("static async build(ctx: ServiceContext")


def test_dataclass_fields_are_properties_with_their_docstrings() -> None:
    result = _symbol(reference(ROOT, "1.0.0")["packages"][0], "ExecResult")
    assert result.get("members") == [
        {
            "name": "code",
            "kind": "property",
            "optional": False,
            "signature": "code: int",
            "doc": "The exit code.",
        },
        {
            "name": "stdout",
            "kind": "property",
            "optional": False,
            "signature": "stdout: str",
            "doc": "What it printed to stdout.",
        },
        {
            "name": "stderr",
            "kind": "property",
            "optional": False,
            "signature": "stderr: str",
            "doc": "What it printed to stderr.",
        },
    ]


def test_every_tool_module_is_a_package_of_its_public_classes() -> None:
    ref = reference(ROOT, "1.0.0")
    tools = sorted(
        p.stem for p in (ROOT / "tools").glob("*.py") if p.stem != "__init__"
    )
    assert [p["dir"] for p in ref["packages"][1:]] == tools
    docker = _package(ref, "docker")
    assert docker["name"] == "zuke.tools.docker"
    assert docker["summary"].startswith("`@zuke/docker`")
    kinds = {s["kind"] for s in docker["symbols"]}
    assert kinds == {"class"}
    assert not any(s["name"] in ("PACKAGE", "VERSION") for s in docker["symbols"])


def test_the_same_source_renders_the_same_reference() -> None:
    first = json.dumps(reference(ROOT, "1.0.0"))
    assert first == json.dumps(reference(ROOT, "1.0.0"))


FAKE_INIT = '''"""A fake package.

Its second paragraph is not the summary.
"""

from __future__ import annotations

from zuke.core import Thing, VERSION, helper, Alias, lower

__version__ = "0.0.0"
'''

FAKE_CORE = '''
from typing import overload

type Alias = int | str
"""A type statement."""

VERSION = "1"

lower = 3

A = B = 2


def helper(x, /, y: int = 2) -> None:
    """Help with :class:`Thing`."""


class Thing:
    """A thing."""

    plain: int
    a.b: int = 1
    _hidden: int

    @overload
    def get(self, key: int) -> int: ...

    def get(self, key):
        """Get it."""

    @property
    def size(self):
        """Its size."""

    @size.setter
    def size(self, value: int) -> None: ...

    @classmethod
    def make(cls, /, n: int) -> "Thing":
        """Make one."""

    def _private(self) -> None: ...
'''

FAKE_TOOL = '''
PACKAGE = "fake"


def task() -> None:
    """A loose task."""


class _Hidden:
    """Not public."""


class Empty:
    pass
'''


def _fake(tmp: Path) -> Path:
    root = tmp / "zuke"
    (root / "tools").mkdir(parents=True)
    (root / "__init__.py").write_text(FAKE_INIT)
    (root / "core.py").write_text(FAKE_CORE)
    (root / "tools" / "__init__.py").write_text('"""Tools."""\n')
    (root / "tools" / "fake.py").write_text(FAKE_TOOL)
    return root


def test_the_edges_of_a_fake_package(tmp_path: Path) -> None:
    ref = reference(_fake(tmp_path), "0.1.0")
    root = ref["packages"][0]
    assert root["summary"] == "A fake package."
    alias = _symbol(root, "Alias")
    assert (alias["kind"], alias["signature"], alias["doc"]) == (
        "typeAlias",
        "type Alias = int | str",
        "A type statement.",
    )
    lower = _symbol(root, "lower")
    assert (lower["kind"], lower["doc"]) == ("variable", "")
    assert _symbol(root, "VERSION")["doc"] == ""
    helper = _symbol(root, "helper")
    assert helper["signature"] == "def helper(x, /, y: int=2) -> None"
    assert helper["doc"] == "Help with `Thing`."
    thing = _symbol(root, "Thing")
    assert thing.get("members") == [
        {
            "name": "plain",
            "kind": "property",
            "optional": False,
            "signature": "plain: int",
            "doc": "",
        },
        {
            "name": "get",
            "kind": "method",
            "optional": False,
            "signature": "get(key)",
            "doc": "Get it.",
        },
        {
            "name": "size",
            "kind": "property",
            "optional": False,
            "signature": "size: object",
            "doc": "Its size.",
        },
        {
            "name": "make",
            "kind": "method",
            "optional": False,
            "signature": "make(n: int) -> 'Thing'",
            "doc": "Make one.",
        },
    ]
    tool = _package(ref, "fake")
    assert tool["summary"] == ""
    assert [s["name"] for s in tool["symbols"]] == ["Empty", "task"]
    assert "members" not in _symbol(tool, "Empty")
