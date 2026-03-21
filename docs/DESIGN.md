# nf-agg v2: API-First Benchmark Reports

## Overview

Replace `tw runs dump` + R/Quarto with nf-boost `request()` + `map` → DuckDB → eCharts. Zero containers for data fetch, one lightweight Python container for report generation.

## Architecture

```
                     Nextflow Pipeline (nf-boost)
┌────────────────────────────────────────────────────────┐
│                                                        │
│  input CSV ──→ .map { fetchWorkflow(it) }              │
│                  ├─ GET /workflow/{id}                  │
│                  ├─ GET /workflow/{id}/metrics          │
│                  ├─ GET /workflow/{id}/tasks            │
│                  └─ GET /workflow/{id}/progress         │
│                                                        │
│           ↓ channel: [meta, workflow_json, tasks_json,  │
│                       metrics_json, progress_json]     │
│                                                        │
│  .collect() ──→ BENCHMARK_REPORT (Python + DuckDB)     │
│                  + optional AWS CUR parquet             │
│                  ↓                                      │
│             benchmark_report.html (eCharts)             │
└────────────────────────────────────────────────────────┘
```

## Data Flow

### Step 1: Fetch via nf-boost `request()` + `map`

No process needed. Pure Nextflow `map` operator calls the Seqera API directly:

```nextflow
include { request; fromJson; toJson } from 'plugin/nf-boost'

def fetchRun(meta, apiEndpoint) {
    def token = System.getenv("TOWER_ACCESS_TOKEN")
    def headers = ["Authorization": "Bearer ${token}"]
    def wsId = resolveWorkspaceId(meta.workspace, apiEndpoint, headers)

    def workflow = apiGet("${apiEndpoint}/workflow/${meta.id}?workspaceId=${wsId}", headers)
    def metrics  = apiGet("${apiEndpoint}/workflow/${meta.id}/metrics?workspaceId=${wsId}", headers)
    def tasks    = apiGetPaginated("${apiEndpoint}/workflow/${meta.id}/tasks?workspaceId=${wsId}", headers)
    def progress = apiGet("${apiEndpoint}/workflow/${meta.id}/progress?workspaceId=${wsId}", headers)

    return [meta, workflow, metrics, tasks, progress]
}
```

### Step 2: Write JSON → DuckDB in Python process

The `BENCHMARK_REPORT` process receives all JSON data, loads into DuckDB, joins with optional AWS CUR parquet, and renders eCharts HTML.

#### DuckDB Tables

**`runs`** — one row per workflow run:
- run_id, group, pipeline, run_name, status, start, complete, duration
- cpu_efficiency, memory_efficiency, cpu_time, read_bytes, write_bytes
- succeeded, failed, cached, fusion_enabled, wave_enabled

**`tasks`** — one row per task:
- run_id, group, hash, name, process, tag, status
- submit, start, complete, duration, realtime (ms)
- cpus, memory, rss, peak_rss, read_bytes, write_bytes
- cost, executor, machine_type, cloud_zone, exit_status
- derived: runtime_ms, wait_ms, staging_ms, process_short

**`costs`** (optional, from AWS CUR parquet):
- run_id, process, hash, cost, used_cost, unused_cost

**`benchmark`** view: tasks JOIN runs LEFT JOIN costs

### Step 3: eCharts Static HTML Report

Single self-contained HTML file. Jinja2 template with embedded eCharts JS. Data injected as JSON blobs.

Report sections (matching current Quarto report):
1. **Benchmark Overview** — grouped bars: wall time, cost, CPU time per group
2. **Run Overview** — summary table of all runs
3. **Process Overview** — box plots: runtime, memory, CPU per process (from /metrics ResourceData)
4. **Task Overview** — scatter (runtime vs memory), timeline/gantt per run
5. **Cost Overview** — stacked bars per process, used vs unused

## Input Format

Same CSV, with optional `group` column:

```csv
id,workspace,group
4Bi5xBK6E2Nbhj,community/showcase,GroupA
4LWT4uaXDaGcDY,community/showcase,GroupB
```

## CLI

```bash
# Standard pipeline invocation
nextflow run seqeralabs/nf-aggregate --input runs.csv --generate_benchmark_report

# With AWS costs
nextflow run seqeralabs/nf-aggregate --input runs.csv --generate_benchmark_report --benchmark_aws_cur_report aws_cur.parquet
```

## Project Structure

```
nf-agg/
├── workflows/nf_aggregate/main.nf     # orchestrator
├── modules/local/
│   ├── seqera_runs_dump/               # KEEP for backwards compat
│   ├── benchmark_report/               # REPLACE with v2
│   └── plot_run_gantt/                 # KEEP (fusion-only gantt)
├── lib/
│   └── SeqeraApi.groovy                # nf-boost request() wrappers
├── bin/
│   ├── benchmark_report.py             # DuckDB + eCharts report generator
│   └── plot_run_gantt.py               # existing gantt plotter
├── templates/
│   └── benchmark_report.html           # Jinja2 + eCharts template
└── nextflow.config                     # add nf-boost plugin
```

## Dependencies

**Nextflow plugins**: nf-boost (for `request`, `fromJson`, `toJson`)
**Python container**: duckdb, jinja2, pyarrow (for parquet)
**Zero**: R, Quarto, renv, tower-cli

## Migration

1. Add nf-boost plugin, implement API fetch in `map`
2. New BENCHMARK_REPORT_V2 process (Python + DuckDB + eCharts)
3. Wire into workflow alongside existing modules
4. Deprecate old R-based BENCHMARK_REPORT
