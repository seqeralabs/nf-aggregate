#!/usr/bin/env python3
"""Unified benchmark CLI: build-db, report, and (future) fetch subcommands.

Consolidates clean_json.py, clean_cur.py, build_tables.py, and render_report.py
into a single Typer application. The DuckDB database file is the universal
interchange format between build-db and report.
"""

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs
from urllib.request import Request, urlopen

import duckdb
import typer
import yaml
from jinja2 import BaseLoader, Environment


def _api_get(url: str, headers: dict[str, str], params: dict[str, str] | None = None) -> dict:
    """Perform a GET request and return parsed JSON. Replaces httpx.get()."""
    if params:
        parsed = urlparse(url)
        existing = parse_qs(parsed.query)
        existing.update({k: [v] for k, v in params.items()})
        flat = {k: v[0] for k, v in existing.items()}
        url = urlunparse(parsed._replace(query=urlencode(flat)))
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read())

app = typer.Typer(add_completion=False)


# ── JSON normalization (from clean_json.py) ─────────────────────────────────


def _run_group(run: dict) -> str:
    """Return the benchmark group for a run."""
    return run["meta"]["group"]


def _run_workflow(run: dict) -> dict:
    """Return the workflow payload for a run."""
    return run["workflow"]


def _task_payload(task_raw: dict) -> dict:
    """Unwrap nested task payloads returned by the API."""
    if isinstance(task_raw, dict) and "task" in task_raw:
        return task_raw["task"]
    return task_raw


