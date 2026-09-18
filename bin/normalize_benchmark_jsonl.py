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
    # This is the entry point the Nextflow module actually executes (bin/ is what lands on
    # $PATH), so the GCP flag has to exist here as well as on the typer CLI in
    # benchmark_report.py — otherwise the module's `--gcp-billing-table` would be rejected.
    parser.add_argument("--gcp-billing-table", type=str, default=None, help="Optional GCP billing export table (project.dataset.table)")
    args = parser.parse_args(argv)
    normalize_jsonl(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        costs_parquet=args.costs,
        cost_label_map=args.cost_label_map,
        machines_dir=args.machines_dir,
        gcp_billing_table=args.gcp_billing_table,
    )


if __name__ == "__main__":
    main()
