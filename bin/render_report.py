#!/usr/bin/env python3
"""Render benchmark HTML report from pre-computed query result JSON files.

This script does NO data processing or DuckDB queries. It strictly:
  1. Loads JSON files produced by build_tables.py
  2. Loads brand/theme assets
  3. Renders a self-contained HTML file with eCharts

Cached task support: the workflow status chart shows succeeded/failed/cached
stacked bars when cachedCount > 0 in run_summary data.
"""

import json
from datetime import datetime
from pathlib import Path

import typer
import yaml
from jinja2 import Environment, BaseLoader

app = typer.Typer(add_completion=False)


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


def load_query_data(tables_dir: Path) -> dict:
    """Load all query result JSON files from tables directory."""
    data = {}
    expected = [
        "benchmark_overview", "run_summary", "run_metrics", "run_costs",
        "process_stats", "task_instance_usage", "task_table", "task_scatter",
        "cost_overview",
    ]
    for name in expected:
        path = tables_dir / f"{name}.json"
        if path.exists():
            with path.open() as f:
                data[name] = json.load(f)
        else:
            data[name] = [] if name != "cost_overview" else None
    return data


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


# ── eCharts HTML Template ──────────────────────────────────────────────────────
REPORT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title> Pipeline benchmarking report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Inter', Helvetica, sans-serif;
         background: {{ brand_white }}; color: {{ brand_heading }}; line-height: 1.6; font-size: 14px; }
  .container { max-width: 1200px; margin: 0 auto; padding: 0 15px; }

  .navbar { background: {{ brand_white }}; border-bottom: 1px solid {{ brand_border }}; padding: 12px 0; margin-bottom: 30px; }
  .navbar .container { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  .navbar-brand { display: flex; align-items: center; gap: 12px; text-decoration: none; color: #000000; }
  .navbar-brand svg { height: 28px; display: block; }
  .navbar-right { color: #000000; font-size: 13px; font-weight: 500; }

  .section { margin-bottom: 40px; }
  .section h1 { font-size: 26px; font-weight: 600; color: {{ brand_heading }}; margin-bottom: 5px;
                 padding-bottom: 8px; border-bottom: 1px solid {{ brand_border }}; }
  .section h2 { font-size: 20px; font-weight: 500; color: {{ brand_heading }}; margin: 25px 0 8px;
                 padding-bottom: 5px; border-bottom: 1px solid {{ brand_border }}; }
  .section h3 { font-size: 17px; font-weight: 500; color: {{ brand_heading }}; margin: 20px 0 8px; }
  .section-desc { color: {{ brand_heading }}; font-size: 13px; margin-bottom: 15px; line-height: 1.5; }
  .section-desc strong { color: {{ brand_heading }}; font-weight: 600; }

  .gs-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 20px; }
  .gs-table th { background: {{ brand_neutral }}; padding: 6px 10px; text-align: center; font-weight: 600;
                  border-bottom: 2px solid {{ brand_border }}; white-space: nowrap; }
  .gs-table th:first-child { text-align: left; }
  .gs-table td { padding: 5px 10px; border-bottom: 1px solid {{ brand_border }}; text-align: center; white-space: nowrap; }
  .gs-table td:first-child { text-align: left; font-weight: 600; }
  .gs-table tr:hover td { background: {{ brand_accent_surface }}; }
  .gs-table a { color: {{ brand_accent }}; text-decoration: none; }

  .chart { width: 100%; height: 400px; margin-bottom: 24px; }
  .chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; margin-bottom: 24px; }

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

  .side-nav { position: fixed; top: 53px; left: 0; width: 228px; padding: 12px 8px;
              background: {{ brand_white }}; border-right: 1px solid {{ brand_border }}; height: calc(100vh - 53px);
              overflow-y: auto; font-size: 12px; z-index: 100; }
  .nav-icon { width: 14px; height: 14px; vertical-align: -2px; margin-right: 6px; flex-shrink: 0; color: #000000; }
  .h-icon { width: 24px; height: 24px; vertical-align: -4px; margin-right: 6px; color: {{ brand_accent }}; }
  .h-icon.sm { width: 20px; height: 20px; vertical-align: -3px; margin-right: 5px; }
  .side-nav a { display: flex; align-items: center; padding: 8px 10px; margin-bottom: 2px; color: #000000; text-decoration: none;
                border-radius: 6px; transition: background 0.15s ease; }
  .side-nav a:hover { background: {{ brand_neutral }}; color: #000000; }
  .side-nav a.active { background: {{ brand_accent_surface }}; color: #000000; font-weight: 600; }
  .side-nav a.l2 { padding-left: 18px; color: #000000; font-size: 11px; }
  .side-nav a.l3 { padding-left: 28px; color: #000000; font-size: 11px; }
  .main-content { margin-left: 228px; }

  .csv-btn { float: right; font-size: 13px; color: {{ brand_accent }}; cursor: pointer; border: 1px solid {{ brand_border }};
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
  <symbol id="ic-benchmark" viewBox="0 0 20 20"><rect x="2" y="2" width="7" height="7" rx="1" fill="currentColor" opacity=".85"/><rect x="11" y="2" width="7" height="7" rx="1" fill="currentColor" opacity=".55"/><rect x="2" y="11" width="7" height="7" rx="1" fill="currentColor" opacity=".55"/><rect x="11" y="11" width="7" height="7" rx="1" fill="currentColor" opacity=".85"/></symbol>
  <symbol id="ic-run" viewBox="0 0 20 20"><path d="M6 3.5v13l10-6.5z" fill="currentColor"/></symbol>
  <symbol id="ic-table" viewBox="0 0 20 20"><rect x="3" y="4" width="14" height="2" rx="1" fill="currentColor"/><rect x="3" y="9" width="14" height="2" rx="1" fill="currentColor"/><rect x="3" y="14" width="14" height="2" rx="1" fill="currentColor"/></symbol>
  <symbol id="ic-chart" viewBox="0 0 20 20"><rect x="2" y="10" width="4" height="8" rx="1" fill="currentColor"/><rect x="8" y="5" width="4" height="13" rx="1" fill="currentColor"/><rect x="14" y="2" width="4" height="16" rx="1" fill="currentColor"/></symbol>
  <symbol id="ic-process" viewBox="0 0 20 20"><circle cx="5" cy="10" r="3" fill="currentColor"/><circle cx="15" cy="5" r="2.5" fill="currentColor" opacity=".7"/><circle cx="15" cy="15" r="2.5" fill="currentColor" opacity=".7"/><line x1="7.5" y1="9" x2="12.5" y2="5.5" stroke="currentColor" stroke-width="1.5"/><line x1="7.5" y1="11" x2="12.5" y2="14.5" stroke="currentColor" stroke-width="1.5"/></symbol>
  <symbol id="ic-task" viewBox="0 0 20 20"><rect x="2" y="2" width="16" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M6 10l2.5 2.5L14 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></symbol>
  <symbol id="ic-instance" viewBox="0 0 20 20"><rect x="3" y="2" width="14" height="5" rx="1.5" fill="currentColor"/><rect x="3" y="9" width="14" height="5" rx="1.5" fill="currentColor" opacity=".65"/><circle cx="6" cy="4.5" r="1" fill="#fff"/><circle cx="6" cy="11.5" r="1" fill="#fff"/></symbol>
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

  <p class="" style="margin-bottom: 25px;">
    Published <strong>{{ generated_at }}</strong>
  </p>

  <!-- 1. Benchmark overview -->
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

  <!-- 2. Run overview -->
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
        &#9654; Click to display table
      </div>
      <div class="callout-body show" style="overflow-x:auto">
        <table class="gs-table" id="run-summary-table"></table>
      </div>
    </div>

    <h2 id="run-metrics"><svg class="h-icon sm"><use href="#ic-chart"/></svg> Run metrics</h2>
    <p class="section-desc">This section provides a visual overview of the pipeline run metrics.</p>
    <div class="callout">
      <div class="callout-header" onclick="this.nextElementSibling.classList.toggle('show')">
        &#9654; Click to display table
      </div>
      <div class="callout-body" style="overflow-x:auto">
        <button class="csv-btn" onclick="downloadCSV('run-metrics-table','run_overview.csv')">Download as CSV</button>
        <table class="gs-table" id="run-metrics-table"></table>
      </div>
    </div>

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

  <!-- 3. Process overview -->
  <div class="section" id="process-overview">
    <h1><svg class="h-icon"><use href="#ic-process"/></svg> Process overview</h1>
    <p class="section-desc">
      <strong>Summary</strong><br>
      This section provides a comparison of the process-level metrics for each pipeline
      across the groups. The plots show the run time distribution per process.
      Dots represent mean values per process across all tasks.
      Error bars indicate mean &plusmn; 1 standard deviation.
      A single point indicates that a single task was executed for the process.
    </p>
    <p class="section-desc">
      <strong>Run time</strong> = Staging time + real time
    </p>
    <div id="process-sections"></div>
  </div>

  <!-- 4. Task overview -->
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
echarts.registerTheme('seqera', {{ echarts_theme_json }});

const DATA = {{ data_json }};
const COLORS = {{ brand_palette | tojson }};

function fmtDuration(ms) {
  if (ms == null || ms === 0) return '\u2014';
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  if (h > 0) return h + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
  return m + ':' + String(s).padStart(2,'0');
}
function fmtCost(v) { return v != null ? '$' + Number(v).toFixed(2) : '\u2014'; }
function fmtPct(v) { return v != null ? Number(v).toFixed(1) + '%' : '\u2014'; }
function fmtGB(v) { return v != null ? Number(v).toLocaleString() : '\u2014'; }
function fmtHours(v) { return v != null ? Number(v).toFixed(1) : '\u2014'; }

function takeaway(labels, values, opts) {
  opts = opts || {};
  if (values.length < 2) return '';
  const pairs = labels.map((l, i) => ({ label: l, value: values[i] })).filter(p => p.value != null);
  if (pairs.length < 2) return '';
  pairs.sort((a, b) => a.value - b.value);
  const lo = pairs[0], hi = pairs[pairs.length - 1];
  if (hi.value === 0) return '';
  const ratio = (hi.value / lo.value).toFixed(1);
  const prefix = opts.prefix || '';
  const suffix = opts.suffix || '';
  if (opts.lowerBetter) {
    return lo.label + ' was ' + ratio + '\u00d7 ' + (opts.adjective || 'lower') + ' (' + prefix + lo.value.toLocaleString(undefined, {maximumFractionDigits: 1}) + suffix + ' vs ' + prefix + hi.value.toLocaleString(undefined, {maximumFractionDigits: 1}) + suffix + ')';
  }
  return hi.label + ' was ' + ratio + '\u00d7 ' + (opts.adjective || 'higher') + ' (' + prefix + hi.value.toLocaleString(undefined, {maximumFractionDigits: 1}) + suffix + ' vs ' + prefix + lo.value.toLocaleString(undefined, {maximumFractionDigits: 1}) + suffix + ')';
}

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

document.getElementById('group-list').innerHTML = groups.map(g =>
  `<span style="background:${groupColor[g]}"></span>${g}`
).join(' &nbsp; ');

// 1. Benchmark overview matrix
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
      html += '<td>' + (match ? match.run_id : '\u2014') + '</td>';
    });
    html += '</tr>';
  });
  html += '</tbody>';
  table.innerHTML = html;
})();

// 2.1 Run summary table (with cached tasks)
(function() {
  const runs = DATA.run_summary || [];
  if (!runs.length) return;
  const cols = [
    ['Pipeline name','pipeline'], ['Group','group'], ['Run ID','run_id'],
    ['User name','username'], ['Pipeline version','Version'],
    ['Nextflow version','Nextflow_version'], ['Platform version','platform_version'],
    ['Tasks succeeded','succeedCount'], ['Tasks failed','failedCount'],
    ['Tasks cached','cachedCount'],
    ['Executor','executor'], ['Region','region'],
    ['Fusion enabled','fusion_enabled'], ['Wave enabled','wave_enabled'],
  ];
  const table = document.getElementById('run-summary-table');
  let html = '<thead><tr>' + cols.map(c => '<th>'+c[0]+'</th>').join('') + '</tr></thead><tbody>';
  runs.forEach((r,i) => {
    const bg = groupColor[r.group] || '{{ brand_border }}';
    html += `<tr style="background:${bg}22">`;
    cols.forEach(c => { html += '<td>' + (r[c[1]] != null ? r[c[1]] : '\u2014') + '</td>'; });
    html += '</tr>';
  });
  html += '</tbody>';
  table.innerHTML = html;
})();

// 2.2 Run metrics table
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

// Chart helpers
function hbarChart(elId, title, labels, values, opts) {
  opts = opts || {};
  const el = document.getElementById(elId);
  if (!el) return;
  const height = Math.max(250, labels.length * 45 + 80);
  el.style.height = height + 'px';
  const seriesArray = opts.series || [{ type: 'bar', data: values.slice().reverse(),
    itemStyle: opts.color ? { color: opts.color, borderRadius: [0, 2, 2, 0] }
                          : { borderRadius: [0, 2, 2, 0] },
    emphasis: { focus: 'series' } }];
  if (seriesArray.length > 1 && seriesArray.length <= 3) {
    seriesArray.forEach(s => {
      s.label = { show: true, position: 'right', formatter: '{a}' };
    });
  }
  echarts.init(el, 'seqera').setOption({
    title: { text: title, subtext: opts.subtitle || '' },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: opts.formatter || (p => p[0].name + ': ' + (opts.prefix||'') +
        p[0].value.toLocaleString(undefined, {maximumFractionDigits:2}) + (opts.suffix||'')) },
    grid: { top: opts.subtitle ? 60 : 40, bottom: 30, containLabel: true },
    xAxis: { type: 'value', name: opts.xName || '', nameLocation: 'center',
      nameGap: 25, axisLabel: { hideOverlap: true } },
    yAxis: { type: 'category', data: labels.slice().reverse() },
    series: seriesArray,
  });
}

