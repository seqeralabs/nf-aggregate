#!/usr/bin/env python3
"""Normalize raw benchmark run JSON files into JSONL datasets.

This module-local entrypoint is the actual stage CLI used by
`nextflow run modules/local/normalize_benchmark_jsonl/main.nf`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark_report_normalize import normalize_jsonl


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
    p.add_argument("--machines-dir", type=Path, default=None, help="Directory containing machine metrics CSVs")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.command == "normalize-jsonl":
        normalize_jsonl(
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            costs_parquet=args.costs,
            machines_dir=args.machines_dir,
        )


if __name__ == "__main__":
    main()
