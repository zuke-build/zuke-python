# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""``run``: a worker under the engine, a no-op when imported, a hint by hand."""

from __future__ import annotations

import pytest

import zuke._run
from zuke import Build, run, target


class App(Build):
    lint = target()


def test_run_hosts_the_build_when_the_engine_started_the_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hosted: list[Build] = []
    monkeypatch.setenv("ZUKE_ENGINE_ADDR", "127.0.0.1:1")
    monkeypatch.setattr(zuke._run, "host", hosted.append)
    run(App)
    assert len(hosted) == 1 and isinstance(hosted[0], App)


def test_run_is_a_no_op_when_the_build_file_is_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ZUKE_ENGINE_ADDR", raising=False)
    run(App)  # This module is not __main__.


def test_run_by_hand_says_how_a_build_is_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZUKE_ENGINE_ADDR", raising=False)
    monkeypatch.setattr("sys.argv", ["build.py"])
    with pytest.raises(SystemExit) as caught:
        exec("run(App)", {"__name__": "__main__", "run": run, "App": App})
    assert str(caught.value) == (
        "App: a Zuke build runs through the engine, `./zuke <target>`, "
        "not `python build.py`"
    )
