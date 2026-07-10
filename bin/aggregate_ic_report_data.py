#!/usr/bin/env python3
"""Aggregate benchmark JSONL datasets into an Intelligent Compute report_data_ic.json."""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark_report_ic_aggregate import aggregate_ic_report_data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl-dir", type=Path, required=True, help="Directory containing JSONL bundle")
    parser.add_argument("--output", type=Path, default=Path("report_data_ic.json"), help="Output path")
    parser.add_argument("--web-base", type=str, default="https://cloud.seqera.io", help="Seqera web base URL for run links")
    args = parser.parse_args(argv)
    aggregate_ic_report_data(jsonl_dir=args.jsonl_dir, output=args.output, web_base=args.web_base)
    print(f"IC report data written to {args.output}")


if __name__ == "__main__":
    main()
