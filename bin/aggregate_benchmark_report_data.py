#!/usr/bin/env python3
"""Aggregate benchmark JSONL datasets into report_data.json."""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark_report_aggregate import aggregate_report_data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl-dir", type=Path, required=True, help="Directory containing JSONL bundle")
    parser.add_argument("--output", type=Path, default=Path("report_data.json"), help="Output report_data.json path")
    args = parser.parse_args(argv)
    aggregate_report_data(jsonl_dir=args.jsonl_dir, output=args.output)
    print(f"Report data written to {args.output}")


if __name__ == "__main__":
    main()