function hbarStacked(elId, title, labels, seriesDefs, opts) {
  opts = opts || {};
  const el = document.getElementById(elId);
  if (!el) return;
  const height = Math.max(250, labels.length * 45 + 80);
  el.style.height = height + 'px';
  echarts.init(el, 'seqera').setOption({
    title: { text: title, subtext: opts.subtitle || '' },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { show: seriesDefs.length > 3, bottom: 0 },
    grid: { top: opts.subtitle ? 60 : 40, bottom: 40, containLabel: true },
    xAxis: { type: 'value', name: opts.xName || '', nameLocation: 'center', nameGap: 25, axisLabel: { hideOverlap: true } },
    yAxis: { type: 'category', data: labels.slice().reverse() },
    series: seriesDefs.map((s, i, arr) => ({
      name: s.name, type: 'bar', stack: 'total',
      data: s.data.slice().reverse(), itemStyle: { color: s.color,
        borderRadius: i === arr.length - 1 ? [0, 2, 2, 0] : 0 },
      emphasis: { focus: 'series' },
      label: { show: true, position: 'inside', overflow: 'truncate', formatter: function(p) { return p.value > 5 ? p.seriesName : ''; }, fontSize: 11, color: '#fff' },
    })),
  });
}

// 2.2 Run metrics charts
(function() {
  const metrics = DATA.run_metrics || [];
  const costs = DATA.run_costs || [];
  const labels = metrics.map(r => r.group);

  const wallValues = metrics.map(r => +(r.duration / 3600000).toFixed(2));
  hbarChart('chart-wall-time', 'Wall time', labels, wallValues,
    { xName: 'Hours', suffix: ' h', subtitle: takeaway(labels, wallValues, { lowerBetter: true, adjective: 'faster', suffix: ' h' }) });

  const cpuValues = metrics.map(r => +(r.cpuTime || 0));
  hbarChart('chart-cpu-time', 'CPU time', labels, cpuValues,
    { xName: 'CPU Hours', suffix: ' h', subtitle: takeaway(labels, cpuValues, { lowerBetter: true, adjective: 'lower', suffix: ' h' }) });

  const costValues = metrics.map(r => { const c = costs.find(x => x.run_id === r.run_id); return c ? +c.cost : 0; });
  hbarChart('chart-est-cost', 'Compute cost', labels, costValues,
    { xName: '$', prefix: '$', subtitle: takeaway(labels, costValues, { lowerBetter: true, adjective: 'cheaper', prefix: '$' }) });

  // Workflow status — succeeded/failed/cached stacked bars
  const summaryRuns = DATA.run_summary || [];
  const totalSucc = summaryRuns.reduce((s,r) => s + (r.succeedCount||0), 0);
  const totalFail = summaryRuns.reduce((s,r) => s + (r.failedCount||0), 0);
  const totalCached = summaryRuns.reduce((s,r) => s + (r.cachedCount||0), 0);
  let statusSubtitle = '';
  if (totalFail === 0 && totalCached === 0) {
    statusSubtitle = 'All tasks succeeded';
  } else {
    const parts = [];
    if (totalFail > 0) parts.push(totalFail + ' task' + (totalFail > 1 ? 's' : '') + ' failed');
    if (totalCached > 0) parts.push(totalCached + ' task' + (totalCached > 1 ? 's' : '') + ' cached');
    statusSubtitle = parts.join(', ') + ' across all runs';
  }
  const statusSeries = [
    { name: 'Succeeded', data: summaryRuns.map(r => r.succeedCount || 0), color: '#16a34a' },
    { name: 'Failed', data: summaryRuns.map(r => r.failedCount || 0), color: '#dc2626' },
  ];
  if (totalCached > 0) {
    statusSeries.push(
      { name: 'Cached', data: summaryRuns.map(r => r.cachedCount || 0), color: '#f59e0b' }
    );
  }
  hbarStacked('chart-workflow-status', 'Workflow status', labels, statusSeries,
    { xName: 'Tasks', subtitle: statusSubtitle });

  const cpuEffValues = metrics.map(r => +(r.cpuEfficiency || 0));
  hbarChart('chart-cpu-eff', 'CPU efficiency', labels, cpuEffValues,
    { xName: '%', suffix: '%', subtitle: takeaway(labels, cpuEffValues, { adjective: 'more efficient', suffix: '%' }) });
  const memEffValues = metrics.map(r => +(r.memoryEfficiency || 0));
  hbarChart('chart-mem-eff', 'Memory efficiency', labels, memEffValues,
    { xName: '%', suffix: '%', subtitle: takeaway(labels, memEffValues, { adjective: 'more efficient', suffix: '%' }) });

  const readValues = metrics.map(r => +(r.readBytes || 0));
  hbarChart('chart-read-io', 'Data read', labels, readValues,
    { xName: 'GB', suffix: ' GB', subtitle: takeaway(labels, readValues, { lowerBetter: true, adjective: 'less I/O', suffix: ' GB' }) });
  const writeValues = metrics.map(r => +(r.writeBytes || 0));
  hbarChart('chart-write-io', 'Data written', labels, writeValues,
    { xName: 'GB', suffix: ' GB', subtitle: takeaway(labels, writeValues, { lowerBetter: true, adjective: 'less I/O', suffix: ' GB' }) });
})();

