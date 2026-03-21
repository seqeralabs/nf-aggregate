#!/usr/bin/env python3
"""Generate benchmark report matching the Quarto/R reference, using Python + DuckDB + eCharts."""

import json
import sys
from pathlib import Path
from datetime import datetime

import duckdb
import typer
import yaml
from jinja2 import Environment, BaseLoader


def load_brand(brand_path: Path | None = None) -> dict:
    """Load brand.yml and return flat color map with defaults."""
    defaults = {
        "accent": "#087F68",
        "accent_light": "#31C9AC",
        "accent_surface": "#E2F7F3",
        "heading": "#201637",
        "border": "#CFD0D1",
        "neutral": "#F7F7F7",
        "white": "#ffffff",
        "palette": [
            "#31C9AC", "#087F68", "#201637", "#0BB392",
            "#055C4B", "#50E3C2", "#CFD0D1", "#8A8B8C",
        ],
    }
    if brand_path and brand_path.exists():
        with brand_path.open() as f:
            raw = yaml.safe_load(f) or {}
        colors = raw.get("colors", {})
        gp = colors.get("green_palette", {})
        ns = colors.get("neutrals", {})
        bs = colors.get("brand_surface", {})
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


def fetch_dicts(db: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    """Execute SQL and return list of dicts (no pandas needed)."""
    result = db.execute(sql)
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def table_exists(db: duckdb.DuckDBPyConnection, name: str) -> bool:
    tables = [row[0] for row in db.execute("SHOW TABLES").fetchall()]
    return name in tables


def load_run_data(data_dir: Path) -> list[dict]:
    runs = []
    for run_file in sorted(data_dir.glob("*.json")):
        with run_file.open() as f:
            runs.append(json.load(f))
    return runs


def _write_tmp_json(rows: list[dict], name: str) -> str:
    import tempfile, os
    path = os.path.join(tempfile.gettempdir(), f"nfagg_{name}.json")
    with open(path, "w") as f:
        json.dump(rows, f)
    return path


def build_database(runs: list[dict], cur_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Build DuckDB in-memory database from run data."""
    db = duckdb.connect()

    # ── runs table ──
    run_rows = []
    for r in runs:
        wf = r["workflow"]
        prog = r.get("progress", {}).get("workflowProgress", {})
        stats = wf.get("stats", {})
        config = wf.get("configProfiles", "")
        launch = r.get("launch", {}) or {}
        ce = r.get("computeEnv", {}) or {}

        fusion_enabled = False
        if wf.get("fusion"):
            fusion_enabled = wf["fusion"].get("enabled", False)

        run_rows.append({
            "run_id": wf["id"],
            "group": r["meta"]["group"],
            "pipeline": (wf.get("projectName") or wf.get("repository", "").split("/")[-1] or "unknown"),
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
            "wave_enabled": bool(wf.get("wave", {}).get("enabled", False)) if wf.get("wave") else False,
            "command_line": wf.get("commandLine", ""),
            "revision": wf.get("revision", ""),
            "container_engine": wf.get("containerEngine", ""),
            "nextflow_version": wf.get("nextflow", {}).get("version", "") if wf.get("nextflow") else "",
            "executor": ce.get("executor", wf.get("executor", "")),
            "region": ce.get("region", ""),
            "pipeline_version": wf.get("revision", ""),
            "platform_version": launch.get("platformVersion", ""),
        })

    path = _write_tmp_json(run_rows, "runs")
    db.execute(f"CREATE TABLE runs AS SELECT * FROM read_json_auto('{path}')")

    # ── tasks table ──
    task_rows = []
    for r in runs:
        run_id = r["workflow"]["id"]
        group = r["meta"]["group"]
        for t_raw in r.get("tasks", []):
            t = t_raw.get("task", t_raw) if isinstance(t_raw, dict) and "task" in t_raw else t_raw
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

    if task_rows:
        path = _write_tmp_json(task_rows, "tasks")
        db.execute(f"CREATE TABLE tasks AS SELECT * FROM read_json_auto('{path}')")
        db.execute("""
            ALTER TABLE tasks ADD COLUMN process_short VARCHAR;
            UPDATE tasks SET process_short = split_part(process, ':', -1);
        """)
        # Add wait_ms and staging_ms derived columns
        db.execute("""
            ALTER TABLE tasks ADD COLUMN wait_ms BIGINT DEFAULT 0;
            ALTER TABLE tasks ADD COLUMN staging_ms BIGINT DEFAULT 0;
            UPDATE tasks SET
                wait_ms = GREATEST(0, COALESCE(duration_ms - realtime_ms, 0)),
                staging_ms = GREATEST(0, COALESCE(duration_ms - realtime_ms - wait_ms, 0));
        """)
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
    metrics_rows = []
    for r in runs:
        run_id = r["workflow"]["id"]
        group = r["meta"]["group"]
        for m in r.get("metrics", []):
            row = {"run_id": run_id, "group": group, "process": m.get("process", "")}
            for field in ["cpu", "mem", "vmem", "time", "reads", "writes", "cpuUsage", "memUsage", "timeUsage"]:
                data = m.get(field, {}) or {}
                for stat in ["mean", "min", "q1", "q2", "q3", "max"]:
                    row[f"{field}_{stat}"] = data.get(stat)
            metrics_rows.append(row)

    if metrics_rows:
        path = _write_tmp_json(metrics_rows, "metrics")
        db.execute(f"CREATE TABLE metrics AS SELECT * FROM read_json_auto('{path}')")

    # ── costs table (optional AWS CUR parquet) ──
    if cur_path and Path(cur_path).exists():
        db.execute(f"""
            CREATE TABLE costs AS
            SELECT
                COALESCE(
                    resource_tags_user_unique_run_id,
                    resource_tags_user_nf_unique_run_id
                ) AS run_id,
                resource_tags_user_pipeline_process AS process,
                LEFT(resource_tags_user_task_hash, 8) AS hash,
                SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost, 0)
                    + COALESCE(split_line_item_unused_cost, 0)) AS cost,
                SUM(COALESCE(split_line_item_split_cost, line_item_unblended_cost, 0)) AS used_cost,
                SUM(COALESCE(split_line_item_unused_cost, 0)) AS unused_cost,
            FROM read_parquet('{cur_path}')
            WHERE resource_tags_user_unique_run_id IS NOT NULL
               OR resource_tags_user_nf_unique_run_id IS NOT NULL
            GROUP BY ALL
        """)

    return db


# ── Query functions matching old report sections ──────────────────────────────

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
            LEFT JOIN costs c ON t.run_id = c.run_id AND LEFT(t.hash, 8) = c.hash
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
        WHERE status = 'COMPLETED' AND machine_type IS NOT NULL AND machine_type != ''
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
        WHERE status = 'COMPLETED'
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
        WHERE status = 'COMPLETED'
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
        LEFT JOIN costs c ON t.run_id = c.run_id AND LEFT(t.hash, 8) = c.hash
        GROUP BY t."group", t.process_short
        ORDER BY total_cost DESC
    """)


