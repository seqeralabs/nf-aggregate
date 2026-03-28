#!/usr/bin/env python3
"""Generate benchmark report matching the Quarto/R reference, using Python + DuckDB + eCharts."""

import json
from pathlib import Path
from datetime import datetime

import duckdb
import typer
from jinja2 import Environment, BaseLoader


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


def load_run_dumps(dump_dir: Path) -> list[dict]:
    """Load unpacked `tw runs dump` directories into the report data model."""
    runs = []
    for run_dir in sorted(path for path in dump_dir.iterdir() if path.is_dir()):
        workflow_path = run_dir / "workflow.json"
        tasks_path = run_dir / "workflow-tasks.json"
        metrics_path = run_dir / "workflow-metrics.json"
        progress_path = run_dir / "workflow-load.json"
        launch_path = run_dir / "workflow-launch.json"
        service_info_path = run_dir / "service-info.json"

        if not workflow_path.exists():
            continue

        with workflow_path.open() as f:
            workflow = json.load(f)
        with tasks_path.open() as f:
            tasks = json.load(f) if tasks_path.exists() else []
        with metrics_path.open() as f:
            metrics = json.load(f) if metrics_path.exists() else []
        with progress_path.open() as f:
            progress = json.load(f) if progress_path.exists() else {}
        with launch_path.open() as f:
            launch = json.load(f) if launch_path.exists() else {}
        with service_info_path.open() as f:
            service_info = json.load(f) if service_info_path.exists() else {}

        group = workflow.get("label") or workflow.get("group") or "default"
        if isinstance(workflow.get("labels"), list) and workflow["labels"]:
            group = workflow["labels"][0]

        runs.append(
            {
                "meta": {
                    "id": workflow.get("id", run_dir.name),
                    "group": group,
                    "workspace": workflow.get("workspaceName") or workflow.get("workspace", ""),
                },
                "workflow": workflow,
                "metrics": metrics,
                "tasks": tasks,
                "progress": progress,
                "launch": launch,
                "computeEnv": service_info.get("computeEnv") or service_info.get("computeEnvironment") or {},
            }
        )
    return runs


def _write_tmp_json(rows: list[dict], name: str) -> str:
    import tempfile, os
    path = os.path.join(tempfile.gettempdir(), f"nfagg_{name}.json")
    with open(path, "w") as f:
        json.dump(rows, f)
    return path