// 3. Process overview
(function() {
  const stats = DATA.process_stats || [];
  if (!stats.length) return;

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

    const processes = [...new Set(pipelineStats.map(s => s.process_name))];

    const section = document.createElement('div');
    section.innerHTML = `<h3>${pipeline}</h3>`;

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
        markPoint: groups.length <= 3 ? {
          data: [{ type: 'max', valueDim: 'x' }],
          label: { formatter: g, fontSize: 10, position: 'right', color: groupColor[g] },
          symbolSize: 0
        } : undefined,
      };
    });

    const errorSeries = groups.map((g, gi) => {
      const gStats = pipelineStats.filter(s => s.group === g);
      return {
        name: g + ' (\u00b1SD)', type: 'custom', silent: true,
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

    const costEl = document.createElement('div');
    costEl.className = 'chart';
    costEl.style.height = Math.max(400, processes.length * 25 + 120) + 'px';
    section.appendChild(costEl);

    const costSeries = groups.map((g, gi) => {
      const gStats = pipelineStats.filter(s => s.group === g);
      return {
        name: g, type: 'bar', stack: g,
        itemStyle: { color: groupColor[g], borderRadius: [0, 2, 2, 0] },
        emphasis: { focus: 'series' },
        label: { show: groups.length <= 3, position: 'right', formatter: '{a}', fontSize: 10 },
        data: processes.map(p => {
          const s = gStats.find(x => x.process_name === p);
          return s ? +s.total_cost.toFixed(4) : 0;
        }),
        markLine: gi === 0 ? {
          silent: true,
          data: [{ type: 'max', name: 'Most expensive' }],
          label: { formatter: 'Most expensive', position: 'middle', fontSize: 10 },
          lineStyle: { type: 'dashed', color: '#999' }
        } : undefined
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
        legend: { show: groups.length > 3, data: groups, bottom: 0 },
        grid: { top: 40, bottom: 40, containLabel: true },
        xAxis: { type: 'value', name: 'Run time (minutes)', nameLocation: 'center', nameGap: 25 },
        yAxis: { type: 'category', data: processes,
                 axisLabel: { width: 280, overflow: 'truncate' },
                 inverse: true },
        series: [...series, ...errorSeries],
      });

      echarts.init(costEl, 'seqera').setOption({
        title: { text: 'Total process cost ($)' },
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        legend: { show: groups.length > 3, data: groups, bottom: 0 },
        grid: { top: 40, bottom: 40, containLabel: true },
        xAxis: { type: 'value', name: 'Cost ($)', nameLocation: 'center', nameGap: 25 },
        yAxis: { type: 'category', data: processes,
                 axisLabel: { width: 280, overflow: 'truncate' },
                 inverse: true },
        series: costSeries,
      });
    }, 50);
  });
})();