def _load_echarts_theme(theme_path: Path | None = None) -> str:
    """Load eCharts theme JSON. Returns JSON string for inline registration."""
    candidates = [
        theme_path,
        Path(__file__).resolve().parent.parent / "assets" / "seqera-echarts-theme.json",
        Path("assets/seqera-echarts-theme.json"),
    ]
    for p in candidates:
        if p and p.exists():
            return p.read_text()
    return "{}"


def render_report(
    data: dict,
    output_path: str,
    brand: dict | None = None,
    logo_svg: str | None = None,
) -> None:
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


# ── eCharts HTML Template ──────────────────────────────────────────────────────
REPORT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pipeline benchmarking report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Inter', Helvetica, sans-serif;
         background: {{ brand_white }}; color: {{ brand_heading }}; line-height: 1.6; font-size: 14px; }
  .container { max-width: 1200px; margin: 0 auto; padding: 0 15px; }

  .navbar { background: {{ brand_white }}; border-bottom: 3px solid {{ brand_accent }}; padding: 10px 0; margin-bottom: 30px; }
  .navbar .container { display: flex; align-items: center; justify-content: space-between; }
  .navbar-brand { display: flex; align-items: center; gap: 12px; text-decoration: none; color: {{ brand_heading }}; }
  .navbar-brand svg { height: 28px; }
  .navbar-right { color: {{ brand_border }}; font-size: 13px; }

  .section { margin-bottom: 40px; }
  .section h1 { font-size: 26px; font-weight: 600; color: {{ brand_heading }}; margin-bottom: 5px;
                 padding-bottom: 8px; border-bottom: 2px solid {{ brand_border }}; }
  .section h2 { font-size: 20px; font-weight: 500; color: {{ brand_heading }}; margin: 25px 0 8px;
                 padding-bottom: 5px; border-bottom: 1px solid {{ brand_border }}; }
  .section h3 { font-size: 17px; font-weight: 500; color: {{ brand_heading }}; margin: 20px 0 8px; }
  .section-desc { color: {{ brand_accent }}; font-size: 13px; margin-bottom: 15px; line-height: 1.5; }
  .section-desc strong { color: {{ brand_heading }}; }

  .gs-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 20px; }
  .gs-table th { background: {{ brand_neutral }}; padding: 6px 10px; text-align: center; font-weight: 600;
                  border-bottom: 2px solid {{ brand_border }}; white-space: nowrap; }
  .gs-table th:first-child { text-align: left; }
  .gs-table td { padding: 5px 10px; border-bottom: 1px solid {{ brand_border }}; text-align: center; white-space: nowrap; }
  .gs-table td:first-child { text-align: left; font-weight: 600; }
  .gs-table tr:hover td { background: {{ brand_accent_surface }}; }
  .gs-table a { color: {{ brand_accent }}; text-decoration: none; }

  .chart { width: 100%; height: 400px; margin-bottom: 20px; }
  .chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }

  .info-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .info-table th { background: {{ brand_neutral }}; padding: 6px 10px; text-align: left; font-weight: 600;
                    border-bottom: 2px solid {{ brand_border }}; }
  .info-table td { padding: 5px 10px; border-bottom: 1px solid {{ brand_border }}; }
  .info-table tr:hover td { background: {{ brand_accent_surface }}; }

  .callout { border: 1px solid {{ brand_border }}; border-radius: 4px; margin-bottom: 15px; }
  .callout-header { background: {{ brand_neutral }}; padding: 8px 12px; cursor: pointer; font-size: 13px;
                     font-weight: 600; color: {{ brand_heading }}; border-bottom: 1px solid {{ brand_border }}; }
  .callout-header:hover { background: {{ brand_accent_surface }}; }
  .callout-body { padding: 12px; display: none; }
  .callout-body.show { display: block; }

  .dl-row { display: flex; gap: 20px; font-size: 13px; margin-bottom: 8px; flex-wrap: wrap; }
  .dl-row dt { font-weight: 600; color: {{ brand_heading }}; }
  .dl-row dd { color: {{ brand_heading }}; margin-right: 15px; }

  footer { border-top: 1px solid {{ brand_border }}; padding: 15px 0; margin-top: 40px;
           font-size: 12px; color: {{ brand_border }}; text-align: center; }
  footer a { color: {{ brand_accent }}; text-decoration: none; }

  .side-nav { position: fixed; top: 50px; left: 0; width: 220px; padding: 15px 10px;
              background: {{ brand_neutral }}; border-right: 1px solid {{ brand_border }}; height: calc(100vh - 50px);
              overflow-y: auto; font-size: 12px; z-index: 100; }
  .nav-icon { width: 14px; height: 14px; vertical-align: -2px; margin-right: 4px; flex-shrink: 0; }
  .h-icon { width: 24px; height: 24px; vertical-align: -4px; margin-right: 6px; color: {{ brand_accent }}; }
  .h-icon.sm { width: 20px; height: 20px; vertical-align: -3px; margin-right: 5px; }
  .side-nav a { display: flex; align-items: center; padding: 4px 8px; color: {{ brand_heading }}; text-decoration: none;
                border-left: 3px solid transparent; }
  .side-nav a:hover, .side-nav a.active { color: {{ brand_accent }}; border-left-color: {{ brand_accent }}; }
  .side-nav a.l2 { padding-left: 20px; color: {{ brand_accent }}; font-size: 11px; }
  .side-nav a.l3 { padding-left: 32px; color: {{ brand_border }}; font-size: 11px; }
  .main-content { margin-left: 220px; }

  .csv-btn { float: right; font-size: 11px; color: {{ brand_accent }}; cursor: pointer; border: 1px solid {{ brand_border }};
             background: {{ brand_white }}; padding: 2px 10px; border-radius: 3px; text-decoration: none; }
  .csv-btn:hover { background: {{ brand_neutral }}; }

  @media (max-width: 900px) {
    .side-nav { display: none; }
    .main-content { margin-left: 0; }
    .chart-row { grid-template-columns: 1fr; }
  }

  .text-muted { color: {{ brand_border }}; }
  .group-colors span { display: inline-block; width: 12px; height: 12px; border-radius: 2px;
                        margin-right: 4px; vertical-align: middle; }
