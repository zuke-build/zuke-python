# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""Zuke for Python: author your build as typed Python, run it on the Zuke engine.

A build is a class extending :class:`Build` whose fields are targets made with
:func:`target`, services made with :func:`service`, parameters made with
:func:`parameter`, groups made with :func:`group` and CI files made with
:func:`ci`; the file ends with :func:`run`. The engine starts the file as a
worker, asks it for the graph, and runs each target's body when its turn comes.
"""

from zuke._build import Build
from zuke._ci import Ci, ci, invoke
from zuke._context import (
    CommandError,
    Context,
    ExecResult,
    Outcome,
    Plan,
    ServiceContext,
    StateHandle,
)
from zuke._dsl import (
    BooleanParameter,
    Group,
    NumberListParameter,
    NumberParameter,
    Parameter,
    Service,
    StringListParameter,
    StringParameter,
    Target,
    group,
    parameter,
    service,
    target,
)
from zuke._duration import Duration
from zuke._run import run
from zuke._settings import LockSettings, ValidateDuringSettings, WaitSettings

__version__ = "1.0.0"  # x-release-please-version
"""The package version; release-please bumps it alongside pyproject.toml."""

__all__ = [
    "BooleanParameter",
    "Build",
    "Ci",
    "CommandError",
    "Context",
    "Duration",
    "ExecResult",
    "Group",
    "LockSettings",
    "NumberListParameter",
    "NumberParameter",
    "Outcome",
    "Parameter",
    "Plan",
    "Service",
    "ServiceContext",
    "StateHandle",
    "StringListParameter",
    "StringParameter",
    "Target",
    "ValidateDuringSettings",
    "WaitSettings",
    "__version__",
    "ci",
    "group",
    "invoke",
    "parameter",
    "run",
    "service",
    "target",
]