def _compute_progress_from_tasks(run: dict) -> dict:
    """Compute workflowProgress metrics from task-level data.

    This is a fallback for runs where the Platform did not provide
    aggregate progress (e.g. imported from Nextflow log tarballs).
    """
    tasks = [_task_payload(t) for t in run.get("tasks", [])]
    completed = [t for t in tasks if t.get("status") == "COMPLETED"]
    if not completed:
        return {}

    cpu_time = sum(
        (t.get("cpus") or 0) * (t.get("realtime") or 0) for t in completed
    )
    # cpuLoad = actual CPU usage: pcpu is % of a single core,
    # so pcpu/100 * realtime gives core-milliseconds used.
    cpu_load = sum(
        (t.get("pcpu") or 0) / 100.0 * (t.get("realtime") or 0)
        for t in completed
    )
    mem_rss = sum(t.get("peakRss") or t.get("rss") or 0 for t in completed)
    mem_req = sum(t.get("memory") or 0 for t in completed)
    read_bytes = sum(t.get("readBytes") or 0 for t in completed)
    write_bytes = sum(t.get("writeBytes") or 0 for t in completed)

    return {
        "cpuTime": int(cpu_time),
        "cpuLoad": int(cpu_load),
        "cpuEfficiency": (
            round(cpu_load / cpu_time * 100, 2) if cpu_time else None
        ),
        "memoryRss": mem_rss,
        "memoryReq": mem_req,
        "memoryEfficiency": (
            round(mem_rss / mem_req * 100, 2) if mem_req else None
        ),
        "readBytes": read_bytes,
        "writeBytes": write_bytes,
    }


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
        wf = _run_workflow(r)
        prog = r.get("progress", {}).get("workflowProgress", {})
        if not prog:
            prog = _compute_progress_from_tasks(r)
        stats = wf.get("stats", {})
        launch = r.get("launch", {}) or {}
        ce = r.get("computeEnv", {}) or {}

        fusion_enabled = False
        if wf.get("fusion"):
            fusion_enabled = wf["fusion"].get("enabled", False)

        run_rows.append({
            "run_id": wf["id"],
            "group": _run_group(r),
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
        run_id = _run_workflow(r)["id"]
        group = _run_group(r)
        for t_raw in r.get("tasks", []):
            t = _task_payload(t_raw)
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
        run_id = _run_workflow(r)["id"]
        group = _run_group(r)
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


# ── CUR cost processing (from clean_cur.py) ────────────────────────────────


def _parquet_columns(
    db: duckdb.DuckDBPyConnection,
    cur_path: str,
) -> set[str]:
    """Return the available columns in a parquet file."""
    return {
        row[0]
        for row in db.execute(
            f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{cur_path}'))"
        ).fetchall()
    }


def detect_cur_format(db: duckdb.DuckDBPyConnection, cur_path: str) -> str:
    """Detect CUR format: 'map' (CUR 2.0) or 'flat' (CUR 1.0) or 'unknown'."""
    cur_cols = _parquet_columns(db, cur_path)

    is_map = (
        "resource_tags" in cur_cols
        and "resource_tags_user_unique_run_id" not in cur_cols
    )
    if is_map:
        return "map"

    has_run_id = "resource_tags_user_unique_run_id" in cur_cols
    has_nf_run_id = "resource_tags_user_nf_unique_run_id" in cur_cols
    if has_run_id or has_nf_run_id:
        return "flat"

    return "unknown"


def build_costs_map_format(
    db: duckdb.DuckDBPyConnection, cur_path: str
) -> None:
    """Build costs table from CUR 2.0 MAP format."""
    db.execute(f"""
        CREATE TABLE costs AS
        SELECT
            COALESCE(
                resource_tags['user_unique_run_id'],
                resource_tags['user_nf_unique_run_id']
            ) AS run_id,
            resource_tags['user_pipeline_process'] AS process,
            LEFT(resource_tags['user_task_hash'], 8) AS hash,
            SUM(
                COALESCE(split_line_item_split_cost, line_item_unblended_cost, 0)
                + COALESCE(split_line_item_unused_cost, 0)
            ) AS cost,
            SUM(
                COALESCE(split_line_item_split_cost, line_item_unblended_cost, 0)
            ) AS used_cost,
            SUM(COALESCE(split_line_item_unused_cost, 0)) AS unused_cost,
        FROM read_parquet('{cur_path}')
        WHERE resource_tags['user_unique_run_id'] IS NOT NULL
           OR resource_tags['user_nf_unique_run_id'] IS NOT NULL
        GROUP BY ALL
    """)


def build_costs_flat_format(
    db: duckdb.DuckDBPyConnection, cur_path: str
) -> None:
    """Build costs table from CUR 1.0 flattened format."""
    cur_cols = _parquet_columns(db, cur_path)

    has_nf_run_id = "resource_tags_user_nf_unique_run_id" in cur_cols
    has_run_id = "resource_tags_user_unique_run_id" in cur_cols

    if has_run_id and has_nf_run_id:
        run_id_expr = "COALESCE(resource_tags_user_unique_run_id, resource_tags_user_nf_unique_run_id)"
        where_clause = (
            "resource_tags_user_unique_run_id IS NOT NULL "
            "OR resource_tags_user_nf_unique_run_id IS NOT NULL"
        )
    elif has_run_id:
        run_id_expr = "resource_tags_user_unique_run_id"
        where_clause = "resource_tags_user_unique_run_id IS NOT NULL"
    elif has_nf_run_id:
        run_id_expr = "resource_tags_user_nf_unique_run_id"
        where_clause = "resource_tags_user_nf_unique_run_id IS NOT NULL"
    else:
        typer.echo("No run ID column found in CUR parquet", err=True)
        raise typer.Exit(code=1)

    process_expr = "resource_tags_user_pipeline_process"
    hash_expr = "LEFT(resource_tags_user_task_hash, 8)"

    db.execute(f"""
        CREATE TABLE costs AS
        SELECT
            {run_id_expr} AS run_id,
            {process_expr} AS process,
            {hash_expr} AS hash,
            SUM(
                COALESCE(split_line_item_split_cost, line_item_unblended_cost, 0)
                + COALESCE(split_line_item_unused_cost, 0)
            ) AS cost,
            SUM(
                COALESCE(split_line_item_split_cost, line_item_unblended_cost, 0)
            ) AS used_cost,
            SUM(COALESCE(split_line_item_unused_cost, 0)) AS unused_cost,
        FROM read_parquet('{cur_path}')
        WHERE {where_clause}
        GROUP BY ALL
    """)


# ── DuckDB build (replaces build_and_export) ───────────────────────────────


def build_db(
    data_dir: Path,
    db_path: Path,
    costs_parquet: Path | None = None,
) -> None:
    """Build a persistent DuckDB file from run JSON files and optional CUR parquet."""
    runs = load_run_data(data_dir)
    if not runs:
        typer.echo("No run data found", err=True)
        raise typer.Exit(code=1)

    # Remove any existing db file so we start fresh
    if db_path.exists():
        db_path.unlink()

    db = duckdb.connect(str(db_path))

    # ── runs table ──
    run_rows = extract_runs(runs)
    path = _write_tmp_json(run_rows, "runs")
    db.execute(f"CREATE TABLE runs AS SELECT * FROM read_json_auto('{path}')")

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
                wait_ms = GREATEST(0, COALESCE(
                    EPOCH_MS(CAST(start AS TIMESTAMP)) - EPOCH_MS(CAST(submit AS TIMESTAMP)), 0
                )),
                staging_ms = GREATEST(0, COALESCE(
                    EPOCH_MS(CAST(complete AS TIMESTAMP)) - EPOCH_MS(CAST(start AS TIMESTAMP)) - realtime_ms, 0
                ));
        """)
        # Remove failed tasks (keep COMPLETED + CACHED)
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

    # ── metrics table ──
    metrics_rows = extract_metrics(runs)
    if metrics_rows:
        path = _write_tmp_json(metrics_rows, "metrics")
        db.execute(
            f"CREATE TABLE metrics AS SELECT * FROM read_json_auto('{path}')"
        )

    # ── costs table (optional CUR parquet) ──
    if costs_parquet:
        cur_str = str(costs_parquet)
        fmt = detect_cur_format(db, cur_str)
        if fmt == "map":
            build_costs_map_format(db, cur_str)
        elif fmt == "flat":
            build_costs_flat_format(db, cur_str)
        else:
            typer.echo(
                "Could not detect CUR format — no run ID columns found",
                err=True,
            )

    db.close()
    typer.echo(f"Database written to {db_path}")


# ── Query functions (from build_tables.py) ──────────────────────────────────


def fetch_dicts(db: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    """Execute SQL and return list of dicts."""
    result = db.execute(sql)
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def table_exists(db: duckdb.DuckDBPyConnection, name: str) -> bool:
    tables = [row[0] for row in db.execute("SHOW TABLES").fetchall()]
    return name in tables


def query_benchmark_overview(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Pipeline x group matrix for benchmark overview."""
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
    cost_expr = "COALESCE(t.cost, 0)"
    used_cost_expr = "NULL"
    unused_cost_expr = "NULL"
    cost_join = ""

    if has_cur:
        cost_expr = "COALESCE(c.cost, t.cost, 0)"
        used_cost_expr = "ROUND(SUM(COALESCE(c.used_cost, t.cost, 0)), 2)"
        unused_cost_expr = "ROUND(SUM(COALESCE(c.unused_cost, 0)), 2)"
        cost_join = """
            LEFT JOIN costs c ON t.run_id = c.run_id
                AND LEFT(REPLACE(t.hash, '/', ''), 8) = c.hash
        """

    return fetch_dicts(db, """
        SELECT
            r.run_id,
            r."group",
            ROUND(SUM(""" + cost_expr + """), 2) AS cost,
            """ + used_cost_expr + """ AS used_cost,
            """ + unused_cost_expr + """ AS unused_cost,
        FROM runs r
        LEFT JOIN tasks t ON r.run_id = t.run_id
        """ + cost_join + """
        GROUP BY r.run_id, r."group"
        ORDER BY r."group"
    """)


def query_process_stats(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Per-process mean +/- SD of run time and cost, grouped by group + pipeline."""
    return fetch_dicts(db, """
        SELECT
            "group",
            process AS process_name,
            process_short,
            COUNT(*) AS n_tasks,
            AVG(staging_ms / 60000.0) AS avg_staging_min,
            STDDEV_SAMP(staging_ms / 60000.0) AS sd_staging_min,
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
            ROUND(CAST(memory_bytes AS DOUBLE) / 1e9, 0) AS "Memoryused_GB",
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
            staging_ms / 60000.0 AS staging_min,
            COALESCE(cost, 0) AS cost,
            cpus,
            CAST(memory_bytes AS DOUBLE) / 1e9 AS memory_gb,
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


# ── HTML rendering (from render_report.py) ──────────────────────────────────


def load_brand(brand_path: Path | None = None) -> dict:
    """Load brand.yml and return flat color map with defaults."""
    defaults = {
        "accent": "#065647",
        "accent_light": "#31C9AC",
        "accent_surface": "#E2F7F3",
        "heading": "#201637",
        "border": "#CFD0D1",
        "neutral": "#F7F7F7",
        "white": "#ffffff",
        "palette": [
            "#065647", "#45a1bf", "#201637", "#f4b548",
            "#31C9AC", "#8f3d56", "#85c7c6", "#a5cdee",
            "#d2c6ac", "#46a485",
        ],
    }
    if brand_path and brand_path.exists():
        with brand_path.open() as f:
            raw = yaml.safe_load(f) or {}
        colors = raw.get("colors", {})
        gp = colors.get("green_palette", {})
        ns = colors.get("neutrals", {})
        if h := gp.get("deep_green", {}).get("hex"):
            defaults["accent"] = h
        if h := gp.get("seqera_green", {}).get("hex"):
            defaults["accent_light"] = h
        if h := gp.get("soft_green", {}).get("hex"):
            defaults["accent_surface"] = h
        if h := ns.get("brand_dark", {}).get("hex"):
            defaults["heading"] = h
        if h := ns.get("border_layout", {}).get("hex"):
            defaults["border"] = h
        if h := ns.get("neutral", {}).get("hex"):
            defaults["neutral"] = h
    return defaults


def _load_echarts_theme(theme_path: Path | None = None) -> str:
    """Load eCharts theme JSON string for inline registration."""
    candidates = [
        theme_path,
        Path(__file__).resolve().parent.parent / "assets" / "seqera-echarts-theme.json",
        Path("assets/seqera-echarts-theme.json"),
    ]
    for p in candidates:
        if p and p.exists():
            return p.read_text()
    return "{}"


def render_html(
    data: dict,
    output_path: str,
    brand: dict | None = None,
    logo_svg: str | None = None,
) -> None:
    """Render the HTML report from pre-computed data."""
    brand = brand or load_brand()
    echarts_theme_json = _load_echarts_theme()
    env = Environment(loader=BaseLoader())
    template = env.from_string(REPORT_TEMPLATE)
    html = template.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data_json=json.dumps(data, default=str),
        echarts_theme_json=echarts_theme_json,
        brand_accent=brand["accent"],
        brand_accent_light=brand["accent_light"],
        brand_accent_surface=brand["accent_surface"],
        brand_heading=brand["heading"],
        brand_border=brand["border"],
        brand_neutral=brand["neutral"],
        brand_white=brand["white"],
        brand_palette=brand["palette"],
        logo_svg=logo_svg or "",
        **data,
    )
    Path(output_path).write_text(html)


def render_report(
    db_path: Path,
    output: Path,
    brand_path: Path | None = None,
    logo_path: Path | None = None,
) -> None:
    """Open DuckDB file, run all queries, and render HTML report."""
    db = duckdb.connect(str(db_path), read_only=True)

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

    data = {}
    for name, query_fn in queries.items():
        result = query_fn(db)
        data[name] = result
        count = len(result) if result else 0
        typer.echo(f"  {name}: {count} rows")

    db.close()

    brand_colors = load_brand(brand_path)
    logo_svg = logo_path.read_text() if logo_path and logo_path.exists() else None
    render_html(data, str(output), brand_colors, logo_svg)
    typer.echo(f"Report written to {output}")


# ── Seqera Platform API fetch (mirrors lib/SeqeraApi.groovy) ─────────────────


def resolve_workspace_id(
    workspace: str, api_endpoint: str, headers: dict[str, str]
) -> int:
    """Resolve 'org/workspace' string to numeric workspace ID."""
    org_name, workspace_name = workspace.split("/", 1)

    data = _api_get(f"{api_endpoint}/orgs", headers=headers)
    orgs = data.get("organizations", [])
    org_id = None
    for org in orgs:
        if org["name"] == org_name:
            org_id = org["orgId"]
            break
    if org_id is None:
        raise RuntimeError(f"Organization '{org_name}' not found")

    data = _api_get(f"{api_endpoint}/orgs/{org_id}/workspaces", headers=headers)
    workspaces = data.get("workspaces", [])
    ws_id = None
    for ws in workspaces:
        if ws["name"] == workspace_name:
            ws_id = ws["id"]
            break
    if ws_id is None:
        raise RuntimeError(
            f"Workspace '{workspace_name}' not found in org '{org_name}'"
        )
    return ws_id


def fetch_all_tasks(
    base_url: str, headers: dict[str, str]
) -> list[dict]:
    """Paginate through /tasks endpoint. Returns flat list of all tasks."""
    tasks: list[dict] = []
    offset = 0
    page_size = 100
    while True:
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}max={page_size}&offset={offset}"
        data = _api_get(url, headers=headers)
        page = data.get("tasks", [])
        tasks.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return tasks


def fetch_run_data(
    run_id: str,
    workspace: str,
    api_endpoint: str,
    token: str,
) -> dict:
    """Fetch all data for a single run from Seqera Platform API.

    Returns dict with workflow, metrics, tasks, progress keys.
    """
    headers = {"Authorization": f"Bearer {token}"}
    ws_id = resolve_workspace_id(workspace, api_endpoint, headers)

    workflow_data = _api_get(
        f"{api_endpoint}/workflow/{run_id}",
        headers=headers,
        params={"workspaceId": str(ws_id)},
    )

    metrics_data = _api_get(
        f"{api_endpoint}/workflow/{run_id}/metrics",
        headers=headers,
        params={"workspaceId": str(ws_id)},
    )

    tasks_url = (
        f"{api_endpoint}/workflow/{run_id}/tasks?workspaceId={ws_id}"
    )
    tasks_data = fetch_all_tasks(tasks_url, headers)

    progress_data = _api_get(
        f"{api_endpoint}/workflow/{run_id}/progress",
        headers=headers,
        params={"workspaceId": str(ws_id)},
    )

    return {
        "workflow": workflow_data.get("workflow"),
        "metrics": metrics_data.get("metrics", []),
        "tasks": tasks_data,
        "progress": progress_data.get("progress"),
    }


# ── CLI subcommands ─────────────────────────────────────────────────────────


@app.command("build-db")
def build_db_cmd(
    data_dir: Path = typer.Option(
        ..., exists=True, help="Directory containing run JSON files"
    ),
    output: Path = typer.Option(
        Path("benchmark.duckdb"), help="Output DuckDB file"
    ),
    costs: Path = typer.Option(
        None, help="AWS CUR parquet file for cost analysis"
    ),
) -> None:
    """Build a DuckDB database from run JSON files and optional CUR parquet."""
    build_db(data_dir, output, costs)


@app.command()
def report(
    db: Path = typer.Option(
        ..., exists=True, help="DuckDB database file"
    ),
    output: Path = typer.Option(
        Path("benchmark_report.html"), help="Output HTML file"
    ),
    brand: Path = typer.Option(None, help="Brand YAML file"),
    logo: Path = typer.Option(None, help="SVG logo file"),
) -> None:
    """Render benchmark HTML report from a DuckDB database."""
    render_report(db, output, brand, logo)


@app.command()
def fetch(
    run_ids: list[str] = typer.Option(..., help="Seqera Platform run IDs"),
    workspace: str = typer.Option(..., help="Workspace as org/name"),
    group: str = typer.Option("default", help="Group label for these runs"),
    api_endpoint: str = typer.Option(
        "https://api.cloud.seqera.io", help="Seqera API endpoint"
    ),
    output_dir: Path = typer.Option(
        Path("json_data"), help="Output directory for JSON files"
    ),
) -> None:
    """Fetch run data from Seqera Platform API and write JSON files."""
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


# ── eCharts HTML Template ──────────────────────────────────────────────────

def _load_report_template() -> str:
    """Load the HTML report template from the sibling file."""
    template_path = Path(__file__).resolve().parent / "benchmark_report_template.html"
    if template_path.exists():
        return template_path.read_text()
    raise FileNotFoundError(f"Report template not found at {template_path}")


REPORT_TEMPLATE = _load_report_template()


# Keep unused marker so tests can verify the template loaded
_TEMPLATE_LOADED = True


if __name__ == "__main__":
    app()