</style>
</head>
<body>

<nav class="navbar">
  <div class="container">
    <a class="navbar-brand" href="https://seqera.io">
      {% if logo_svg %}{{ logo_svg }}{% else %}<span style="font-size:20px;font-weight:300">seqera</span>{% endif %}
    </a>
    <div class="navbar-right">Pipeline benchmarking report</div>
  </div>
</nav>

<svg xmlns="http://www.w3.org/2000/svg" style="display:none">
  <!-- Benchmark overview: dashboard/grid -->
  <symbol id="ic-benchmark" viewBox="0 0 20 20"><rect x="2" y="2" width="7" height="7" rx="1" fill="currentColor" opacity=".85"/><rect x="11" y="2" width="7" height="7" rx="1" fill="currentColor" opacity=".55"/><rect x="2" y="11" width="7" height="7" rx="1" fill="currentColor" opacity=".55"/><rect x="11" y="11" width="7" height="7" rx="1" fill="currentColor" opacity=".85"/></symbol>
  <!-- Run overview: play/run -->
  <symbol id="ic-run" viewBox="0 0 20 20"><path d="M6 3.5v13l10-6.5z" fill="currentColor"/></symbol>
  <!-- Run summary: list/table -->
  <symbol id="ic-table" viewBox="0 0 20 20"><rect x="3" y="4" width="14" height="2" rx="1" fill="currentColor"/><rect x="3" y="9" width="14" height="2" rx="1" fill="currentColor"/><rect x="3" y="14" width="14" height="2" rx="1" fill="currentColor"/></symbol>
  <!-- Run metrics: bar chart -->
  <symbol id="ic-chart" viewBox="0 0 20 20"><rect x="2" y="10" width="4" height="8" rx="1" fill="currentColor"/><rect x="8" y="5" width="4" height="13" rx="1" fill="currentColor"/><rect x="14" y="2" width="4" height="16" rx="1" fill="currentColor"/></symbol>
  <!-- Process overview: workflow/nodes -->
  <symbol id="ic-process" viewBox="0 0 20 20"><circle cx="5" cy="10" r="3" fill="currentColor"/><circle cx="15" cy="5" r="2.5" fill="currentColor" opacity=".7"/><circle cx="15" cy="15" r="2.5" fill="currentColor" opacity=".7"/><line x1="7.5" y1="9" x2="12.5" y2="5.5" stroke="currentColor" stroke-width="1.5"/><line x1="7.5" y1="11" x2="12.5" y2="14.5" stroke="currentColor" stroke-width="1.5"/></symbol>
  <!-- Task overview: checklist -->
  <symbol id="ic-task" viewBox="0 0 20 20"><rect x="2" y="2" width="16" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M6 10l2.5 2.5L14 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></symbol>
  <!-- Instance usage: server/stack -->
  <symbol id="ic-instance" viewBox="0 0 20 20"><rect x="3" y="2" width="14" height="5" rx="1.5" fill="currentColor"/><rect x="3" y="9" width="14" height="5" rx="1.5" fill="currentColor" opacity=".65"/><circle cx="6" cy="4.5" r="1" fill="#fff"/><circle cx="6" cy="11.5" r="1" fill="#fff"/></symbol>
  <!-- Task metrics: scatter/timing -->
  <symbol id="ic-scatter" viewBox="0 0 20 20"><circle cx="5" cy="14" r="1.8" fill="currentColor"/><circle cx="9" cy="8" r="1.8" fill="currentColor" opacity=".75"/><circle cx="14" cy="11" r="1.8" fill="currentColor" opacity=".6"/><circle cx="16" cy="5" r="1.8" fill="currentColor" opacity=".45"/></symbol>
</svg>

