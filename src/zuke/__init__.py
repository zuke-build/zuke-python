# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""Zuke for Python: author your build as typed Python, run it on the Zuke engine.

A build is a class extending :class:`Build` whose fields are targets made with
:func:`target`, parameters made with :func:`parameter` and groups made with
:func:`group`; the file ends with :func:`run`. The engine starts the file as a
worker, asks it for the graph, and runs each target's body when its turn comes.
"""

from zuke._build import Build
from zuke._dsl import (
    BooleanParameter,
    Context,
    Group,
    NumberListParameter,
    NumberParameter,
    Parameter,
    StringListParameter,
    StringParameter,
    Target,
    group,
    parameter,
    target,
)
from zuke._run import run

__version__ = "0.0.0"
"""The package version; release automation bumps it alongside pyproject.toml."""

__all__ = [
    "BooleanParameter",
    "Build",
    "Context",
    "Group",
    "NumberListParameter",
    "NumberParameter",
    "Parameter",
    "StringListParameter",
    "StringParameter",
    "Target",
    "__version__",
    "group",
    "parameter",
    "run",
    "target",
]