def _first_present(mapping: dict | None, *keys: str):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def build_database(runs: list[dict], cur_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Build DuckDB in-memory database from run data."""
    db = duckdb.connect()

    # ── runs table ──
    run_rows = []
    for r in runs:
        wf = r["workflow"]
        progress_payload = r.get("progress", {}) or {}
        prog = progress_payload.get("workflowProgress", progress_payload)
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
            "cpu_efficiency": _first_present(prog, "cpuEfficiency"),
            "memory_efficiency": _first_present(prog, "memoryEfficiency"),
            "cpu_time_ms": _first_present(prog, "cpuTime", "cpuTimeMillis") or 0,
            "read_bytes": _first_present(prog, "readBytes") or 0,
            "write_bytes": _first_present(prog, "writeBytes") or 0,
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
        for t in r.get("tasks", []):
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


def render_report(data: dict, output_path: str) -> None:
    env = Environment(loader=BaseLoader())
    template = env.from_string(REPORT_TEMPLATE)
    html = template.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data_json=json.dumps(data, default=str),
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
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Lucida Grande', 'Helvetica Neue', Helvetica, Arial, sans-serif;
         background: #fff; color: #333; line-height: 1.6; font-size: 14px; }
  .container { max-width: 1200px; margin: 0 auto; padding: 0 15px; }

  .navbar { background: #fff; border-bottom: 3px solid #4256e7; padding: 10px 0; margin-bottom: 30px; }
  .navbar .container { display: flex; align-items: center; justify-content: space-between; }
  .navbar-brand { display: flex; align-items: center; gap: 12px; text-decoration: none; color: #333; }
  .navbar-brand svg { height: 28px; }
  .navbar-right { color: #999; font-size: 13px; }

  .section { margin-bottom: 40px; }
  .section h1 { font-size: 26px; font-weight: 300; color: #333; margin-bottom: 5px;
                 padding-bottom: 8px; border-bottom: 2px solid #eee; }
  .section h2 { font-size: 20px; font-weight: 300; color: #333; margin: 25px 0 8px;
                 padding-bottom: 5px; border-bottom: 1px solid #eee; }
  .section h3 { font-size: 17px; font-weight: 400; color: #333; margin: 20px 0 8px; }
  .section-desc { color: #666; font-size: 13px; margin-bottom: 15px; line-height: 1.5; }
  .section-desc strong { color: #333; }

  .gs-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 20px; }
  .gs-table th { background: #f5f5f5; padding: 6px 10px; text-align: center; font-weight: 600;
                  border-bottom: 2px solid #ddd; white-space: nowrap; }
  .gs-table th:first-child { text-align: left; }
  .gs-table td { padding: 5px 10px; border-bottom: 1px solid #eee; text-align: center; white-space: nowrap; }
  .gs-table td:first-child { text-align: left; font-weight: 600; }
  .gs-table tr:hover td { background: #f9f9f9; }
  .gs-table a { color: #4256e7; text-decoration: none; }

  .chart { width: 100%; height: 400px; margin-bottom: 20px; }
  .chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }

  .info-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .info-table th { background: #f5f5f5; padding: 6px 10px; text-align: left; font-weight: 600;
                    border-bottom: 2px solid #ddd; }
  .info-table td { padding: 5px 10px; border-bottom: 1px solid #eee; }
  .info-table tr:hover td { background: #f9f9f9; }

  .callout { border: 1px solid #ddd; border-radius: 4px; margin-bottom: 15px; }
  .callout-header { background: #f5f5f5; padding: 8px 12px; cursor: pointer; font-size: 13px;
                     font-weight: 600; color: #555; border-bottom: 1px solid #ddd; }
  .callout-header:hover { background: #eee; }
  .callout-body { padding: 12px; display: none; }
  .callout-body.show { display: block; }

  .dl-row { display: flex; gap: 20px; font-size: 13px; margin-bottom: 8px; flex-wrap: wrap; }
  .dl-row dt { font-weight: 600; color: #555; }
  .dl-row dd { color: #333; margin-right: 15px; }

  footer { border-top: 1px solid #eee; padding: 15px 0; margin-top: 40px;
           font-size: 12px; color: #999; text-align: center; }
  footer a { color: #4256e7; text-decoration: none; }

  .side-nav { position: fixed; top: 50px; left: 0; width: 220px; padding: 15px 10px;
              background: #fafafa; border-right: 1px solid #eee; height: calc(100vh - 50px);
              overflow-y: auto; font-size: 12px; z-index: 100; }
  .side-nav a { display: block; padding: 4px 8px; color: #555; text-decoration: none;
                border-left: 3px solid transparent; }
  .side-nav a:hover, .side-nav a.active { color: #4256e7; border-left-color: #4256e7; }
  .side-nav a.l2 { padding-left: 20px; color: #777; font-size: 11px; }
  .side-nav a.l3 { padding-left: 32px; color: #999; font-size: 11px; }
  .main-content { margin-left: 220px; }

  .csv-btn { float: right; font-size: 11px; color: #4256e7; cursor: pointer; border: 1px solid #ddd;
             background: #fff; padding: 2px 10px; border-radius: 3px; text-decoration: none; }
  .csv-btn:hover { background: #f5f5f5; }

  @media (max-width: 900px) {
    .side-nav { display: none; }
    .main-content { margin-left: 0; }
    .chart-row { grid-template-columns: 1fr; }
  }

  .text-muted { color: #999; }
  .group-colors span { display: inline-block; width: 12px; height: 12px; border-radius: 2px;
                        margin-right: 4px; vertical-align: middle; }
</style>
</head>
<body>

<nav class="navbar">
  <div class="container">
    <a class="navbar-brand" href="https://seqera.io">
      <svg viewBox="0 0 120 28" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M18.8 5.6c-1.5-.9-3.4-.9-4.9 0L3.6 12c-1.5.9-2.4 2.5-2.4 4.2v3.1c0 1.7.9 3.3 2.4 4.2l2.5 1.4c1.5.9 3.4.9 4.9 0l10.3-5.9c1.5-.9 2.4-2.5 2.4-4.2v-3.1c0-1.7-.9-3.3-2.4-4.2L18.8 5.6z" fill="#4256E7"/>
        <text x="30" y="21" font-family="Helvetica Neue, sans-serif" font-size="20" fill="#333" font-weight="300">seqera</text>
      </svg>
    </a>
    <div class="navbar-right">Pipeline benchmarking report</div>
  </div>
</nav>

<div class="side-nav" id="side-nav">
  <a href="#benchmark-overview"><strong>1</strong> Benchmark overview</a>
  <a href="#run-overview"><strong>2</strong> Run overview</a>
  <a href="#run-summary" class="l2">2.1 Run summary</a>
  <a href="#run-metrics" class="l2">2.2 Run metrics</a>
  <a href="#process-overview"><strong>3</strong> Process overview</a>
  <a href="#task-overview"><strong>4</strong> Task overview</a>
  <a href="#task-instance-usage" class="l2">4.1 Task instance usage</a>
  <a href="#task-metrics" class="l2">4.2 Task metrics</a>
</div>

<div class="main-content">
<div class="container">

  <p class="text-muted" style="margin-bottom: 25px;">
    Published <strong>{{ generated_at }}</strong>
  </p>

  <!-- ═══ 1. Benchmark overview ═══════════════════════════ -->
  <div class="section" id="benchmark-overview">
    <h1>1 &nbsp; Benchmark overview</h1>
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
    <h1>2 &nbsp; Run overview</h1>
    <p class="section-desc">
      <strong>Summary</strong><br>
      This section provides a high-level overview of the pipeline run metrics.
    </p>

    <h2 id="run-summary">2.1 &nbsp; Run summary</h2>
    <p class="section-desc">Summary of pipeline execution and infrastructure settings.</p>
    <div class="callout">
      <div class="callout-header" onclick="this.nextElementSibling.classList.toggle('show')">
        ▶ Click to display table
      </div>
      <div class="callout-body show" style="overflow-x:auto">
        <table class="gs-table" id="run-summary-table"></table>
      </div>
    </div>

    <h2 id="run-metrics">2.2 &nbsp; Run metrics</h2>
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
    <h1>3 &nbsp; Process overview</h1>
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
    <h1>4 &nbsp; Task overview</h1>
    <p class="section-desc">
      <strong>Summary</strong><br>
      This section provides an overview of task-level metrics for instance usage and runtime metrics.
    </p>

    <h2 id="task-instance-usage">4.1 &nbsp; Task instance usage</h2>
    <p class="section-desc">Number of tasks per instance type, grouped by pipeline run group.</p>
    <div class="chart" id="chart-instance-usage" style="height:500px"></div>

    <h2 id="task-metrics">4.2 &nbsp; Task metrics</h2>
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
const DATA = {{ data_json }};
const COLORS = ['#0DC09D', '#3D95FD', '#F18046', '#D0021B', '#7B61FF', '#50E3C2', '#E85D75', '#4A90D9'];

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
    const bg = groupColor[r.group] || '#ddd';
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
  echarts.init(el).setOption({
    title: { text: title, textStyle: { color: '#333', fontSize: 15, fontWeight: 400 }, left: 'center' },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: opts.formatter || (p => p[0].name + ': ' + (opts.prefix||'') +
        p[0].value.toLocaleString(undefined, {maximumFractionDigits:2}) + (opts.suffix||'')) },
    grid: { left: 250, right: 40, top: 40, bottom: 20 },
    xAxis: { type: 'value', name: opts.xName || '', axisLabel: { color: '#666' },
             nameTextStyle: { color: '#999' }, splitLine: { lineStyle: { color: '#eee' } } },
    yAxis: { type: 'category', data: labels.slice().reverse(),
             axisLabel: { color: '#333', fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false } },
    series: opts.series || [{ type: 'bar', data: values.slice().reverse(), barMaxWidth: 24,
      itemStyle: { color: opts.color || '#4256e7' } }],
    backgroundColor: 'transparent',
  });
}

function hbarStacked(elId, title, labels, seriesDefs) {
  const el = document.getElementById(elId);
  if (!el) return;
  const height = Math.max(250, labels.length * 40 + 80);
  el.style.height = height + 'px';
  echarts.init(el).setOption({
    title: { text: title, textStyle: { color: '#333', fontSize: 15, fontWeight: 400 }, left: 'center' },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0, textStyle: { color: '#666' } },
    grid: { left: 250, right: 40, top: 40, bottom: 40 },
    xAxis: { type: 'value', axisLabel: { color: '#666' }, splitLine: { lineStyle: { color: '#eee' } } },
    yAxis: { type: 'category', data: labels.slice().reverse(),
             axisLabel: { color: '#333', fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false } },
    series: seriesDefs.map(s => ({
      name: s.name, type: 'bar', stack: 'total', barMaxWidth: 24,
      data: s.data.slice().reverse(), itemStyle: { color: s.color },
    })),
    backgroundColor: 'transparent',
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
    { xName: 'Hours', suffix: ' h', color: '#4a90d9' });

  // CPU time
  hbarChart('chart-cpu-time', 'CPU time', labels,
    metrics.map(r => +(r.cpuTime || 0)),
    { xName: 'CPU Hours', suffix: ' h', color: '#7b61ff' });

  // Estimated cost
  hbarChart('chart-est-cost', 'Compute cost', labels,
    metrics.map(r => { const c = costs.find(x => x.run_id === r.run_id); return c ? +c.cost : 0; }),
    { xName: '$', prefix: '$', color: '#f5a623' });

  // Workflow status
  const summaryRuns = DATA.run_summary || [];
  hbarStacked('chart-workflow-status', 'Workflow status', labels, [
    { name: 'Succeeded', data: summaryRuns.map(r => r.succeedCount || 0), color: '#22b573' },
    { name: 'Failed', data: summaryRuns.map(r => r.failedCount || 0), color: '#d0021b' },
  ]);

  // Efficiency
  hbarChart('chart-cpu-eff', 'CPU efficiency', labels,
    metrics.map(r => +(r.cpuEfficiency || 0)), { xName: '%', suffix: '%', color: '#22b573' });
  hbarChart('chart-mem-eff', 'Memory efficiency', labels,
    metrics.map(r => +(r.memoryEfficiency || 0)), { xName: '%', suffix: '%', color: '#50e3c2' });

  // I/O
  hbarChart('chart-read-io', 'Data read', labels,
    metrics.map(r => +(r.readBytes || 0)), { xName: 'GB', suffix: ' GB', color: '#4a90d9' });
  hbarChart('chart-write-io', 'Data written', labels,
    metrics.map(r => +(r.writeBytes || 0)), { xName: 'GB', suffix: ' GB', color: '#e85d75' });
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
      echarts.init(rtEl).setOption({
        title: { text: 'Run time per process', textStyle: { color: '#333', fontSize: 15, fontWeight: 400 }, left: 'center' },
        tooltip: { trigger: 'item',
          formatter: p => {
            if (p.seriesType === 'custom') return '';
            return `<strong>${processes[p.data[1]]}</strong><br>${p.seriesName}: ${p.data[0].toFixed(1)} min`;
          }
        },
        legend: { data: groups, bottom: 0, textStyle: { color: '#666' } },
        grid: { left: 350, right: 40, top: 40, bottom: 40 },
        xAxis: { type: 'value', name: 'Run time (minutes)', axisLabel: { color: '#666' },
                 nameTextStyle: { color: '#999' }, splitLine: { lineStyle: { color: '#eee' } } },
        yAxis: { type: 'category', data: processes,
                 axisLabel: { color: '#333', fontSize: 9, width: 320, overflow: 'truncate' },
                 axisLine: { show: false }, axisTick: { show: false }, inverse: true },
        series: [...series, ...errorSeries],
        backgroundColor: 'transparent',
      });

      echarts.init(costEl).setOption({
        title: { text: 'Total process cost ($)', textStyle: { color: '#333', fontSize: 15, fontWeight: 400 }, left: 'center' },
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        legend: { data: groups, bottom: 0, textStyle: { color: '#666' } },
        grid: { left: 350, right: 40, top: 40, bottom: 40 },
        xAxis: { type: 'value', name: 'Cost ($)', axisLabel: { color: '#666' },
                 nameTextStyle: { color: '#999' }, splitLine: { lineStyle: { color: '#eee' } } },
        yAxis: { type: 'category', data: processes,
                 axisLabel: { color: '#333', fontSize: 9, width: 320, overflow: 'truncate' },
                 axisLine: { show: false }, axisTick: { show: false }, inverse: true },
        series: costSeries,
        backgroundColor: 'transparent',
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

  echarts.init(el).setOption({
    title: { text: 'Instance type usage', textStyle: { color: '#333', fontSize: 15, fontWeight: 400 }, left: 'center' },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: instanceTypes, bottom: 0, textStyle: { color: '#666', fontSize: 10 }, type: 'scroll' },
    grid: { left: 180, right: 40, top: 40, bottom: 60 },
    xAxis: { type: 'value', name: 'Number of tasks', axisLabel: { color: '#666' },
             splitLine: { lineStyle: { color: '#eee' } } },
    yAxis: { type: 'category', data: groups.slice().reverse(),
             axisLabel: { color: '#333', fontSize: 12 }, axisLine: { show: false }, axisTick: { show: false } },
    series: instanceTypes.map(t => ({
      name: t, type: 'bar', stack: 'total', barMaxWidth: 30,
      data: groups.slice().reverse().map(g => {
        const match = usage.find(u => u.group === g && u.machine_type === t);
        return match ? match.count : 0;
      }),
      itemStyle: { color: instanceColors[t] },
    })),
    backgroundColor: 'transparent',
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
    echarts.init(scatterEl).setOption({
      title: { text: 'Task real time vs staging time', textStyle: { color: '#333', fontSize: 15, fontWeight: 400 }, left: 'center' },
      tooltip: { trigger: 'item',
        formatter: p => `<strong>${p.data[3]}</strong><br>Real time: ${p.data[0].toFixed(1)} min<br>Staging: ${p.data[1].toFixed(1)} min<br>Cost: $${p.data[2].toFixed(4)}` },
      legend: { data: groups, textStyle: { color: '#666' }, bottom: 0 },
      grid: { left: 70, right: 40, top: 50, bottom: 60 },
      xAxis: { type: 'value', name: 'Task real time (minutes)', axisLabel: { color: '#666' },
               nameTextStyle: { color: '#999' }, splitLine: { lineStyle: { color: '#eee' } } },
      yAxis: { type: 'value', name: 'Task staging time (minutes)', axisLabel: { color: '#666' },
               nameTextStyle: { color: '#999' }, splitLine: { lineStyle: { color: '#eee' } } },
      series: groups.map((g, i) => ({
        name: g, type: 'scatter', symbolSize: 6,
        data: tasks.filter(t => t.group === g).map(t => [t.realtime_min||0, t.staging_min||0, t.cost||0, t.process_short]),
        itemStyle: { color: groupColor[g] },
      })),
      backgroundColor: 'transparent',
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

    echarts.init(costBoxEl).setOption({
      title: { text: 'Task cost ($) per process', textStyle: { color: '#333', fontSize: 15, fontWeight: 400 }, left: 'center' },
      tooltip: { trigger: 'item' },
      grid: { left: 250, right: 40, top: 40, bottom: 20 },
      yAxis: { type: 'category', data: processes,
               axisLabel: { color: '#333', fontSize: 9, width: 220, overflow: 'truncate' },
               axisLine: { show: false }, axisTick: { show: false }, inverse: true },
      xAxis: { type: 'value', name: 'Cost ($)', axisLabel: { color: '#666' },
               nameTextStyle: { color: '#999' }, splitLine: { lineStyle: { color: '#eee' } } },
      series: [{ type: 'boxplot', data: boxData,
                 itemStyle: { color: '#d9edf7', borderColor: '#4256e7' } }],
      backgroundColor: 'transparent',
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
      if (taskTable.length > 500) html += '<tr><td colspan="'+cols.length+'" style="text-align:center;color:#999">... and '+(taskTable.length-500)+' more rows</td></tr>';
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
    data_dir: Path | None = typer.Option(None, exists=True, help="Directory containing run JSON files"),
    dump_dir: Path | None = typer.Option(None, exists=True, help="Directory containing unpacked run dump folders"),
    costs: Path | None = typer.Option(None, help="AWS CUR parquet file"),
    output: Path = typer.Option(Path("benchmark_report.html"), help="Output HTML file"),
    remove_failed: bool = typer.Option(True, help="Exclude failed tasks from analysis"),
) -> None:
    """Generate a benchmark report from Seqera Platform API data."""
    if dump_dir:
        runs = load_run_dumps(dump_dir)
    elif data_dir:
        runs = load_run_data(data_dir)
    else:
        typer.echo("Provide either --data-dir or --dump-dir", err=True)
        raise typer.Exit(code=1)

    if not runs:
        typer.echo("No run data found", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Loaded {len(runs)} runs")
    db = build_database(runs, str(costs) if costs else None)

    if remove_failed:
        db.execute("DELETE FROM tasks WHERE status != 'COMPLETED' AND status != 'CACHED'")

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

    render_report(data, str(output))
    typer.echo(f"Report written to {output}")


if __name__ == "__main__":
    app()