<div class="side-nav" id="side-nav">
  <a href="#benchmark-overview"><svg class="nav-icon"><use href="#ic-benchmark"/></svg> Benchmark overview</a>
  <a href="#run-overview"><svg class="nav-icon"><use href="#ic-run"/></svg> Run overview</a>
  <a href="#run-summary" class="l2"><svg class="nav-icon"><use href="#ic-table"/></svg> Run summary</a>
  <a href="#run-metrics" class="l2"><svg class="nav-icon"><use href="#ic-chart"/></svg> Run metrics</a>
  <a href="#process-overview"><svg class="nav-icon"><use href="#ic-process"/></svg> Process overview</a>
  <a href="#task-overview"><svg class="nav-icon"><use href="#ic-task"/></svg> Task overview</a>
  <a href="#task-instance-usage" class="l2"><svg class="nav-icon"><use href="#ic-instance"/></svg> Instance usage</a>
  <a href="#task-metrics" class="l2"><svg class="nav-icon"><use href="#ic-scatter"/></svg> Task metrics</a>
</div>

<div class="main-content">
<div class="container">

  <p class="text-muted" style="margin-bottom: 25px;">
    Published <strong>{{ generated_at }}</strong>
  </p>

  <!-- ═══ 1. Benchmark overview ═══════════════════════════ -->
  <div class="section" id="benchmark-overview">
    <h1><svg class="h-icon"><use href="#ic-benchmark"/></svg> Benchmark overview</h1>
    <div class="dl-row">
      <dt>Failed task excluded</dt><dd>: Yes</dd>
    </div>
    <p class="section-desc">
      <strong>Summary</strong><br>
      This report summarizes the run, process, task, and, if applicable, cost metrics
      for pipeline executions, which have been split into groups:
      <span id="group-list" class="group-colors"></span>
    </p>
    <div style="overflow-x: auto;">
      <table class="gs-table" id="overview-matrix"></table>
    </div>
  </div>

  <!-- ═══ 2. Run overview ═════════════════════════════════ -->
  <div class="section" id="run-overview">
    <h1><svg class="h-icon"><use href="#ic-run"/></svg> Run overview</h1>
    <p class="section-desc">
      <strong>Summary</strong><br>
      This section provides a high-level overview of the pipeline run metrics.
    </p>

    <h2 id="run-summary"><svg class="h-icon sm"><use href="#ic-table"/></svg> Run summary</h2>
    <p class="section-desc">Summary of pipeline execution and infrastructure settings.</p>
    <div class="callout">
      <div class="callout-header" onclick="this.nextElementSibling.classList.toggle('show')">
        ▶ Click to display table
      </div>
      <div class="callout-body show" style="overflow-x:auto">
        <table class="gs-table" id="run-summary-table"></table>
      </div>
    </div>

    <h2 id="run-metrics"><svg class="h-icon sm"><use href="#ic-chart"/></svg> Run metrics</h2>
    <p class="section-desc">This section provides a visual overview of the pipeline run metrics.</p>
    <div class="callout">
      <div class="callout-header" onclick="this.nextElementSibling.classList.toggle('show')">
        ▶ Click to display table
      </div>
      <div class="callout-body" style="overflow-x:auto">
        <button class="csv-btn" onclick="downloadCSV('run-metrics-table','run_overview.csv')">Download as CSV</button>
        <table class="gs-table" id="run-metrics-table"></table>
      </div>
    </div>

    <!-- Run metrics charts -->
    <div class="chart-row">
      <div class="chart" id="chart-wall-time"></div>
      <div class="chart" id="chart-cpu-time"></div>
    </div>
    <div class="chart-row">
      <div class="chart" id="chart-est-cost"></div>
      <div class="chart" id="chart-workflow-status"></div>
    </div>
    <div class="chart-row">
      <div class="chart" id="chart-cpu-eff"></div>
      <div class="chart" id="chart-mem-eff"></div>
    </div>
    <div class="chart-row">
      <div class="chart" id="chart-read-io"></div>
      <div class="chart" id="chart-write-io"></div>
    </div>
  </div>

  <!-- ═══ 3. Process overview ═════════════════════════════ -->
  <div class="section" id="process-overview">
    <h1><svg class="h-icon"><use href="#ic-process"/></svg> Process overview</h1>
    <p class="section-desc">
      <strong>Summary</strong><br>
      This section provides a comparison of the process-level metrics for each pipeline
      across the groups. The plots show the run time distribution per process.
      Dots represent mean values per process across all tasks.
      Error bars indicate mean ± 1 standard deviation.
      A single point indicates that a single task was executed for the process.
    </p>
    <p class="section-desc">
      <strong>Run time</strong> = Staging time + real time
    </p>
    <div id="process-sections"></div>
  </div>

  <!-- ═══ 4. Task overview ════════════════════════════════ -->
  <div class="section" id="task-overview">
    <h1><svg class="h-icon"><use href="#ic-task"/></svg> Task overview</h1>
    <p class="section-desc">
      <strong>Summary</strong><br>
      This section provides an overview of task-level metrics for instance usage and runtime metrics.
    </p>

    <h2 id="task-instance-usage"><svg class="h-icon sm"><use href="#ic-instance"/></svg> Task instance usage</h2>
    <p class="section-desc">Number of tasks per instance type, grouped by pipeline run group.</p>
    <div class="chart" id="chart-instance-usage" style="height:500px"></div>

    <h2 id="task-metrics"><svg class="h-icon sm"><use href="#ic-scatter"/></svg> Task metrics</h2>
    <p class="section-desc">
      This section provides a comparison between staging and run times for tasks.<br>
      <strong>Wait time</strong>: time from submission to task start.<br>
      <strong>Staging time</strong>: time to stage/unstage before and after execution.<br>
      <strong>Real time</strong>: time to execute the task.
    </p>
    <div id="task-sections"></div>
  </div>

</div>
</div>

