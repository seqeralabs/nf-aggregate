#!/usr/bin/env python3
"""Transform raw Seqera API JSON into normalized CSVs using DuckDB.

Reads run JSON files (output of SeqeraApi.fetchRunData()) and produces:
  - runs.csv    — one row per workflow run
  - tasks.csv   — one row per task
  - metrics.csv — one row per process metric field

Cached task support: extracts cachedCount from workflow.stats and keeps
CACHED status tasks alongside COMPLETED ones.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import duckdb
import typer

app = typer.Typer(add_completion=False)


def _write_tmp_json(rows: list[dict], name: str) -> str:
    """Write rows to a temporary JSON file for DuckDB to read."""
    path = os.path.join(tempfile.gettempdir(), f"nfagg_{name}.json")
    with open(path, "w") as f:
        json.dump(rows, f)
    return path


def load_run_data(data_dir: Path) -> list[dict]:
    """Load all run JSON files from a directory."""
    runs = []
    for run_file in sorted(data_dir.glob("*.json")):
        with run_file.open() as f:
            runs.append(json.load(f))
    return runs


def extract_runs(runs: list[dict]) -> list[dict]:
    """Extract run-level metadata from raw API data."""
    run_rows = []
    for r in runs:
        wf = r["workflow"]
        prog = r.get("progress", {}).get("workflowProgress", {})
        stats = wf.get("stats", {})
        launch = r.get("launch", {}) or {}
        ce = r.get("computeEnv", {}) or {}

        fusion_enabled = False
        if wf.get("fusion"):
            fusion_enabled = wf["fusion"].get("enabled", False)

        run_rows.append({
            "run_id": wf["id"],
            "group": r["meta"]["group"],
            "pipeline": (
                wf.get("projectName")
                or wf.get("repository", "").split("/")[-1]
                or "unknown"
            ),
            "run_name": wf.get("runName", ""),
            "username": wf.get("userName", ""),
            "status": wf.get("status", ""),
            "start": wf.get("start"),
            "complete": wf.get("complete"),
            "duration_ms": wf.get("duration", 0),
            "succeeded": stats.get("succeedCount", 0),
            "failed": stats.get("failedCount", 0),
            "cached": stats.get("cachedCount", 0),
            "cpu_efficiency": prog.get("cpuEfficiency"),
            "memory_efficiency": prog.get("memoryEfficiency"),
            "cpu_time_ms": prog.get("cpuTime", 0),
            "read_bytes": prog.get("readBytes", 0),
            "write_bytes": prog.get("writeBytes", 0),
            "fusion_enabled": fusion_enabled,
            "wave_enabled": (
                bool(wf.get("wave", {}).get("enabled", False))
                if wf.get("wave")
                else False
            ),
            "command_line": wf.get("commandLine", ""),
            "revision": wf.get("revision", ""),
            "container_engine": wf.get("containerEngine", ""),
            "nextflow_version": (
                wf.get("nextflow", {}).get("version", "")
                if wf.get("nextflow")
                else ""
            ),
            "executor": ce.get("executor", wf.get("executor", "")),
            "region": ce.get("region", ""),
            "pipeline_version": wf.get("revision", ""),
            "platform_version": launch.get("platformVersion", ""),
        })
    return run_rows


def extract_tasks(runs: list[dict]) -> list[dict]:
    """Extract task-level data from raw API data."""
    task_rows = []
    for r in runs:
        run_id = r["workflow"]["id"]
        group = r["meta"]["group"]
        for t_raw in r.get("tasks", []):
            t = (
                t_raw.get("task", t_raw)
                if isinstance(t_raw, dict) and "task" in t_raw
                else t_raw
            )
            task_rows.append({
                "run_id": run_id,
                "group": group,
                "hash": t.get("hash", ""),
                "name": t.get("name", ""),
                "process": t.get("process", ""),
                "tag": t.get("tag"),
                "status": t.get("status", ""),
                "submit": t.get("submit"),
                "start": t.get("start"),
                "complete": t.get("complete"),
                "duration_ms": t.get("duration", 0),
                "realtime_ms": t.get("realtime", 0),
                "cpus": t.get("cpus", 0),
                "memory_bytes": t.get("memory", 0),
                "pcpu": t.get("pcpu", 0),
                "pmem": t.get("pmem", 0),
                "rss": t.get("rss", 0),
                "peak_rss": t.get("peakRss", 0),
                "read_bytes": t.get("readBytes", 0),
                "write_bytes": t.get("writeBytes", 0),
                "cost": t.get("cost"),
                "executor": t.get("executor", ""),
                "machine_type": t.get("machineType", ""),
                "cloud_zone": t.get("cloudZone", ""),
                "exit_status": t.get("exitStatus"),
                "vol_ctxt": t.get("volCtxt", 0),
                "inv_ctxt": t.get("invCtxt", 0),
            })
    return task_rows


def extract_metrics(runs: list[dict]) -> list[dict]:
    """Extract per-process metrics from raw API data."""
    metrics_rows = []
    for r in runs:
        run_id = r["workflow"]["id"]
        group = r["meta"]["group"]
        for m in r.get("metrics", []):
            row = {
                "run_id": run_id,
                "group": group,
                "process": m.get("process", ""),
            }
            for field in [
                "cpu", "mem", "vmem", "time", "reads", "writes",
                "cpuUsage", "memUsage", "timeUsage",
            ]:
                data = m.get(field, {}) or {}
                for stat in ["mean", "min", "q1", "q2", "q3", "max"]:
                    row[f"{field}_{stat}"] = data.get(stat)
            metrics_rows.append(row)
    return metrics_rows


def build_and_export(
    runs: list[dict],
    output_dir: Path,
    remove_failed: bool = True,
) -> None:
    """Build DuckDB tables and export to CSVs."""
    db = duckdb.connect()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── runs table ──
    run_rows = extract_runs(runs)
    path = _write_tmp_json(run_rows, "runs")
    db.execute(f"CREATE TABLE runs AS SELECT * FROM read_json_auto('{path}')")
    db.execute(f"COPY runs TO '{output_dir}/runs.csv' (HEADER, DELIMITER ',')")

    # ── tasks table ──
    task_rows = extract_tasks(runs)
    if task_rows:
        path = _write_tmp_json(task_rows, "tasks")
        db.execute(f"CREATE TABLE tasks AS SELECT * FROM read_json_auto('{path}')")
        db.execute("""
            ALTER TABLE tasks ADD COLUMN process_short VARCHAR;
            UPDATE tasks SET process_short = split_part(process, ':', -1);
        """)
        db.execute("""
            ALTER TABLE tasks ADD COLUMN wait_ms BIGINT DEFAULT 0;
            ALTER TABLE tasks ADD COLUMN staging_ms BIGINT DEFAULT 0;
            UPDATE tasks SET
                wait_ms = GREATEST(0, COALESCE(duration_ms - realtime_ms, 0)),
                staging_ms = GREATEST(0, COALESCE(duration_ms - realtime_ms - wait_ms, 0));
        """)

        if remove_failed:
            db.execute(
                "DELETE FROM tasks WHERE status != 'COMPLETED' AND status != 'CACHED'"
            )
    else:
        db.execute("""
            CREATE TABLE tasks (
                run_id VARCHAR, "group" VARCHAR, hash VARCHAR, name VARCHAR,
                process VARCHAR, tag VARCHAR, status VARCHAR,
                submit VARCHAR, start VARCHAR, complete VARCHAR,
                duration_ms BIGINT, realtime_ms BIGINT,
                cpus INTEGER, memory_bytes BIGINT, pcpu DOUBLE, pmem DOUBLE,
                rss BIGINT, peak_rss BIGINT, read_bytes BIGINT, write_bytes BIGINT,
                cost DOUBLE, executor VARCHAR, machine_type VARCHAR, cloud_zone VARCHAR,
                exit_status INTEGER, vol_ctxt BIGINT, inv_ctxt BIGINT,
                process_short VARCHAR, wait_ms BIGINT, staging_ms BIGINT
            )
        """)

    db.execute(f"COPY tasks TO '{output_dir}/tasks.csv' (HEADER, DELIMITER ',')")

    # ── metrics table ──
    metrics_rows = extract_metrics(runs)
    if metrics_rows:
        path = _write_tmp_json(metrics_rows, "metrics")
        db.execute(
            f"CREATE TABLE metrics AS SELECT * FROM read_json_auto('{path}')"
        )
        db.execute(
            f"COPY metrics TO '{output_dir}/metrics.csv' (HEADER, DELIMITER ',')"
        )

    db.close()


@app.command()
def main(
    data_dir: Path = typer.Option(
        ..., exists=True, help="Directory containing run JSON files"
    ),
    output_dir: Path = typer.Option(
        Path("cleaned"), help="Output directory for CSVs"
    ),
    remove_failed: bool = typer.Option(
        True, help="Exclude failed tasks (keep COMPLETED + CACHED)"
    ),
) -> None:
    """Clean raw Seqera API JSON into normalized CSVs."""
    runs = load_run_data(data_dir)
    if not runs:
        typer.echo("No run data found", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Loaded {len(runs)} runs")
    build_and_export(runs, output_dir, remove_failed)
    typer.echo(f"CSVs written to {output_dir}/")


if __name__ == "__main__":
    app()
