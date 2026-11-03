# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The API reference: the SDK's public surface as the website's ``api.json``.

``./zuke api_reference`` writes the reference the Zuke website renders, in the
contract the engine repository's ``apiReference`` flow emits for TypeScript
from ``deno doc``: schema 1, a list of packages, each with its symbols, and
each class with its members. The packages are ``zuke`` itself, every name its
``__init__`` imports, and one per module of ``zuke.tools``. Everything is read
from the source with :mod:`ast`, so signatures are spelled exactly as written,
nothing is imported, and the same source always renders the same reference.
"""

from __future__ import annotations

import ast
import copy
import inspect
import re
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

SCHEMA = 1
"""The ``api.json`` schema this generator writes."""

Kind = Literal["class", "function", "typeAlias", "variable"]
"""A symbol's kind, named as the TypeScript reference names it."""


class ApiMember(TypedDict):
    """A class member as the reference renders it."""

    name: str
    """The member's name."""
    kind: Literal["method", "property"]
    """A method, or a property or field."""
    optional: bool
    """Always false: a Python member is never optional the way a TS one is."""
    signature: str
    """The member's signature, without ``self``."""
    doc: str
    """The member's docstring, as Markdown."""


class ApiSymbol(TypedDict):
    """One public symbol of a package."""

    name: str
    """The symbol's name."""
    kind: Kind
    """What it is."""
    doc: str
    """Its docstring, as Markdown."""
    signature: str
    """Its signature, as the source spells it."""
    deprecated: bool
    """Always false: the SDK deprecates nothing yet."""
    members: NotRequired[list[ApiMember]]
    """A class's own public members, in declaration order."""


class ApiPackage(TypedDict):
    """One package: ``zuke`` or a module of ``zuke.tools``."""

    name: str
    """The import path, e.g. ``zuke.tools.docker``."""
    dir: str
    """The page slug the website gives it, e.g. ``docker``."""
    summary: str
    """The first paragraph of the module's docstring."""
    symbols: list[ApiSymbol]
    """Its public symbols, by name."""


class ApiReference(TypedDict):
    """The whole ``api.json`` document."""

    version: int
    """The schema version, :data:`SCHEMA`."""
    generated: str
    """What it was generated from, ``zuke@<version>``: no timestamp, so a rerun
    of the same release diffs to nothing."""
    packages: list[ApiPackage]
    """``zuke`` first, then each module of ``zuke.tools`` by name."""


_ROLE = re.compile(r":[a-z]+:`(~?)([^`]+)`")
_LITERAL = re.compile(r"``([^`]+)``")


def markdown(doc: str) -> str:
    """A reStructuredText docstring as the Markdown the website renders.

    ``:class:`Target``` becomes ```Target```, a ``~`` keeping the last dotted
    part only, and a double-backtick literal becomes a single-backtick one.
    """

    def role(match: re.Match[str]) -> str:
        name = match.group(2)
        return f"`{name.rsplit('.', 1)[-1] if match.group(1) else name}`"

    return _LITERAL.sub(r"`\1`", _ROLE.sub(role, doc))


def _doc(
    node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
) -> str:
    return markdown(ast.get_docstring(node) or "")


def _attribute_doc(body: list[ast.stmt], index: int) -> str:
    """The string literal right after ``body[index]``: an attribute's docstring."""
    following = body[index + 1] if index + 1 < len(body) else None
    if (
        isinstance(following, ast.Expr)
        and isinstance(following.value, ast.Constant)
        and isinstance(following.value.value, str)
    ):
        return markdown(inspect.cleandoc(following.value.value))
    return ""


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {ast.unparse(d) for d in node.decorator_list}


def _arguments(node: ast.FunctionDef | ast.AsyncFunctionDef, bound: bool) -> str:
    args = node.args
    if bound:
        # Drop self or cls; the defaults align to the end, so they stay put.
        args = copy.copy(args)
        if args.posonlyargs:
            args.posonlyargs = args.posonlyargs[1:]
        else:
            args.args = args.args[1:]
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"({ast.unparse(args)}){returns}"