<footer>
  <div class="container">
    Generated by <a href="https://github.com/seqeralabs/nf-aggregate">seqeralabs/nf-aggregate</a> &mdash;
    Powered by <a href="https://seqera.io">Seqera</a>
  </div>
</footer>

<script>
// Register Seqera eCharts theme
echarts.registerTheme('seqera', {{ echarts_theme_json }});

const DATA = {{ data_json }};
const COLORS = {{ brand_palette | tojson }};

function fmtDuration(ms) {
  if (ms == null || ms === 0) return '—';
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  if (h > 0) return h + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
  return m + ':' + String(s).padStart(2,'0');
}
function fmtCost(v) { return v != null ? '$' + Number(v).toFixed(2) : '—'; }
function fmtPct(v) { return v != null ? Number(v).toFixed(1) + '%' : '—'; }
function fmtGB(v) { return v != null ? Number(v).toLocaleString() : '—'; }
function fmtHours(v) { return v != null ? Number(v).toFixed(1) : '—'; }

// CSV download helper
function downloadCSV(tableId, filename) {
  const table = document.getElementById(tableId);
  const rows = [...table.querySelectorAll('tr')];
  const csv = rows.map(r => [...r.querySelectorAll('th,td')].map(c => '"'+c.textContent.trim()+'"').join(',')).join('\n');
  const blob = new Blob([csv], {type:'text/csv'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = filename; a.click();
}

// Group colors
const groups = [...new Set((DATA.run_summary||[]).map(r => r.group))];
const groupColor = {};
groups.forEach((g,i) => { groupColor[g] = COLORS[i % COLORS.length]; });

// Group list with colored badges
document.getElementById('group-list').innerHTML = groups.map(g =>
  `<span style="background:${groupColor[g]}"></span>${g}`
).join(' &nbsp; ');

// ── 1. Benchmark overview matrix ─────────────────────
(function() {
  const runs = DATA.benchmark_overview || [];
  const pipelines = [...new Set(runs.map(r => r.pipeline))];
  const table = document.getElementById('overview-matrix');
  let html = '<thead><tr><th style="text-align:left">Pipeline</th>';
  groups.forEach(g => { html += `<th>${g}</th>`; });
  html += '</tr></thead><tbody>';
  pipelines.forEach(p => {
    html += '<tr><td>' + p + '</td>';
    groups.forEach(g => {
      const match = runs.find(r => r.pipeline === p && r.group === g);
      html += '<td>' + (match ? match.run_id : '—') + '</td>';
    });
    html += '</tr>';
  });
  html += '</tbody>';
  table.innerHTML = html;
})();

// ── 2.1 Run summary table ───────────────────────────
(function() {
  const runs = DATA.run_summary || [];
  if (!runs.length) return;
  const cols = [
    ['Pipeline name','pipeline'], ['Group','group'], ['Run ID','run_id'],
    ['User name','username'], ['Pipeline version','Version'],
    ['Nextflow version','Nextflow_version'], ['Platform version','platform_version'],
    ['Tasks succeeded','succeedCount'], ['Tasks failed','failedCount'],
    ['Executor','executor'], ['Region','region'],
    ['Fusion enabled','fusion_enabled'], ['Wave enabled','wave_enabled'],
  ];
  const table = document.getElementById('run-summary-table');
  let html = '<thead><tr>' + cols.map(c => '<th>'+c[0]+'</th>').join('') + '</tr></thead><tbody>';
  runs.forEach((r,i) => {
    const bg = groupColor[r.group] || '{{ brand_border }}';
    html += `<tr style="background:${bg}22">`;
    cols.forEach(c => { html += '<td>' + (r[c[1]] != null ? r[c[1]] : '—') + '</td>'; });
    html += '</tr>';
  });
  html += '</tbody>';
  table.innerHTML = html;
})();

// ── 2.2 Run metrics table ───────────────────────────
(function() {
  const metrics = DATA.run_metrics || [];
  const costs = DATA.run_costs || [];
  if (!metrics.length) return;
  const table = document.getElementById('run-metrics-table');
  const cols = ['Pipeline name','Group','Run ID','Duration','CPU time (hours)',
                'Compute cost ($)','Read (GB)','Write (GB)',
                'CPU efficiency (%)','Memory efficiency (%)',
                'Used cost ($)','Unused cost ($)','Total run time'];
  let html = '<thead><tr>' + cols.map(c => '<th>'+c+'</th>').join('') + '</tr></thead><tbody>';
  metrics.forEach(r => {
    const c = costs.find(x => x.run_id === r.run_id) || {};
    const pipelineRuntimeMs = r.pipeline_runtime || 0;
    const prtH = Math.floor(pipelineRuntimeMs / 3600000);
    const prtM = Math.floor((pipelineRuntimeMs % 3600000) / 60000);
    const prtS = Math.floor((pipelineRuntimeMs % 60000) / 1000);
    const prtFmt = prtH + ':' + String(prtM).padStart(2,'0') + ':' + String(prtS).padStart(2,'0');
    html += '<tr>';
    html += '<td>' + r.pipeline + '</td>';
    html += '<td>' + r.group + '</td>';
    html += '<td>' + r.run_id + '</td>';
    html += '<td>' + fmtDuration(r.duration) + '</td>';
    html += '<td>' + fmtHours(r.cpuTime) + '</td>';
    html += '<td>' + fmtCost(c.cost) + '</td>';
    html += '<td>' + fmtGB(r.readBytes) + '</td>';
    html += '<td>' + fmtGB(r.writeBytes) + '</td>';
    html += '<td>' + fmtPct(r.cpuEfficiency) + '</td>';
    html += '<td>' + fmtPct(r.memoryEfficiency) + '</td>';
    html += '<td>' + fmtCost(c.used_cost) + '</td>';
    html += '<td>' + fmtCost(c.unused_cost) + '</td>';
    html += '<td>' + prtFmt + '</td>';
    html += '</tr>';
  });
  html += '</tbody>';
  table.innerHTML = html;
})();

// ── Chart helpers ────────────────────────────────────
function hbarChart(elId, title, labels, values, opts) {
  opts = opts || {};
  const el = document.getElementById(elId);
  if (!el) return;
  const height = Math.max(250, labels.length * 40 + 80);
  el.style.height = height + 'px';
  echarts.init(el, 'seqera').setOption({
    title: { text: title },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: opts.formatter || (p => p[0].name + ': ' + (opts.prefix||'') +
        p[0].value.toLocaleString(undefined, {maximumFractionDigits:2}) + (opts.suffix||'')) },
    grid: { left: 250, right: 40, top: 40, bottom: 20 },
    xAxis: { type: 'value', name: opts.xName || '' },
    yAxis: { type: 'category', data: labels.slice().reverse(),
             axisLabel: { fontSize: 11 } },
    series: opts.series || [{ type: 'bar', data: values.slice().reverse(), barMaxWidth: 24,
      itemStyle: opts.color ? { color: opts.color } : undefined }],
  });
}

function hbarStacked(elId, title, labels, seriesDefs) {
  const el = document.getElementById(elId);
  if (!el) return;
  const height = Math.max(250, labels.length * 40 + 80);
  el.style.height = height + 'px';
  echarts.init(el, 'seqera').setOption({
    title: { text: title },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0 },
    grid: { left: 250, right: 40, top: 40, bottom: 40 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: labels.slice().reverse(),
             axisLabel: { fontSize: 11 } },
    series: seriesDefs.map(s => ({
      name: s.name, type: 'bar', stack: 'total', barMaxWidth: 24,
      data: s.data.slice().reverse(), itemStyle: { color: s.color },
    })),
  });
}

