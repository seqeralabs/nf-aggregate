#!/usr/bin/env python3
"""Normalize raw benchmark run JSON files into JSONL datasets."""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark_report_normalize import normalize_jsonl


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True, help="Directory containing run JSON files")
    parser.add_argument("--output-dir", type=Path, default=Path("jsonl_bundle"), help="Output JSONL bundle directory")
    parser.add_argument("--costs", type=Path, default=None, help="Optional AWS CUR parquet file")
    parser.add_argument("--cost-label-map", type=Path, default=None, help="Optional YAML mapping for CUR resource label aliases")
    parser.add_argument("--machines-dir", type=Path, default=None, help="Directory containing machine metrics CSVs")
    args = parser.parse_args(argv)
    normalize_jsonl(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        costs_parquet=args.costs,
        cost_label_map=args.cost_label_map,
        machines_dir=args.machines_dir,
    )


if __name__ == "__main__":
    main()
