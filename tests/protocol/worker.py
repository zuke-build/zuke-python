# Copyright (c) 2026 the Zuke contributors
# SPDX-License-Identifier: MIT
"""The worker process the conformance replay starts: the case's twin, hosted.

The replay runs this file with the interpreter running the tests, the real
engine's environment variables, and ``ZUKE_CONFORMANCE_CASE`` naming the case;
``PYTHONPATH`` carries the tests directory so the twin builder imports.
"""

import os

from twins import manifest_of, twin
from zuke import run

run(twin(manifest_of(os.environ["ZUKE_CONFORMANCE_CASE"])))
