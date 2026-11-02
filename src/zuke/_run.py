# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""``run``: the last line of a build file."""

from __future__ import annotations

import inspect
import os
import sys

from zuke._build import Build
from zuke._worker import host


def run(build: type[Build]) -> None:
    """Host ``build`` when the engine started this process; otherwise do nothing.

    A build file ends with ``run(MyBuild)``. Started by the engine, the file
    becomes its worker. Imported, by a test say, the call is a no-op. Run by
    hand with ``python``, it says how a build is run and exits.
    """
    if "ZUKE_ENGINE_ADDR" in os.environ:
        host(build())
        return
    frame = inspect.currentframe()
    caller = None if frame is None else frame.f_back
    if caller is not None and caller.f_globals.get("__name__") == "__main__":
        raise SystemExit(
            f"{build.__name__}: a Zuke build runs through the engine, "
            f"`./zuke <target>`, not `python {sys.argv[0]}`"
        )
