#!/usr/bin/env python3
"""Aggregate benchmark JSONL datasets into report_data.json.

This module-local entrypoint is the actual stage CLI used by
`nextflow run modules/local/aggregate_benchmark_report_data/main.nf`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _add_repo_bin_to_path() -> None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "bin" / "benchmark_report_aggregate.py"
        if candidate.exists():
            sys.path.insert(0, str(parent / "bin"))
            return
    raise RuntimeError("Unable to locate the repository root for benchmark report helpers")


_add_repo_bin_to_path()

from benchmark_report_aggregate import aggregate_report_data  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benchmark_report.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("aggregate-report-data", help="Aggregate JSONL into report_data.json")
    p.add_argument("--jsonl-dir", type=Path, required=True, help="Directory containing JSONL bundle")
    p.add_argument(
        "--output",
        type=Path,
        default=Path("report_data.json"),
        help="Output report_data.json path",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.command == "aggregate-report-data":
        aggregate_report_data(jsonl_dir=args.jsonl_dir, output=args.output)
        print(f"Report data written to {args.output}")


if __name__ == "__main__":
    main()
