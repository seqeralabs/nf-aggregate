#!/usr/bin/env python3
"""Render benchmark report HTML from report_data.json.

This module-local entrypoint is the actual stage CLI used by
`nextflow run modules/local/render_benchmark_report/main.nf`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark_report_render import render_report_from_json


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benchmark_report.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("render-html", help="Render report_data.json to HTML")
    p.add_argument("--data", type=Path, required=True, help="report_data.json path")
    p.add_argument("--output", type=Path, default=Path("benchmark_report.html"), help="Output HTML file")
    p.add_argument("--brand", type=Path, default=None, help="Brand YAML file")
    p.add_argument("--logo", type=Path, default=None, help="SVG logo file")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.command == "render-html":
        render_report_from_json(report_data_path=args.data, output=args.output, brand_path=args.brand, logo_path=args.logo)
        print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
