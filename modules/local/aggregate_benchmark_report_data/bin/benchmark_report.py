#!/usr/bin/env python3
"""Module-local shim for direct `nextflow run modules/local/...` execution.

This delegates to the repo-root benchmark_report.py so the shared CLI and
assets/template lookup continue to work from the canonical implementation.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "bin" / "benchmark_report.py"
        if candidate.exists() and candidate != here:
            return parent
    raise RuntimeError(f"Could not locate repo root from {here}")


REPO_ROOT = _find_repo_root()
REPO_BIN = REPO_ROOT / "bin"
sys.path.insert(0, str(REPO_BIN))
sys.argv[0] = str(REPO_BIN / "benchmark_report.py")
runpy.run_path(str(REPO_BIN / "benchmark_report.py"), run_name="__main__")