// ── 2.2 Run metrics charts ──────────────────────────
(function() {
  const metrics = DATA.run_metrics || [];
  const costs = DATA.run_costs || [];
  const labels = metrics.map(r => r.group);

  // Wall time
  hbarChart('chart-wall-time', 'Wall time', labels,
    metrics.map(r => +(r.duration / 3600000).toFixed(2)),
    { xName: 'Hours', suffix: ' h' });

  // CPU time
  hbarChart('chart-cpu-time', 'CPU time', labels,
    metrics.map(r => +(r.cpuTime || 0)),
    { xName: 'CPU Hours', suffix: ' h' });

  // Estimated cost
  hbarChart('chart-est-cost', 'Compute cost', labels,
    metrics.map(r => { const c = costs.find(x => x.run_id === r.run_id); return c ? +c.cost : 0; }),
    { xName: '$', prefix: '$' });

  // Workflow status — explicit colors for semantic meaning
  const summaryRuns = DATA.run_summary || [];
  hbarStacked('chart-workflow-status', 'Workflow status', labels, [
    { name: 'Succeeded', data: summaryRuns.map(r => r.succeedCount || 0), color: COLORS[0] },
    { name: 'Failed', data: summaryRuns.map(r => r.failedCount || 0), color: COLORS[2] },
  ]);

  // Efficiency
  hbarChart('chart-cpu-eff', 'CPU efficiency', labels,
    metrics.map(r => +(r.cpuEfficiency || 0)), { xName: '%', suffix: '%' });
  hbarChart('chart-mem-eff', 'Memory efficiency', labels,
    metrics.map(r => +(r.memoryEfficiency || 0)), { xName: '%', suffix: '%' });

  // I/O
  hbarChart('chart-read-io', 'Data read', labels,
    metrics.map(r => +(r.readBytes || 0)), { xName: 'GB', suffix: ' GB' });
  hbarChart('chart-write-io', 'Data written', labels,
    metrics.map(r => +(r.writeBytes || 0)), { xName: 'GB', suffix: ' GB' });
})();

