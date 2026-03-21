#!/usr/bin/env python3
"""Generate benchmark report from Seqera Platform API JSON data using DuckDB + eCharts."""

import json
import sys
from pathlib import Path
from datetime import datetime

import click
import duckdb
from jinja2 import Environment, FileSystemLoader, BaseLoader


def fetch_dicts(db: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    """Execute SQL and return list of dicts (no pandas needed)."""
    result = db.execute(sql)
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def table_exists(db: duckdb.DuckDBPyConnection, name: str) -> bool:
    """Check if a table exists in the database."""
    tables = [row[0] for row in db.execute("SHOW TABLES").fetchall()]
    return name in tables


def load_run_data(data_dir: Path) -> list[dict]:
    """Load all run JSON files from the data directory."""
    runs = []
    for run_file in sorted(data_dir.glob("*.json")):
        with run_file.open() as f:
            runs.append(json.load(f))
    return runs


def build_database(runs: list[dict], cur_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Build DuckDB in-memory database from run data."""
    db = duckdb.connect()

    # -- runs table --
    run_rows = []
    for r in runs:
        wf = r["workflow"]
        prog = r.get("progress", {}).get("workflowProgress", {})
        stats = wf.get("stats", {})
        fusion_enabled = False
        if wf.get("fusion"):
            fusion_enabled = wf["fusion"].get("enabled", False)

        run_rows.append({
            "run_id": wf["id"],
            "group": r["meta"]["group"],
            "pipeline": (wf.get("projectName") or wf.get("repository", "").split("/")[-1] or "unknown"),
            "run_name": wf.get("runName", ""),
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
            "command_line": wf.get("commandLine", ""),
            "revision": wf.get("revision", ""),
            "container_engine": wf.get("containerEngine", ""),
        })

    import tempfile, os
    # DuckDB read_json_auto needs a file path, not a string
    runs_tmp = os.path.join(tempfile.gettempdir(), "nfagg_runs.json")
    with open(runs_tmp, "w") as f:
        json.dump(run_rows, f)
    db.execute(f"CREATE TABLE runs AS SELECT * FROM read_json_auto('{runs_tmp}')")

    # -- tasks table --
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
            })

    if task_rows:
        tasks_tmp = os.path.join(tempfile.gettempdir(), "nfagg_tasks.json")
        with open(tasks_tmp, "w") as f:
            json.dump(task_rows, f)
        db.execute(f"CREATE TABLE tasks AS SELECT * FROM read_json_auto('{tasks_tmp}')")
        # Add derived columns
        db.execute("""
            ALTER TABLE tasks ADD COLUMN process_short VARCHAR;
            UPDATE tasks SET process_short = split_part(process, ':', -1);
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
                exit_status INTEGER, process_short VARCHAR
            )
        """)

    # -- metrics table (per-process box plot stats from /metrics endpoint) --
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
        metrics_tmp = os.path.join(tempfile.gettempdir(), "nfagg_metrics.json")
        with open(metrics_tmp, "w") as f:
            json.dump(metrics_rows, f)
        db.execute(f"CREATE TABLE metrics AS SELECT * FROM read_json_auto('{metrics_tmp}')")

    # -- costs table (optional AWS CUR parquet) --
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


def query_benchmark_overview(db: duckdb.DuckDBPyConnection) -> dict:
    """Grouped summary stats per group for overview charts."""
    return fetch_dicts(db, """
        SELECT
            "group",
            pipeline,
            COUNT(*) AS n_runs,
            AVG(duration_ms) / 1000.0 / 60.0 AS avg_duration_min,
            AVG(cpu_efficiency) AS avg_cpu_efficiency,
            AVG(memory_efficiency) AS avg_memory_efficiency,
            SUM(cpu_time_ms) / 1000.0 / 3600.0 AS total_cpu_hours,
            SUM(read_bytes) / 1e9 AS total_read_gb,
            SUM(write_bytes) / 1e9 AS total_write_gb,
        FROM runs
        GROUP BY "group", pipeline
        ORDER BY "group"
    """)


def query_run_overview(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Per-run summary table."""
    return fetch_dicts(db, """
        SELECT
            run_id,
            "group",
            pipeline,
            run_name,
            status,
            start,
            complete,
            duration_ms / 1000.0 / 60.0 AS duration_min,
            succeeded,
            failed,
            cached,
            ROUND(cpu_efficiency, 1) AS cpu_efficiency,
            ROUND(memory_efficiency, 1) AS memory_efficiency,
            fusion_enabled,
        FROM runs
        ORDER BY "group", start
    """)


def query_process_overview(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Per-process metrics (box plot data from /metrics endpoint)."""
    if not table_exists(db, "metrics"):
        return []
    return fetch_dicts(db, """
        SELECT * FROM metrics
        ORDER BY process
    """)


def query_task_overview(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Task-level data for scatter plots."""
    return fetch_dicts(db, """
        SELECT
            run_id,
            "group",
            process_short,
            name,
            status,
            duration_ms / 1000.0 AS duration_s,
            realtime_ms / 1000.0 AS realtime_s,
            memory_bytes / 1e9 AS memory_gb,
            peak_rss / 1e9 AS peak_rss_gb,
            cpus,
            pcpu,
            cost,
        FROM tasks
        WHERE status = 'COMPLETED'
        ORDER BY process_short, duration_ms DESC
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
    """Render the eCharts HTML report."""
    template_str = REPORT_TEMPLATE
    env = Environment(loader=BaseLoader())
    template = env.from_string(template_str)
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
<title>Seqera Benchmark Report</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  :root {
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3a;
    --text: #e4e4e7; --muted: #71717a; --accent: #6366f1;
    --green: #22c55e; --red: #ef4444; --blue: #3b82f6; --purple: #a855f7;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.6; }
  .container { max-width: 1400px; margin: 0 auto; padding: 2rem; }
  header { border-bottom: 1px solid var(--border); padding-bottom: 1.5rem; margin-bottom: 2rem; }
  header h1 { font-size: 1.75rem; font-weight: 600; }
  header p { color: var(--muted); font-size: 0.875rem; margin-top: 0.25rem; }
  .section { margin-bottom: 3rem; }
  .section h2 { font-size: 1.25rem; font-weight: 600; margin-bottom: 1rem;
                 padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); }
  .chart { width: 100%; height: 400px; background: var(--surface);
           border: 1px solid var(--border); border-radius: 8px; margin-bottom: 1.5rem; }
  .chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
  table { width: 100%; border-collapse: collapse; background: var(--surface);
          border: 1px solid var(--border); border-radius: 8px; overflow: hidden; font-size: 0.8rem; }
  th { background: var(--bg); padding: 0.75rem 1rem; text-align: left;
       font-weight: 600; font-size: 0.75rem; text-transform: uppercase;
       letter-spacing: 0.05em; color: var(--muted); position: sticky; top: 0; }
  td { padding: 0.5rem 1rem; border-top: 1px solid var(--border); }
  tr:hover td { background: rgba(99, 102, 241, 0.05); }
  .badge { display: inline-block; padding: 0.125rem 0.5rem; border-radius: 9999px;
           font-size: 0.7rem; font-weight: 600; }
  .badge-green { background: rgba(34, 197, 94, 0.15); color: var(--green); }
  .badge-red { background: rgba(239, 68, 68, 0.15); color: var(--red); }
  .badge-blue { background: rgba(59, 130, 246, 0.15); color: var(--blue); }
  .table-wrap { max-height: 500px; overflow: auto; border-radius: 8px; }
  @media (max-width: 900px) { .chart-row { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>🧬 Seqera Benchmark Report</h1>
    <p>Generated {{ generated_at }}</p>
  </header>

  <!-- Benchmark Overview -->
  <div class="section">
    <h2>Benchmark Overview</h2>
    <div class="chart-row">
      <div class="chart" id="chart-duration"></div>
      <div class="chart" id="chart-cpu-hours"></div>
    </div>
    <div class="chart-row">
      <div class="chart" id="chart-efficiency"></div>
      <div class="chart" id="chart-io"></div>
    </div>
  </div>

  <!-- Run Overview -->
  <div class="section">
    <h2>Run Overview</h2>
    <div class="table-wrap">
      <table id="run-table">
        <thead><tr>
          <th>Group</th><th>Run</th><th>Pipeline</th><th>Status</th>
          <th>Duration (min)</th><th>Tasks</th><th>CPU Eff%</th><th>Mem Eff%</th><th>Fusion</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <!-- Process Overview -->
  <div class="section">
    <h2>Process Overview</h2>
    <div class="chart-row">
      <div class="chart" id="chart-process-time"></div>
      <div class="chart" id="chart-process-cpu"></div>
    </div>
    <div class="chart-row">
      <div class="chart" id="chart-process-mem"></div>
      <div class="chart" id="chart-process-reads"></div>
    </div>
  </div>

  <!-- Task Overview -->
  <div class="section">
    <h2>Task Overview</h2>
    <div class="chart" id="chart-task-scatter" style="height: 500px;"></div>
  </div>

  <!-- Cost Overview -->
  <div class="section" id="cost-section" style="display: none;">
    <h2>Cost Overview</h2>
    <div class="chart-row">
      <div class="chart" id="chart-cost-process"></div>
      <div class="chart" id="chart-cost-waste"></div>
    </div>
  </div>
</div>

<script>
const DATA = {{ data_json }};
const COLORS = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#3b82f6', '#a855f7', '#ec4899', '#14b8a6'];

// ── Benchmark Overview ────────────────────────────────
(function() {
  const ov = DATA.benchmark_overview || [];
  const groups = [...new Set(ov.map(d => d.group))];
  const pipelines = [...new Set(ov.map(d => d.pipeline))];

  // Duration bar chart
  echarts.init(document.getElementById('chart-duration')).setOption({
    title: { text: 'Avg Wall Time (min)', textStyle: { color: '#e4e4e7', fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: groups, textStyle: { color: '#71717a' }, bottom: 0 },
    xAxis: { type: 'category', data: pipelines, axisLabel: { color: '#71717a' } },
    yAxis: { type: 'value', name: 'Minutes', axisLabel: { color: '#71717a' }, nameTextStyle: { color: '#71717a' } },
    series: groups.map((g, i) => ({
      name: g, type: 'bar',
      data: pipelines.map(p => { const d = ov.find(x => x.group === g && x.pipeline === p); return d ? +d.avg_duration_min.toFixed(1) : 0; }),
      itemStyle: { color: COLORS[i % COLORS.length] },
    })),
    backgroundColor: 'transparent',
  });

  // CPU hours
  echarts.init(document.getElementById('chart-cpu-hours')).setOption({
    title: { text: 'Total CPU Hours', textStyle: { color: '#e4e4e7', fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: groups, textStyle: { color: '#71717a' }, bottom: 0 },
    xAxis: { type: 'category', data: pipelines, axisLabel: { color: '#71717a' } },
    yAxis: { type: 'value', name: 'CPU-hours', axisLabel: { color: '#71717a' }, nameTextStyle: { color: '#71717a' } },
    series: groups.map((g, i) => ({
      name: g, type: 'bar',
      data: pipelines.map(p => { const d = ov.find(x => x.group === g && x.pipeline === p); return d ? +d.total_cpu_hours.toFixed(1) : 0; }),
      itemStyle: { color: COLORS[i % COLORS.length] },
    })),
    backgroundColor: 'transparent',
  });

  // Efficiency
  echarts.init(document.getElementById('chart-efficiency')).setOption({
    title: { text: 'Resource Efficiency (%)', textStyle: { color: '#e4e4e7', fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: groups, textStyle: { color: '#71717a' }, bottom: 0 },
    xAxis: { type: 'category', data: ['CPU Efficiency', 'Memory Efficiency'], axisLabel: { color: '#71717a' } },
    yAxis: { type: 'value', max: 100, axisLabel: { color: '#71717a' } },
    series: groups.map((g, i) => ({
      name: g, type: 'bar',
      data: [
        ov.filter(x => x.group === g).reduce((s, x) => s + (x.avg_cpu_efficiency || 0), 0) / Math.max(ov.filter(x => x.group === g).length, 1),
        ov.filter(x => x.group === g).reduce((s, x) => s + (x.avg_memory_efficiency || 0), 0) / Math.max(ov.filter(x => x.group === g).length, 1),
      ].map(v => +v.toFixed(1)),
      itemStyle: { color: COLORS[i % COLORS.length] },
    })),
    backgroundColor: 'transparent',
  });

  // I/O
  echarts.init(document.getElementById('chart-io')).setOption({
    title: { text: 'Total I/O (GB)', textStyle: { color: '#e4e4e7', fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: groups, textStyle: { color: '#71717a' }, bottom: 0 },
    xAxis: { type: 'category', data: ['Read', 'Write'], axisLabel: { color: '#71717a' } },
    yAxis: { type: 'value', name: 'GB', axisLabel: { color: '#71717a' }, nameTextStyle: { color: '#71717a' } },
    series: groups.map((g, i) => ({
      name: g, type: 'bar',
      data: [
        ov.filter(x => x.group === g).reduce((s, x) => s + (x.total_read_gb || 0), 0),
        ov.filter(x => x.group === g).reduce((s, x) => s + (x.total_write_gb || 0), 0),
      ].map(v => +v.toFixed(1)),
      itemStyle: { color: COLORS[i % COLORS.length] },
    })),
    backgroundColor: 'transparent',
  });
})();

// ── Run Overview Table ────────────────────────────────
(function() {
  const tbody = document.querySelector('#run-table tbody');
  (DATA.run_overview || []).forEach(r => {
    const statusClass = r.status === 'SUCCEEDED' ? 'badge-green' : r.status === 'FAILED' ? 'badge-red' : 'badge-blue';
    const tasks = `${r.succeeded || 0}✓ ${r.failed || 0}✗ ${r.cached || 0}⟳`;
    const fusion = r.fusion_enabled ? '✅' : '—';
    tbody.innerHTML += `<tr>
      <td>${r.group}</td><td>${r.run_name}</td><td>${r.pipeline}</td>
      <td><span class="badge ${statusClass}">${r.status}</span></td>
      <td>${(r.duration_min || 0).toFixed(1)}</td><td>${tasks}</td>
      <td>${r.cpu_efficiency ?? '—'}%</td><td>${r.memory_efficiency ?? '—'}%</td>
      <td>${fusion}</td>
    </tr>`;
  });
})();

// ── Process Overview Box Plots ────────────────────────
(function() {
  const metrics = DATA.process_overview || [];
  if (!metrics.length) return;
  const processes = [...new Set(metrics.map(m => m.process))];

  function boxChart(elId, title, field) {
    const data = processes.map(p => {
      const rows = metrics.filter(m => m.process === p);
      if (!rows.length) return [0, 0, 0, 0, 0];
      const r = rows[0];
      return [r[field+'_min']||0, r[field+'_q1']||0, r[field+'_q2']||0, r[field+'_q3']||0, r[field+'_max']||0];
    });
    echarts.init(document.getElementById(elId)).setOption({
      title: { text: title, textStyle: { color: '#e4e4e7', fontSize: 14 } },
      tooltip: { trigger: 'item' },
      xAxis: { type: 'category', data: processes, axisLabel: { color: '#71717a', rotate: 45, fontSize: 10 } },
      yAxis: { type: 'value', axisLabel: { color: '#71717a' } },
      series: [{ type: 'boxplot', data: data, itemStyle: { color: '#6366f1', borderColor: '#818cf8' } }],
      backgroundColor: 'transparent',
      grid: { bottom: 80 },
    });
  }

  boxChart('chart-process-time', 'Duration per Process', 'time');
  boxChart('chart-process-cpu', 'CPU Usage per Process (%)', 'cpuUsage');
  boxChart('chart-process-mem', 'Memory Usage per Process (%)', 'memUsage');
  boxChart('chart-process-reads', 'Read Bytes per Process', 'reads');
})();

// ── Task Scatter ──────────────────────────────────────
(function() {
  const tasks = DATA.task_overview || [];
  if (!tasks.length) return;
  const groups = [...new Set(tasks.map(t => t.group))];
  echarts.init(document.getElementById('chart-task-scatter')).setOption({
    title: { text: 'Task Duration vs Peak Memory', textStyle: { color: '#e4e4e7', fontSize: 14 } },
    tooltip: { trigger: 'item', formatter: p => `${p.data[3]}<br>Duration: ${p.data[0].toFixed(0)}s<br>Memory: ${p.data[1].toFixed(2)} GB<br>CPUs: ${p.data[2]}` },
    legend: { data: groups, textStyle: { color: '#71717a' }, bottom: 0 },
    xAxis: { type: 'value', name: 'Duration (s)', axisLabel: { color: '#71717a' }, nameTextStyle: { color: '#71717a' } },
    yAxis: { type: 'value', name: 'Peak RSS (GB)', axisLabel: { color: '#71717a' }, nameTextStyle: { color: '#71717a' } },
    series: groups.map((g, i) => ({
      name: g, type: 'scatter', symbolSize: 6,
      data: tasks.filter(t => t.group === g).map(t => [t.realtime_s || 0, t.peak_rss_gb || 0, t.cpus || 1, t.process_short]),
      itemStyle: { color: COLORS[i % COLORS.length] },
    })),
    backgroundColor: 'transparent',
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 30 }],
  });
})();

// ── Cost Overview ─────────────────────────────────────
(function() {
  const costs = DATA.cost_overview;
  if (!costs) return;
  document.getElementById('cost-section').style.display = '';
  const groups = [...new Set(costs.map(c => c.group))];
  const processes = [...new Set(costs.map(c => c.process_short))].sort((a, b) => {
    const ca = costs.filter(c => c.process_short === a).reduce((s, c) => s + (c.total_cost || 0), 0);
    const cb = costs.filter(c => c.process_short === b).reduce((s, c) => s + (c.total_cost || 0), 0);
    return cb - ca;
  });

  echarts.init(document.getElementById('chart-cost-process')).setOption({
    title: { text: 'Cost by Process ($)', textStyle: { color: '#e4e4e7', fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { data: groups, textStyle: { color: '#71717a' }, bottom: 0 },
    xAxis: { type: 'category', data: processes, axisLabel: { color: '#71717a', rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', name: '$', axisLabel: { color: '#71717a' }, nameTextStyle: { color: '#71717a' } },
    series: groups.map((g, i) => ({
      name: g, type: 'bar', stack: 'cost',
      data: processes.map(p => { const d = costs.find(c => c.group === g && c.process_short === p); return d ? +(d.total_cost || 0).toFixed(3) : 0; }),
      itemStyle: { color: COLORS[i % COLORS.length] },
    })),
    backgroundColor: 'transparent',
    grid: { bottom: 80 },
  });

  echarts.init(document.getElementById('chart-cost-waste')).setOption({
    title: { text: 'Used vs Unused Cost ($)', textStyle: { color: '#e4e4e7', fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: processes, axisLabel: { color: '#71717a', rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', name: '$', axisLabel: { color: '#71717a' }, nameTextStyle: { color: '#71717a' } },
    series: [
      { name: 'Used', type: 'bar', stack: 'waste',
        data: processes.map(p => costs.filter(c => c.process_short === p).reduce((s, c) => s + (c.used_cost || 0), 0).toFixed(3)),
        itemStyle: { color: '#22c55e' } },
      { name: 'Unused', type: 'bar', stack: 'waste',
        data: processes.map(p => costs.filter(c => c.process_short === p).reduce((s, c) => s + (c.unused_cost || 0), 0).toFixed(3)),
        itemStyle: { color: '#ef4444' } },
    ],
    legend: { data: ['Used', 'Unused'], textStyle: { color: '#71717a' }, bottom: 0 },
    backgroundColor: 'transparent',
    grid: { bottom: 80 },
  });
})();

// Resize all charts on window resize
window.addEventListener('resize', () => {
  document.querySelectorAll('.chart').forEach(el => {
    const chart = echarts.getInstanceByDom(el);
    if (chart) chart.resize();
  });
});
</script>
</body>
</html>"""


@click.command()
@click.option("--data-dir", type=click.Path(exists=True), required=True, help="Directory containing run JSON files")
@click.option("--costs", type=click.Path(), default=None, help="AWS CUR parquet file")
@click.option("--output", type=click.Path(), default="benchmark_report.html", help="Output HTML file")
@click.option("--remove-failed", is_flag=True, default=True, help="Exclude failed tasks from analysis")
def main(data_dir: str, costs: str | None, output: str, remove_failed: bool):
    """Generate a benchmark report from Seqera Platform API data."""
    runs = load_run_data(Path(data_dir))
    if not runs:
        click.echo("No run data found", err=True)
        sys.exit(1)

    click.echo(f"Loaded {len(runs)} runs")
    db = build_database(runs, costs)

    if remove_failed:
        db.execute("DELETE FROM tasks WHERE status != 'COMPLETED' AND status != 'CACHED'")

    data = {
        "benchmark_overview": query_benchmark_overview(db),
        "run_overview": query_run_overview(db),
        "process_overview": query_process_overview(db),
        "task_overview": query_task_overview(db),
        "cost_overview": query_cost_overview(db),
    }

    render_report(data, output)
    click.echo(f"Report written to {output}")


if __name__ == "__main__":
    main()
