# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""``run``: a worker under the engine, a no-op when imported, a hint by hand."""

from __future__ import annotations

import pytest

import zuke._run
from zuke import Build, run, target


class App(Build):
    lint = target()


def as_main() -> dict[str, object]:
    """Globals of a build file the interpreter started: where ``exec`` runs ``run``."""
    return {"__name__": "__main__", "run": run, "App": App}


def test_run_hosts_the_build_when_the_engine_started_the_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hosted: list[Build] = []
    monkeypatch.setenv("ZUKE_ENGINE_ADDR", "127.0.0.1:1")
    monkeypatch.setattr(zuke._run, "host", hosted.append)
    exec("run(App)", as_main())
    assert len(hosted) == 1 and isinstance(hosted[0], App)


def test_run_is_a_no_op_when_the_build_file_is_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hosted: list[Build] = []
    monkeypatch.setattr(zuke._run, "host", hosted.append)
    monkeypatch.delenv("ZUKE_ENGINE_ADDR", raising=False)
    run(App)  # This module is not __main__.
    # Nor is it when a command the engine runs for a body imports the file:
    # the engine's variables are inherited, but the file is not the entry.
    monkeypatch.setenv("ZUKE_ENGINE_ADDR", "127.0.0.1:1")
    run(App)
    assert hosted == []


def test_run_by_hand_says_how_a_build_is_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZUKE_ENGINE_ADDR", raising=False)
    monkeypatch.setattr("sys.argv", ["build.py"])
    with pytest.raises(SystemExit) as caught:
        exec("run(App)", as_main())
    assert str(caught.value) == (
        "App: a Zuke build runs through the engine, `./zuke <target>`, "
        "not `python build.py`"
    )