// ── 3. Process overview (dot + errorbar per group) ───
(function() {
  const stats = DATA.process_stats || [];
  if (!stats.length) return;

  // Group by pipeline (use process_name to extract pipeline prefix)
  const pipelines = [...new Set(stats.map(s => {
    const parts = s.process_name.split(':');
    return parts.length > 1 ? parts[0].replace('NFCORE_','').toLowerCase() : 'default';
  }))];

  const container = document.getElementById('process-sections');

  pipelines.forEach(pipeline => {
    const pipelineStats = stats.filter(s => {
      const parts = s.process_name.split(':');
      const p = parts.length > 1 ? parts[0].replace('NFCORE_','').toLowerCase() : 'default';
      return p === pipeline;
    });

    // Get unique processes sorted by avg runtime desc
    const processes = [...new Set(pipelineStats.map(s => s.process_name))];

    const section = document.createElement('div');
    section.innerHTML = `<h3>${pipeline}</h3>`;

    // Run time dot chart
    const rtEl = document.createElement('div');
    rtEl.className = 'chart';
    rtEl.style.height = Math.max(400, processes.length * 25 + 120) + 'px';
    section.appendChild(rtEl);
    container.appendChild(section);

    const series = groups.map((g, gi) => {
      const gStats = pipelineStats.filter(s => s.group === g);
      return {
        name: g, type: 'scatter', symbolSize: 8,
        itemStyle: { color: groupColor[g] },
        data: processes.map((p, pi) => {
          const s = gStats.find(x => x.process_name === p);
          return s ? [s.avg_runtime_min, pi] : null;
        }).filter(Boolean),
        // error bars via custom rendering
      };
    });

    // Also add error bar series
    const errorSeries = groups.map((g, gi) => {
      const gStats = pipelineStats.filter(s => s.group === g);
      return {
        name: g + ' (±SD)', type: 'custom', silent: true,
        renderItem: function(params, api) {
          const yVal = api.value(1);
          const xVal = api.value(0);
          const sd = api.value(2);
          const point = api.coord([xVal, yVal]);
          const lo = api.coord([Math.max(0, xVal - sd), yVal]);
          const hi = api.coord([xVal + sd, yVal]);
          return { type: 'group', children: [
            { type: 'line', shape: { x1: lo[0], y1: point[1], x2: hi[0], y2: point[1] },
              style: { stroke: groupColor[g], lineWidth: 1.5 } },
            { type: 'line', shape: { x1: lo[0], y1: point[1]-4, x2: lo[0], y2: point[1]+4 },
              style: { stroke: groupColor[g], lineWidth: 1.5 } },
            { type: 'line', shape: { x1: hi[0], y1: point[1]-4, x2: hi[0], y2: point[1]+4 },
              style: { stroke: groupColor[g], lineWidth: 1.5 } },
          ]};
        },
        data: processes.map((p, pi) => {
          const s = gStats.find(x => x.process_name === p);
          return s ? [s.avg_runtime_min, pi, s.sd_runtime_min || 0] : null;
        }).filter(Boolean),
        encode: { x: 0, y: 1 },
        z: -1,
      };
    });

    // Cost chart
    const costEl = document.createElement('div');
    costEl.className = 'chart';
    costEl.style.height = Math.max(400, processes.length * 25 + 120) + 'px';
    section.appendChild(costEl);

    const costSeries = groups.map((g, gi) => {
      const gStats = pipelineStats.filter(s => s.group === g);
      return {
        name: g, type: 'bar', barMaxWidth: 16, stack: g,
        itemStyle: { color: groupColor[g] },
        data: processes.map(p => {
          const s = gStats.find(x => x.process_name === p);
          return s ? +s.total_cost.toFixed(4) : 0;
        }),
      };
    });

    setTimeout(() => {
      echarts.init(rtEl, 'seqera').setOption({
        title: { text: 'Run time per process' },
        tooltip: { trigger: 'item',
          formatter: p => {
            if (p.seriesType === 'custom') return '';
            return `<strong>${processes[p.data[1]]}</strong><br>${p.seriesName}: ${p.data[0].toFixed(1)} min`;
          }
        },
        legend: { data: groups, bottom: 0 },
        grid: { left: 350, right: 40, top: 40, bottom: 40 },
        xAxis: { type: 'value', name: 'Run time (minutes)' },
        yAxis: { type: 'category', data: processes,
                 axisLabel: { fontSize: 9, width: 320, overflow: 'truncate' },
                 inverse: true },
        series: [...series, ...errorSeries],
      });

      echarts.init(costEl, 'seqera').setOption({
        title: { text: 'Total process cost ($)' },
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        legend: { data: groups, bottom: 0 },
        grid: { left: 350, right: 40, top: 40, bottom: 40 },
        xAxis: { type: 'value', name: 'Cost ($)' },
        yAxis: { type: 'category', data: processes,
                 axisLabel: { fontSize: 9, width: 320, overflow: 'truncate' },
                 inverse: true },
        series: costSeries,
      });
    }, 50);
  });
})();

// ── 4.1 Task instance usage (stacked bar) ────────────
(function() {
  const usage = DATA.task_instance_usage || [];
  if (!usage.length) return;
  const instanceTypes = [...new Set(usage.map(u => u.machine_type))];
  const instanceColors = {};
  instanceTypes.forEach((t,i) => { instanceColors[t] = COLORS[i % COLORS.length]; });

  const el = document.getElementById('chart-instance-usage');
  const height = Math.max(300, groups.length * 60 + 100);
  el.style.height = height + 'px';

  echarts.init(el, 'seqera').setOption({
    title: { text: 'Instance type usage' },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: instanceTypes, bottom: 0, fontSize: 10, type: 'scroll' },
    grid: { left: 180, right: 40, top: 40, bottom: 60 },
    xAxis: { type: 'value', name: 'Number of tasks' },
    yAxis: { type: 'category', data: groups.slice().reverse(),
             axisLabel: { fontSize: 12 } },
    series: instanceTypes.map(t => ({
      name: t, type: 'bar', stack: 'total', barMaxWidth: 30,
      data: groups.slice().reverse().map(g => {
        const match = usage.find(u => u.group === g && u.machine_type === t);
        return match ? match.count : 0;
      }),
      itemStyle: { color: instanceColors[t] },
    })),
  });
})();

