#!/usr/bin/env python3
"""Render the Intelligent Compute HTML report from report_data_ic.json."""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark_report_render import render_report_from_json


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="report_data_ic.json path")
    parser.add_argument("--output", type=Path, default=Path("intelligent_compute_report.html"), help="Output HTML file")
    parser.add_argument("--brand", type=Path, default=None, help="Brand YAML file")
    parser.add_argument("--logo", type=Path, default=None, help="SVG logo file")
    args = parser.parse_args(argv)
    template = Path(__file__).resolve().parent / "benchmark_report_ic_template.html"
    render_report_from_json(
        report_data_path=args.data, output=args.output,
        brand_path=args.brand, logo_path=args.logo, template_path=template,
    )
    print(f"IC report written to {args.output}")


if __name__ == "__main__":
    main()
