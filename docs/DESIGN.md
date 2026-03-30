# nf-agg: API-First Benchmark Reports

## Overview

nf-boost `request()` + `map` → DuckDB → eCharts. Zero containers for data fetch, multi-step pipeline for report generation.

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
│  ┌─ CLEAN_JSON ──→ runs.csv, tasks.csv, metrics.csv       │
│  │                                                         │
│  ├─ CLEAN_CUR ───→ costs.csv (optional, CUR 1.0 or 2.0)  │
│  │                                                         │
│  ├─ BUILD_TABLES ─→ query result JSONs (9 files)          │
│  │                   (joins, aggregation, DuckDB queries)  │
│  │                                                         │
│  └─ RENDER_REPORT → benchmark_report.html (eCharts)       │
│                      (strictly HTML rendering, no queries) │
└────────────────────────────────────────────────────────────┘
```

Additional paths (always active):
- `SEQERA_RUNS_DUMP` (tower-cli) → run dump dirs → `MULTIQC` + `PLOT_RUN_GANTT`

## Data Flow

### Step 0: Fetch via nf-boost `request()` + `map` (head job)

No process needed. Pure Nextflow `map` operator calls the Seqera API directly
via `SeqeraApi.fetchRunData()`. JSON files collected into a directory.

### Step 1: CLEAN_JSON — Normalize raw JSON → CSVs

Script: `bin/clean_json.py`

Reads run JSON files and produces:
- `runs.csv` — one row per workflow run (includes `cached` count)
- `tasks.csv` — one row per task (filtered: keeps COMPLETED + CACHED, drops FAILED)
- `metrics.csv` — one row per process metric field

### Step 2: CLEAN_CUR — Normalize AWS CUR parquet → CSV (optional)

Script: `bin/clean_cur.py`

Auto-detects CUR format:
- **CUR 2.0** (MAP format): `resource_tags` is `MAP(VARCHAR, VARCHAR)`
- **CUR 1.0** (flattened): `resource_tags_user_unique_run_id`, etc.

Produces: `costs.csv` with columns: `run_id, process, hash, cost, used_cost, unused_cost`

### Step 3: BUILD_TABLES — DuckDB joins/aggregation → query result JSONs

Script: `bin/build_tables.py`

Reads CSVs, runs DuckDB queries, outputs JSON files:
- `benchmark_overview.json` — Pipeline × group matrix
- `run_summary.json` — Infrastructure settings (includes `cachedCount`)
- `run_metrics.json` — Duration, CPU time, efficiency
- `run_costs.json` — Per-run costs (task-level + optional CUR)
- `process_stats.json` — Per-process mean ± SD
- `task_instance_usage.json` — Instance type counts
- `task_table.json` — Full task table
- `task_scatter.json` — Realtime vs staging scatter data
- `cost_overview.json` — CUR cost breakdown (if available)

### Step 4: RENDER_REPORT — HTML rendering (no queries)

Script: `bin/render_report.py`

Loads pre-computed JSON files, renders self-contained HTML with eCharts.
**Does no DuckDB queries.** Strictly presentation layer.

Report sections:
1. **Benchmark Overview** — pipeline × group matrix
2. **Run Overview** — summary table + metrics charts
3. **Run Metrics** — wall time, CPU time, cost, status, efficiency, I/O
4. **Workflow Status** — succeeded/failed/cached stacked bars
5. **Process Overview** — dot + error bar charts, cost per process
6. **Task Overview** — instance usage, scatter, box plots, task table

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

## Local Testing (individual scripts)

```bash
# Step 1: Clean JSON
uv run --with duckdb --with typer --with pyyaml python bin/clean_json.py \
  --data-dir tests/data \
  --output-dir /tmp/cleaned

# Step 3: Build tables
uv run --with duckdb --with typer python bin/build_tables.py \
  --runs-csv /tmp/cleaned/runs.csv \
  --tasks-csv /tmp/cleaned/tasks.csv \
  --metrics-csv /tmp/cleaned/metrics.csv \
  --output-dir /tmp/tables

# Step 4: Render report
uv run --with jinja2 --with typer --with pyyaml python bin/render_report.py \
  --tables-dir /tmp/tables \
  --brand assets/brand.yml \
  --output /tmp/benchmark_report.html
```

## Running Tests

```bash
# All new decomposed tests
uv run --with duckdb --with jinja2 --with typer --with pyyaml --with pyarrow --with pytest \
  pytest bin/test_clean_json.py bin/test_clean_cur.py bin/test_build_tables.py bin/test_render_report.py -v

```

## Project Structure

```
nf-agg/
├── workflows/nf_aggregate/main.nf     # orchestrator
├── modules/local/
│   ├── clean_json/main.nf             # JSON → CSVs
│   ├── clean_cur/main.nf              # CUR parquet → costs CSV
│   ├── build_tables/main.nf           # CSVs → query result JSONs
│   ├── render_report/main.nf          # JSONs → HTML report
│   ├── seqera_runs_dump/              # tower-cli runs dump + metadata
│   └── plot_run_gantt/                # fusion-only gantt
├── lib/
│   └── SeqeraApi.groovy               # API client (head job)
├── bin/
│   ├── clean_json.py                   # Step 1: normalize JSON
│   ├── clean_cur.py                    # Step 2: normalize CUR
│   ├── build_tables.py                 # Step 3: DuckDB queries
│   ├── render_report.py                # Step 4: HTML rendering
│   ├── test_clean_json.py              # tests for step 1
│   ├── test_clean_cur.py               # tests for step 2
│   ├── test_build_tables.py            # tests for step 3
│   ├── test_render_report.py           # tests for step 4
│   └── test_render_report.py           # tests for step 4
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
**Python**: duckdb, jinja2, typer, pyarrow (for parquet), pyyaml
**Not required**: R, Quarto, renv

## Gotchas

- Wave freeze strategy: `['conda', 'container', 'dockerfile']` — no `spack`
- DuckDB `read_json_auto` needs file paths, not JSON strings — use temp files
- `commit.gpgsign` must be true (SSH signing via 1Password)
- CUR hash join: task hash contains '/' (e.g. `45/d87388`) — strip before comparing
- CLEAN_CUR auto-detects CUR format (MAP vs flattened) — no user config needed