// ── 4.2 Task metrics (per-pipeline scatter + box + table) ─
(function() {
  const tasks = DATA.task_scatter || [];
  const taskTable = DATA.task_table || [];
  if (!tasks.length) return;

  const container = document.getElementById('task-sections');

  // Realtime vs staging scatter
  const scatterEl = document.createElement('div');
  scatterEl.className = 'chart';
  scatterEl.style.height = '500px';
  container.appendChild(scatterEl);

  setTimeout(() => {
    echarts.init(scatterEl, 'seqera').setOption({
      title: { text: 'Task real time vs staging time' },
      tooltip: { trigger: 'item',
        formatter: p => `<strong>${p.data[3]}</strong><br>Real time: ${p.data[0].toFixed(1)} min<br>Staging: ${p.data[1].toFixed(1)} min<br>Cost: $${p.data[2].toFixed(4)}` },
      legend: { data: groups, bottom: 0 },
      grid: { left: 70, right: 40, top: 50, bottom: 60 },
      xAxis: { type: 'value', name: 'Task real time (minutes)' },
      yAxis: { type: 'value', name: 'Task staging time (minutes)' },
      series: groups.map((g, i) => ({
        name: g, type: 'scatter', symbolSize: 6,
        data: tasks.filter(t => t.group === g).map(t => [t.realtime_min||0, t.staging_min||0, t.cost||0, t.process_short]),
        itemStyle: { color: groupColor[g] },
      })),
      dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 25, height: 20 }],
    });
  }, 100);

  // Task cost box plot
  const costBoxEl = document.createElement('div');
  costBoxEl.className = 'chart';
  costBoxEl.style.height = '500px';
  container.appendChild(costBoxEl);

  setTimeout(() => {
    const processes = [...new Set(tasks.map(t => t.process_short))];
    const boxData = [];
    processes.forEach(p => {
      const costs = groups.map(g => {
        return tasks.filter(t => t.group === g && t.process_short === p).map(t => t.cost || 0);
      });
      // Flatten and compute box stats per process
      const all = costs.flat().sort((a,b) => a-b);
      if (all.length) {
        const q1i = Math.floor(all.length * 0.25);
        const q2i = Math.floor(all.length * 0.5);
        const q3i = Math.floor(all.length * 0.75);
        boxData.push([all[0], all[q1i], all[q2i], all[q3i], all[all.length-1]]);
      } else {
        boxData.push([0,0,0,0,0]);
      }
    });

    echarts.init(costBoxEl, 'seqera').setOption({
      title: { text: 'Task cost ($) per process' },
      tooltip: { trigger: 'item' },
      grid: { left: 250, right: 40, top: 40, bottom: 20 },
      yAxis: { type: 'category', data: processes,
               axisLabel: { fontSize: 9, width: 220, overflow: 'truncate' },
               inverse: true },
      xAxis: { type: 'value', name: 'Cost ($)' },
      series: [{ type: 'boxplot', data: boxData }],
    });
  }, 150);

  // Task data table
  if (taskTable.length) {
    const tableDiv = document.createElement('div');
    tableDiv.innerHTML = `
      <div class="callout" style="margin-top:20px">
        <div class="callout-header" onclick="this.nextElementSibling.classList.toggle('show')">
          ▶ Click to display task table (${taskTable.length} tasks)
        </div>
        <div class="callout-body" style="overflow-x:auto;max-height:600px;overflow-y:auto">
          <button class="csv-btn" onclick="downloadCSV('task-data-table','task_table.csv')">Download as CSV</button>
          <table class="gs-table" id="task-data-table"></table>
        </div>
      </div>`;
    container.appendChild(tableDiv);

    setTimeout(() => {
      const cols = ['Group','Run ID','Taskhash','Task name short','Executor','Cloudzone',
                    'Instance type','Realtime (min)','Cost','CPUs','Memory (GB)',
                    'Pcpu','Pmem','Read bytes','Write bytes','Task name','Status'];
      const keys = ['Group','Run ID','Taskhash','Task name short','Executor','Cloudzone',
                    'Instance type','Realtime_min','Cost','CPUused','Memoryused_GB',
                    'Pcpu','Pmem','Readbytes','Writebytes','Task name','Status'];
      const table = document.getElementById('task-data-table');
      let html = '<thead><tr>' + cols.map(c => '<th>'+c+'</th>').join('') + '</tr></thead><tbody>';
      taskTable.slice(0, 500).forEach(r => {
        html += '<tr>';
        keys.forEach(k => {
          let v = r[k];
          if (k === 'Realtime_min') v = v != null ? Number(v).toFixed(1) : '—';
          else if (k === 'Cost') v = v != null ? '$' + Number(v).toFixed(6) : '—';
          else if (v == null) v = '—';
          html += '<td>' + v + '</td>';
        });
        html += '</tr>';
      });
      if (taskTable.length > 500) html += '<tr><td colspan="'+cols.length+'" style="text-align:center;color:{{ brand_border }}">... and '+(taskTable.length-500)+' more rows</td></tr>';
      html += '</tbody>';
      table.innerHTML = html;
    }, 200);
  }
})();

// Resize
window.addEventListener('resize', () => {
  document.querySelectorAll('.chart').forEach(el => {
    const inst = echarts.getInstanceByDom(el);
    if (inst) inst.resize();
  });
});
</script>
</body>
</html>"""


app = typer.Typer(add_completion=False)


@app.command()
def main(
    data_dir: Path = typer.Option(..., exists=True, help="Directory containing run JSON files"),
    costs: Path | None = typer.Option(None, help="AWS CUR parquet file"),
    output: Path = typer.Option(Path("benchmark_report.html"), help="Output HTML file"),
    remove_failed: bool = typer.Option(True, help="Exclude failed tasks from analysis"),
    brand: Path | None = typer.Option(None, help="Brand YAML file for report colors"),
    logo: Path | None = typer.Option(None, help="SVG logo file for report navbar"),
) -> None:
    """Generate a benchmark report from Seqera Platform API data."""
    runs = load_run_data(data_dir)
    if not runs:
        typer.echo("No run data found", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Loaded {len(runs)} runs")
    db = build_database(runs, str(costs) if costs else None)

    if remove_failed:
        db.execute("DELETE FROM tasks WHERE status != 'COMPLETED' AND status != 'CACHED'")

    brand_colors = load_brand(brand)
    logo_svg = logo.read_text() if logo and logo.exists() else None

    data = {
        "benchmark_overview": query_benchmark_overview(db),
        "run_summary": query_run_summary(db),
        "run_metrics": query_run_metrics(db),
        "run_costs": query_run_costs(db),
        "process_stats": query_process_stats(db),
        "task_instance_usage": query_task_instance_usage(db),
        "task_table": query_task_table(db),
        "task_scatter": query_task_scatter(db),
        "cost_overview": query_cost_overview(db),
    }

    render_report(data, str(output), brand_colors, logo_svg)
    typer.echo(f"Report written to {output}")


if __name__ == "__main__":
    app()