// 4.1 Task instance usage
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
    legend: { data: instanceTypes, bottom: 0, type: 'scroll' },
    grid: { top: 40, bottom: 60, containLabel: true },
    xAxis: { type: 'value', name: 'Number of tasks', nameLocation: 'center', nameGap: 25 },
    yAxis: { type: 'category', data: groups.slice().reverse() },
    series: instanceTypes.map(t => ({
      name: t, type: 'bar', stack: 'total',
      emphasis: { focus: 'series' },
      data: groups.slice().reverse().map(g => {
        const match = usage.find(u => u.group === g && u.machine_type === t);
        return match ? match.count : 0;
      }),
      itemStyle: { color: instanceColors[t] },
    })),
  });
})();

// 4.2 Task metrics
(function() {
  const tasks = DATA.task_scatter || [];
  const taskTable = DATA.task_table || [];
  if (!tasks.length) return;

  const container = document.getElementById('task-sections');

  const scatterEl = document.createElement('div');
  scatterEl.className = 'chart';
  scatterEl.style.height = '500px';
  container.appendChild(scatterEl);

  setTimeout(() => {
    echarts.init(scatterEl, 'seqera').setOption({
      title: { text: 'Task real time vs staging time' },
      tooltip: { trigger: 'item',
        formatter: p => `<strong>${p.data[3]}</strong><br>Real time: ${p.data[0].toFixed(1)} min<br>Staging: ${p.data[1].toFixed(1)} min<br>Cost: $${p.data[2].toFixed(4)}` },
      legend: { show: groups.length > 3, data: groups, bottom: 0 },
      grid: { top: 50, bottom: 60, containLabel: true },
      xAxis: { type: 'value', name: 'Task real time (minutes)', nameLocation: 'center', nameGap: 25 },
      yAxis: { type: 'value', name: 'Task staging time (minutes)', nameLocation: 'center', nameGap: 40 },
      series: groups.map((g, i) => ({
        name: g, type: 'scatter', symbolSize: 6,
        data: tasks.filter(t => t.group === g).map(t => [t.realtime_min||0, t.staging_min||0, t.cost||0, t.process_short]),
        itemStyle: { color: groupColor[g] },
        markPoint: groups.length <= 3 ? {
          data: [{ type: 'max', valueDim: 'x' }],
          label: { formatter: g, fontSize: 10, position: 'top', color: groupColor[g] },
          symbolSize: 0
        } : undefined,
      })),
      dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 25, height: 20 }],
    });
  }, 100);

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
      grid: { top: 40, bottom: 20, containLabel: true },
      yAxis: { type: 'category', data: processes,
               axisLabel: { width: 220, overflow: 'truncate' },
               inverse: true },
      xAxis: { type: 'value', name: 'Cost ($)', nameLocation: 'center', nameGap: 25 },
      series: [{ type: 'boxplot', data: boxData }],
    });
  }, 150);

  if (taskTable.length) {
    const tableDiv = document.createElement('div');
    tableDiv.innerHTML = `
      <div class="callout" style="margin-top:20px">
        <div class="callout-header" onclick="this.nextElementSibling.classList.toggle('show')">
          &#9654; Click to display task table (${taskTable.length} tasks)
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
          if (k === 'Realtime_min') v = v != null ? Number(v).toFixed(1) : '\u2014';
          else if (k === 'Cost') v = v != null ? '$' + Number(v).toFixed(6) : '\u2014';
          else if (v == null) v = '\u2014';
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

// Side nav: highlight link for section in view
(function () {
  const nav = document.getElementById('side-nav');
  if (!nav) return;
  const links = [...nav.querySelectorAll('a[href^="#"]')];
  const sections = links
    .map((a) => document.getElementById(a.getAttribute('href').slice(1)))
    .filter(Boolean);
  if (!sections.length) return;

  function updateActive() {
    const margin = 100;
    let current = sections[0];
    for (const sec of sections) {
      const top = sec.getBoundingClientRect().top;
      if (top <= margin) current = sec;
      else break;
    }
    const id = current.id;
    links.forEach((l) => {
      l.classList.toggle('active', l.getAttribute('href') === '#' + id);
    });
  }

  window.addEventListener('scroll', updateActive, { passive: true });
  window.addEventListener('resize', updateActive);
  updateActive();
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


@app.command()
def main(
    tables_dir: Path = typer.Option(
        ..., exists=True, help="Directory containing query result JSON files"
    ),
    output: Path = typer.Option(
        Path("benchmark_report.html"), help="Output HTML file"
    ),
    brand: Path = typer.Option(None, help="Brand YAML file for report colors"),
    logo: Path = typer.Option(None, help="SVG logo file for report navbar"),
) -> None:
    """Render benchmark HTML report from pre-computed query results."""
    data = load_query_data(tables_dir)

    brand_colors = load_brand(brand)
    logo_svg = logo.read_text() if logo and logo.exists() else None

    render_html(data, str(output), brand_colors, logo_svg)
    typer.echo(f"Report written to {output}")


if __name__ == "__main__":
    app()
