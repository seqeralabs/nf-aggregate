#!/usr/bin/env python3
"""Thin CLI wrapper for benchmark report pipeline stages."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import typer

app = typer.Typer(add_completion=False)

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_BIN_DIRS = {
    "normalize": REPO_ROOT / "modules" / "local" / "normalize_benchmark_jsonl" / "bin",
    "aggregate": REPO_ROOT / "modules" / "local" / "aggregate_benchmark_report_data" / "bin",
    "render": REPO_ROOT / "modules" / "local" / "render_benchmark_report" / "bin",
}


def _import_from_module_bin(module_name: str, key: str):
    module_bin = MODULE_BIN_DIRS[key]
    if not module_bin.exists():
        raise RuntimeError(f"Module bin directory not found: {module_bin}")
    sys.path.insert(0, str(module_bin))
    try:
        return importlib.import_module(module_name)
    finally:
        try:
            sys.path.remove(str(module_bin))
        except ValueError:
            pass


@app.command("normalize-jsonl")
def normalize_jsonl_cmd(
    data_dir: Path = typer.Option(..., exists=True, help="Directory containing run JSON files"),
    output_dir: Path = typer.Option(Path("jsonl_bundle"), help="Output JSONL bundle directory"),
    costs: Path = typer.Option(None, help="Optional AWS CUR parquet file"),
    machines_dir: Path = typer.Option(None, help="Optional machine metrics CSV directory"),
) -> None:
    """Normalize raw run JSON into runs/tasks/metrics JSONL files."""
    normalize_mod = _import_from_module_bin("benchmark_report_normalize", "normalize")

    normalize_mod.normalize_jsonl(
        data_dir=data_dir,
        output_dir=output_dir,
        costs_parquet=costs,
        machines_dir=machines_dir,
    )


@app.command("aggregate-report-data")
def aggregate_report_data_cmd(
    jsonl_dir: Path = typer.Option(..., exists=True, help="Directory containing JSONL bundle"),
    output: Path = typer.Option(Path("report_data.json"), help="Output report_data.json path"),
) -> None:
    """Aggregate JSONL bundle into report_data.json."""
    aggregate_mod = _import_from_module_bin("benchmark_report_aggregate", "aggregate")

    aggregate_mod.aggregate_report_data(jsonl_dir=jsonl_dir, output=output)
    typer.echo(f"Report data written to {output}")


@app.command("render-html")
def render_html_cmd(
    data: Path = typer.Option(..., exists=True, help="report_data.json path"),
    output: Path = typer.Option(Path("benchmark_report.html"), help="Output HTML file"),
    brand: Path = typer.Option(None, help="Brand YAML file"),
    logo: Path = typer.Option(None, help="SVG logo file"),
) -> None:
    """Render benchmark HTML from report_data.json."""
    render_mod = _import_from_module_bin("benchmark_report_render", "render")

    render_mod.render_report_from_json(report_data_path=data, output=output, brand_path=brand, logo_path=logo)
    typer.echo(f"Report written to {output}")


@app.command()
def report(
    jsonl_dir: Path = typer.Option(..., "--jsonl-dir", exists=True, help="Directory containing JSONL bundle"),
    output: Path = typer.Option(Path("benchmark_report.html"), help="Output HTML file"),
    data_output: Path = typer.Option(Path("report_data.json"), help="Intermediate report_data.json output"),
    brand: Path = typer.Option(None, help="Brand YAML file"),
    logo: Path = typer.Option(None, help="SVG logo file"),
) -> None:
    """Convenience wrapper: aggregate-report-data + render-html."""
    aggregate_mod = _import_from_module_bin("benchmark_report_aggregate", "aggregate")
    render_mod = _import_from_module_bin("benchmark_report_render", "render")

    aggregate_mod.aggregate_report_data(jsonl_dir=jsonl_dir, output=data_output)
    render_mod.render_report_from_json(report_data_path=data_output, output=output, brand_path=brand, logo_path=logo)
    typer.echo(f"Report written to {output}")


@app.command()
def fetch(
    run_ids: list[str] = typer.Option(..., help="Seqera Platform run IDs"),
    workspace: str = typer.Option(..., help="Workspace as org/name"),
    group: str = typer.Option("default", help="Group label for these runs"),
    api_endpoint: str = typer.Option("https://api.cloud.seqera.io", help="Seqera API endpoint"),
    output_dir: Path = typer.Option(Path("json_data"), help="Output directory for JSON files"),
) -> None:
    """Fetch run data from Seqera Platform API and write JSON files."""
    from benchmark_report_fetch import fetch_run_data

    token = os.environ.get("TOWER_ACCESS_TOKEN")
    if not token:
        typer.echo("TOWER_ACCESS_TOKEN environment variable is required", err=True)
        raise typer.Exit(code=1)

    output_dir.mkdir(parents=True, exist_ok=True)

    for run_id in run_ids:
        typer.echo(f"Fetching run {run_id} ...")
        data = fetch_run_data(run_id, workspace, api_endpoint, token)
        data["meta"] = {"id": run_id, "workspace": workspace, "group": group}
        out_file = output_dir / f"{run_id}.json"
        out_file.write_text(json.dumps(data, default=str))
        typer.echo(f"  Written to {out_file}")

    typer.echo(f"Done. {len(run_ids)} run(s) saved to {output_dir}")


if __name__ == "__main__":
    app()
