#!/usr/bin/env python3
"""Normalize raw benchmark run JSON files into JSONL datasets.

This module-local entrypoint is the actual stage CLI used by
`nextflow run modules/local/normalize_benchmark_jsonl/main.nf`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _add_repo_bin_to_path() -> None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "bin" / "benchmark_report_normalize.py"
        if candidate.exists():
            sys.path.insert(0, str(parent / "bin"))
            return
    raise RuntimeError("Unable to locate the repository root for benchmark report helpers")


_add_repo_bin_to_path()

from benchmark_report_normalize import normalize_jsonl  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benchmark_report.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("normalize-jsonl", help="Normalize raw run JSON into JSONL files")
    p.add_argument("--data-dir", type=Path, required=True, help="Directory containing run JSON files")
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("jsonl_bundle"),
        help="Output JSONL bundle directory",
    )
    p.add_argument("--costs", type=Path, default=None, help="Optional AWS CUR parquet file")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.command == "normalize-jsonl":
        normalize_jsonl(data_dir=args.data_dir, output_dir=args.output_dir, costs_parquet=args.costs)


if __name__ == "__main__":
    main()
