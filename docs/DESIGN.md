# nf-agg: API-First Benchmark Reports

## Overview

nf-boost `request()` + `map` → DuckDB → eCharts. Zero containers for data fetch, single process for report generation.

## Architecture

```
                     Nextflow Pipeline (nf-boost)
┌────────────────────────────────────────────────────────────┐
│                                                            │
│  input CSV ──→ .map { fetchWorkflow(it) }   (head job)    │
│                  ├─ GET /workflow/{id}                      │
│                  ├─ GET /workflow/{id}/metrics              │
│                  ├─ GET /workflow/{id}/tasks                │
│                  └─ GET /workflow/{id}/progress             │
│                                                            │
│           ↓ collect JSON files into directory               │
│                                                            │
│  BENCHMARK_REPORT process:                                 │
│    benchmark_report.py build-db → benchmark.duckdb         │
│    benchmark_report.py report   → benchmark_report.html    │
└────────────────────────────────────────────────────────────┘
```

Additional paths (always active):
- `SEQERA_RUNS_DUMP` (tower-cli) → run dump dirs → `MULTIQC` + `PLOT_RUN_GANTT`

## Data Flow

### Step 0: Fetch via nf-boost `request()` + `map` (head job)

No process needed. Pure Nextflow `map` operator calls the Seqera API directly
via `SeqeraApi.fetchRunData()`. JSON files collected into a directory.

### Step 1: build-db — JSON + CUR → DuckDB

Script: `bin/benchmark_report.py build-db`

Reads run JSON files and optional AWS CUR parquet. Creates a persistent
DuckDB database with normalized tables:

- `runs` — one row per workflow run (includes `cached` count)
- `tasks` — one row per task (filtered: keeps COMPLETED + CACHED, drops FAILED)
- `metrics` — one row per process metric field
- `costs` — optional, from AWS CUR parquet (auto-detects CUR 1.0 flat vs 2.0 MAP)

### Step 2: report — DuckDB → HTML

Script: `bin/benchmark_report.py report`

Opens the DuckDB file, runs 9 SQL queries, renders self-contained HTML with eCharts.

Report sections:
1. **Benchmark Overview** — pipeline × group matrix
2. **Run Overview** — summary table + metrics charts
3. **Run Metrics** — wall time, CPU time, cost, status, efficiency, I/O
4. **Workflow Status** — succeeded/failed/cached stacked bars
5. **Process Overview** — dot + error bar charts, cost per process
6. **Task Overview** — instance usage, scatter, box plots, task table

### Standalone: fetch — API → JSON

Script: `bin/benchmark_report.py fetch`

Python equivalent of `SeqeraApi.groovy` for agent/standalone use. Calls 4 API
endpoints per run and writes one JSON file per run. Not used by the Nextflow pipeline.

## DuckDB Tables

**`runs`** — one row per workflow run:
- run_id, group, pipeline, run_name, status, start, complete, duration_ms
- succeeded, failed, **cached** (from `workflow.stats.cachedCount`)
- cpu_efficiency, memory_efficiency, cpu_time_ms, read_bytes, write_bytes
- fusion_enabled, wave_enabled, executor, region, etc.

**`tasks`** — one row per task:
- run_id, group, hash, name, process, tag, status
- submit, start, complete, duration_ms, realtime_ms
- cpus, memory_bytes, rss, peak_rss, read_bytes, write_bytes
- cost, executor, machine_type, cloud_zone, exit_status
- derived: process_short, wait_ms, staging_ms

**`metrics`** — per-process resource stats:
- run_id, group, process
- cpu/mem/vmem/time/reads/writes/cpuUsage/memUsage/timeUsage × {mean,min,q1,q2,q3,max}

**`costs`** (optional, from AWS CUR parquet):
- run_id, process, hash, cost, used_cost, unused_cost

## Input Format

CSV with optional `group` column:

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
nextflow run seqeralabs/nf-aggregate --input runs.csv --generate_benchmark_report \
  --benchmark_aws_cur_report aws_cur.parquet
```

## Local Testing

```bash
# Build DuckDB from JSON data
uv run --with duckdb --with typer --with pyyaml --with pyarrow \
  python bin/benchmark_report.py build-db \
  --data-dir /path/to/json_data --output /tmp/benchmark.duckdb

# Render HTML report from DuckDB
uv run --with duckdb --with jinja2 --with typer --with pyyaml \
  python bin/benchmark_report.py report \
  --db /tmp/benchmark.duckdb --brand assets/brand.yml --output /tmp/report.html

# Fetch from Seqera API (standalone)
uv run --with duckdb --with typer --with pyyaml --with httpx \
  python bin/benchmark_report.py fetch \
  --run-ids <id> --workspace org/name --output-dir /tmp/json_data
```

## Running Tests

```bash
uv run --with duckdb --with jinja2 --with typer --with pyyaml --with pyarrow --with httpx --with pytest \
  pytest bin/test_benchmark_report.py -v
```

## Project Structure

```
nf-agg/
├── workflows/nf_aggregate/main.nf     # orchestrator
├── modules/local/
│   ├── benchmark_report/main.nf       # build-db + report (single process)
│   ├── extract_tarball/main.nf        # extract external run tarballs
│   ├── seqera_runs_dump/              # tower-cli runs dump + metadata
│   └── plot_run_gantt/                # fusion-only gantt
├── lib/
│   └── SeqeraApi.groovy               # API client (head job, Nextflow only)
├── bin/
│   ├── benchmark_report.py            # unified CLI (build-db, report, fetch)
│   ├── benchmark_report_template.html # eCharts HTML template
│   ├── test_benchmark_report.py       # tests
│   └── plot_run_gantt.py              # gantt chart script
└── nextflow.config
```

## Key Params

| Param | Default | Purpose |
|---|---|---|
| `generate_benchmark_report` | false | Enable benchmark report |
| `benchmark_aws_cur_report` | null | AWS CUR parquet for cost analysis |
| `seqera_api_endpoint` | `https://api.cloud.seqera.io` | Platform API URL |
| `skip_run_gantt` | false | Skip Gantt chart generation |
| `skip_multiqc` | false | Skip MultiQC aggregation |

## Plugins

- `nf-schema@2.3.0` — param validation, samplesheet parsing
- `nf-boost@0.6.0` — `request()`, `fromJson`/`toJson` for API calls

## Env Requirements

- `TOWER_ACCESS_TOKEN` — Seqera Platform API token

## Dependencies

**Nextflow plugins**: nf-boost (for `request`, `fromJson`, `toJson`)
**Python**: duckdb, jinja2, typer, pyarrow (for parquet), pyyaml, httpx (fetch only)

## Gotchas

- Wave freeze strategy: `['conda', 'container', 'dockerfile']` — no `spack`
- DuckDB `read_json_auto` needs file paths, not JSON strings — use temp files
- CUR hash join: task hash contains '/' (e.g. `45/d87388`) — strip before comparing
- CUR auto-detects format (MAP vs flattened) — no user config needed