def _member(node: ast.stmt, body: list[ast.stmt], index: int) -> ApiMember | None:
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        name = node.target.id
        signature = f"{name}: {ast.unparse(node.annotation)}"
        return _public_member(name, "property", signature, _attribute_doc(body, index))
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return None
    decorators = _decorators(node)
    if any(d.endswith((".setter", ".deleter")) or d == "overload" for d in decorators):
        return None
    if "property" in decorators:
        returns = ast.unparse(node.returns) if node.returns else "object"
        return _public_member(
            node.name, "property", f"{node.name}: {returns}", _doc(node)
        )
    static = "staticmethod" in decorators
    prefix = ("static " if static else "") + (
        "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    )
    signature = f"{prefix}{node.name}{_arguments(node, bound=not static)}"
    return _public_member(node.name, "method", signature, _doc(node))


def _public_member(
    name: str, kind: Literal["method", "property"], signature: str, doc: str
) -> ApiMember | None:
    if name.startswith("_"):
        return None
    return {
        "name": name,
        "kind": kind,
        "optional": False,
        "signature": signature,
        "doc": doc,
    }


def _instance_attributes(init: ast.FunctionDef) -> list[ApiMember]:
    """The ``self.<name>`` attributes ``__init__`` assigns, typed where it can tell.

    An annotated assignment gives its annotation; a parameter assigned as is
    gives the parameter's; anything else is named without a type.
    """
    params = {a.arg: a.annotation for a in init.args.args if a.annotation}
    found: list[ApiMember] = []
    for index, stmt in enumerate(init.body):
        target = stmt.target if isinstance(stmt, ast.AnnAssign) else None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
        if not (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            continue
        typed = stmt.annotation if isinstance(stmt, ast.AnnAssign) else None
        value = stmt.value if isinstance(stmt, ast.Assign) else None
        if isinstance(value, ast.Name):
            typed = params.get(value.id)
        signature = f"{target.attr}: {ast.unparse(typed)}" if typed else target.attr
        doc = _attribute_doc(init.body, index)
        member = _public_member(target.attr, "property", signature, doc)
        if member is not None:
            found.append(member)
    return found


def _class(node: ast.ClassDef) -> ApiSymbol:
    bases = ", ".join(ast.unparse(b) for b in node.bases)
    members: list[ApiMember] = []
    for index, child in enumerate(node.body):
        if isinstance(child, ast.FunctionDef) and child.name == "__init__":
            # The constructor itself is private; what it assigns to self is not.
            members.extend(_instance_attributes(child))
        elif (member := _member(child, node.body, index)) is not None:
            members.append(member)
    symbol: ApiSymbol = {
        "name": node.name,
        "kind": "class",
        "doc": _doc(node),
        "signature": f"class {node.name}({bases})" if bases else f"class {node.name}",
        "deprecated": False,
    }
    if members:
        symbol["members"] = members
    return symbol


def _symbols(module: ast.Module) -> dict[str, ApiSymbol]:
    """Every top-level symbol a module defines, public or not, by name."""
    found: dict[str, ApiSymbol] = {}
    for index, node in enumerate(module.body):
        if isinstance(node, ast.ClassDef):
            found[node.name] = _class(node)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            keyword = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            found[node.name] = {
                "name": node.name,
                "kind": "function",
                "doc": _doc(node),
                "signature": f"{keyword} {node.name}{_arguments(node, bound=False)}",
                "deprecated": False,
            }
        elif isinstance(node, ast.TypeAlias):
            name = ast.unparse(node.name)
            found[name] = _alias(
                name, "typeAlias", ast.unparse(node), module.body, index
            )
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name = node.targets[0].id
            signature = f"{name} = {ast.unparse(node.value)}"
            # The value's shape, not the name's case, tells an alias from a constant.
            kind: Kind = (
                "typeAlias" if isinstance(node.value, _TYPE_SHAPES) else "variable"
            )
            found[name] = _alias(name, kind, signature, module.body, index)
    return found


_TYPE_SHAPES = (ast.BinOp, ast.Subscript, ast.Name, ast.Attribute)
"""What an assigned type alias's value looks like: ``str | int``, ``dict[str, X]``."""


def _alias(
    name: str, kind: Kind, signature: str, body: list[ast.stmt], index: int
) -> ApiSymbol:
    return {
        "name": name,
        "kind": kind,
        "doc": _attribute_doc(body, index),
        "signature": signature,
        "deprecated": False,
    }


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _summary(module: ast.Module) -> str:
    return " ".join(_doc(module).split("\n\n", 1)[0].split())


def _by_name(symbols: list[ApiSymbol]) -> list[ApiSymbol]:
    return sorted(symbols, key=lambda s: (s["name"].lower(), s["name"]))


def _exported(module: ast.Module) -> set[str]:
    """The names a module's ``__all__`` lists, or none when it has no list."""
    for node in module.body:
        if (
            isinstance(node, ast.Assign)
            and ast.unparse(node.targets[0]) == "__all__"
            and isinstance(node.value, ast.List)
        ):
            return {
                e.value
                for e in node.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            }
    return set()


def _root_package(root: Path) -> ApiPackage:
    """``zuke``: each name ``__init__`` imports from a module of the package.

    Raises ``ValueError`` when ``__all__`` exports a name no such import
    defines, so a re-export the reader cannot follow fails the generation
    rather than vanishing from the reference.
    """
    init = _parse(root / "__init__.py")
    symbols: list[ApiSymbol] = []
    for node in init.body:
        # Only the package's own modules: a __future__ import defines nothing.
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("zuke."):
            module = str(node.module).replace(".", "/")
            defined = _symbols(_parse(root.parent / f"{module}.py"))
            symbols.extend(defined[alias.name] for alias in node.names)
    missing = _exported(init) - {"__version__"} - {s["name"] for s in symbols}
    if missing:
        raise ValueError(
            f"zuke/__init__.py exports {', '.join(sorted(missing))} without an "
            "absolute import from a zuke module, so the reference cannot document it"
        )
    return {
        "name": "zuke",
        "dir": "zuke",
        "summary": _summary(init),
        "symbols": _by_name(symbols),
    }


def _tool_package(path: Path) -> ApiPackage:
    """A module of ``zuke.tools``: the public classes and functions it defines."""
    module = _parse(path)
    symbols = [
        s
        for name, s in _symbols(module).items()
        if not name.startswith("_") and s["kind"] in ("class", "function")
    ]
    return {
        "name": f"zuke.tools.{path.stem}",
        "dir": path.stem,
        "summary": _summary(module),
        "symbols": _by_name(symbols),
    }


def reference(root: Path, version: str) -> ApiReference:
    """The reference for the ``zuke`` package at ``root``, released as ``version``."""
    tools = sorted(p for p in (root / "tools").glob("*.py") if p.name != "__init__.py")
    return {
        "version": SCHEMA,
        "generated": f"zuke@{version}",
        "packages": [_root_package(root), *(_tool_package(p) for p in tools)],
    }
