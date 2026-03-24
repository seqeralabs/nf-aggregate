#!/usr/bin/env python3
"""Build query result CSVs from normalized input CSVs using DuckDB.

Reads: runs.csv, tasks.csv, metrics.csv, and optionally costs.csv
Produces: benchmark_overview.csv, run_summary.csv, run_metrics.csv,
          run_costs.csv, process_stats.csv, task_instance_usage.csv,
          task_table.csv, task_scatter.csv, cost_overview.csv

All output is serialized as JSON (one file per query) for easy consumption
by the HTML renderer.
"""

import json
from pathlib import Path

import duckdb
import typer

app = typer.Typer(add_completion=False)


def fetch_dicts(db: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    """Execute SQL and return list of dicts."""
    result = db.execute(sql)
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def table_exists(db: duckdb.DuckDBPyConnection, name: str) -> bool:
    tables = [row[0] for row in db.execute("SHOW TABLES").fetchall()]
    return name in tables


def load_tables(
    db: duckdb.DuckDBPyConnection,
    runs_csv: Path,
    tasks_csv: Path,
    metrics_csv: Path | None,
    costs_csv: Path | None,
) -> None:
    """Load CSVs into DuckDB tables."""
    db.execute(
        f"CREATE TABLE runs AS SELECT * FROM read_csv_auto('{runs_csv}')"
    )
    db.execute(
        f"CREATE TABLE tasks AS SELECT * FROM read_csv_auto('{tasks_csv}')"
    )
    if metrics_csv and metrics_csv.exists():
        db.execute(
            f"CREATE TABLE metrics AS SELECT * FROM read_csv_auto('{metrics_csv}')"
        )
    if costs_csv and costs_csv.exists():
        db.execute(
            f"CREATE TABLE costs AS SELECT * FROM read_csv_auto('{costs_csv}')"
        )


# ── Query functions ──────────────────────────────────────────────────────────


def query_benchmark_overview(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Pipeline × group matrix for benchmark overview."""
    return fetch_dicts(db, """
        SELECT pipeline, "group", run_id
        FROM runs ORDER BY pipeline, "group"
    """)


def query_run_summary(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Run summary table (infrastructure settings)."""
    return fetch_dicts(db, """
        SELECT
            pipeline, "group", run_id, username,
            pipeline_version AS "Version",
            nextflow_version AS "Nextflow_version",
            platform_version AS "platform_version",
            succeeded AS "succeedCount",
            failed AS "failedCount",
            cached AS "cachedCount",
            executor, region,
            fusion_enabled, wave_enabled,
            container_engine,
        FROM runs
        ORDER BY "group"
    """)


def query_run_metrics(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Run metrics table matching run_overview.csv schema."""
    return fetch_dicts(db, """
        SELECT
            pipeline, "group", run_id,
            CAST(duration_ms AS BIGINT) AS duration,
            ROUND(CAST(cpu_time_ms AS DOUBLE) / 1000.0 / 3600.0, 1) AS "cpuTime",
            CAST(cpu_time_ms AS BIGINT) AS pipeline_runtime,
            ROUND(CAST(cpu_efficiency AS DOUBLE), 0) AS "cpuEfficiency",
            ROUND(CAST(memory_efficiency AS DOUBLE), 2) AS "memoryEfficiency",
            ROUND(CAST(read_bytes AS DOUBLE) / 1e9, 0) AS "readBytes",
            ROUND(CAST(write_bytes AS DOUBLE) / 1e9, 0) AS "writeBytes",
        FROM runs
        ORDER BY "group"
    """)


def query_run_costs(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Per-run cost from task-level sums + optional CUR costs."""
    has_cur = table_exists(db, "costs")
    if has_cur:
        return fetch_dicts(db, """
            SELECT
                r.run_id,
                r."group",
                ROUND(SUM(COALESCE(c.cost, t.cost, 0)), 2) AS cost,
                ROUND(SUM(COALESCE(c.used_cost, t.cost, 0)), 2) AS used_cost,
                ROUND(SUM(COALESCE(c.unused_cost, 0)), 2) AS unused_cost,
            FROM runs r
            LEFT JOIN tasks t ON r.run_id = t.run_id
            LEFT JOIN costs c ON t.run_id = c.run_id
                AND LEFT(REPLACE(t.hash, '/', ''), 8) = c.hash
            GROUP BY r.run_id, r."group"
            ORDER BY r."group"
        """)
    return fetch_dicts(db, """
        SELECT
            r.run_id,
            r."group",
            ROUND(SUM(COALESCE(t.cost, 0)), 2) AS cost,
            NULL AS used_cost,
            NULL AS unused_cost,
        FROM runs r
        LEFT JOIN tasks t ON r.run_id = t.run_id
        GROUP BY r.run_id, r."group"
        ORDER BY r."group"
    """)


def query_process_stats(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Per-process mean ± SD of run time and cost, grouped by group + pipeline."""
    return fetch_dicts(db, """
        SELECT
            "group",
            process AS process_name,
            process_short,
            COUNT(*) AS n_tasks,
            AVG((COALESCE(duration_ms, 0) - realtime_ms) / 60000.0) AS avg_staging_min,
            STDDEV_SAMP((COALESCE(duration_ms, 0) - realtime_ms) / 60000.0) AS sd_staging_min,
            AVG(realtime_ms / 60000.0) AS avg_realtime_min,
            STDDEV_SAMP(realtime_ms / 60000.0) AS sd_realtime_min,
            AVG((COALESCE(duration_ms, 0)) / 60000.0) AS avg_runtime_min,
            STDDEV_SAMP((COALESCE(duration_ms, 0)) / 60000.0) AS sd_runtime_min,
            AVG(COALESCE(cost, 0)) AS avg_cost,
            STDDEV_SAMP(COALESCE(cost, 0)) AS sd_cost,
            SUM(COALESCE(cost, 0)) AS total_cost,
        FROM tasks
        WHERE status = 'COMPLETED'
        GROUP BY "group", process, process_short
        ORDER BY avg_runtime_min DESC
    """)


def query_task_instance_usage(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Instance type counts per group for stacked bar chart."""
    return fetch_dicts(db, """
        SELECT
            "group",
            machine_type,
            COUNT(*) AS count
        FROM tasks
        WHERE status = 'COMPLETED'
            AND machine_type IS NOT NULL AND machine_type != ''
        GROUP BY "group", machine_type
        ORDER BY "group", count DESC
    """)


def query_task_table(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Full task table matching task_table.csv schema."""
    return fetch_dicts(db, """
        SELECT
            "group" AS "Group",
            run_id AS "Run ID",
            LEFT(hash, 9) AS "Taskhash",
            process_short AS "Task name short",
            executor AS "Executor",
            cloud_zone AS "Cloudzone",
            machine_type AS "Instance type",
            realtime_ms / 60000.0 AS "Realtime_min",
            realtime_ms AS "Realtime_ms",
            duration_ms AS "Duration_ms",
            COALESCE(cost, 0) AS "Cost",
            cpus AS "CPUused",
            ROUND(memory_bytes / 1e9, 0) AS "Memoryused_GB",
            pcpu AS "Pcpu",
            pmem AS "Pmem",
            rss AS "Rss",
            read_bytes AS "Readbytes",
            write_bytes AS "Writebytes",
            vol_ctxt AS "VolCtxt",
            inv_ctxt AS "InvCtxt",
            name AS "Task name",
            status AS "Status",
        FROM tasks
        WHERE status IN ('COMPLETED', 'CACHED')
        ORDER BY "group", process_short, name
    """)


def query_task_scatter(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Task scatter data: realtime vs staging time, colored by group."""
    return fetch_dicts(db, """
        SELECT
            run_id,
            "group",
            process_short,
            name,
            realtime_ms / 60000.0 AS realtime_min,
            GREATEST(0, (duration_ms - realtime_ms)) / 60000.0 AS staging_min,
            COALESCE(cost, 0) AS cost,
            cpus,
            memory_bytes / 1e9 AS memory_gb,
        FROM tasks
        WHERE status IN ('COMPLETED', 'CACHED')
        ORDER BY process_short
    """)


def query_cost_overview(db: duckdb.DuckDBPyConnection) -> list[dict] | None:
    """Cost breakdown if AWS CUR data available."""
    if not table_exists(db, "costs"):
        return None
    return fetch_dicts(db, """
        SELECT
            t."group",
            t.process_short,
            SUM(COALESCE(c.cost, t.cost, 0)) AS total_cost,
            SUM(c.used_cost) AS used_cost,
            SUM(c.unused_cost) AS unused_cost,
            COUNT(*) AS n_tasks,
        FROM tasks t
        LEFT JOIN costs c ON t.run_id = c.run_id
            AND LEFT(REPLACE(t.hash, '/', ''), 8) = c.hash
        GROUP BY t."group", t.process_short
        ORDER BY total_cost DESC
    """)


@app.command()
def main(
    runs_csv: Path = typer.Option(..., exists=True, help="Input runs.csv"),
    tasks_csv: Path = typer.Option(..., exists=True, help="Input tasks.csv"),
    metrics_csv: Path = typer.Option(None, help="Input metrics.csv"),
    costs_csv: Path = typer.Option(None, help="Input costs.csv"),
    output_dir: Path = typer.Option(
        Path("tables"), help="Output directory for query result JSON files"
    ),
) -> None:
    """Build query result JSON files from normalized CSVs."""
    db = duckdb.connect()
    output_dir.mkdir(parents=True, exist_ok=True)

    load_tables(db, runs_csv, tasks_csv, metrics_csv, costs_csv)

    queries = {
        "benchmark_overview": query_benchmark_overview,
        "run_summary": query_run_summary,
        "run_metrics": query_run_metrics,
        "run_costs": query_run_costs,
        "process_stats": query_process_stats,
        "task_instance_usage": query_task_instance_usage,
        "task_table": query_task_table,
        "task_scatter": query_task_scatter,
        "cost_overview": query_cost_overview,
    }

    for name, query_fn in queries.items():
        result = query_fn(db)
        out_path = output_dir / f"{name}.json"
        with out_path.open("w") as f:
            json.dump(result, f, default=str)
        count = len(result) if result else 0
        typer.echo(f"  {name}: {count} rows → {out_path}")

    db.close()
    typer.echo(f"All tables written to {output_dir}/")


if __name__ == "__main__":
    app()
