# nf-agg: API-first benchmark reports (current design)

## Overview

Benchmark reporting uses a staged handoff:

`raw run JSON -> jsonl_bundle/ -> report_data.json -> benchmark_report.html`

The current implementation does not use DuckDB as an intermediate artifact.

## Workflow architecture

```
input CSV (id, workspace, group, logs, fusion)
  -> branch: api (SeqeraApi.fetchRunData) | external (EXTRACT_TARBALL)
  -> collect JSON files
  -> NORMALIZE_BENCHMARK_JSONL (raw JSON -> jsonl_bundle/)
  -> AGGREGATE_BENCHMARK_REPORT_DATA (jsonl_bundle -> report_data.json)
  -> RENDER_BENCHMARK_REPORT (report_data.json -> benchmark_report.html)
```

### Routing behavior

- API runs (`workspace != external`) are fetched via `SeqeraApi.fetchRunData()`
- External runs (`workspace == external`) are read from directory/tarball logs
- Tarball inputs pass through `EXTRACT_TARBALL` before merge

## Stage boundaries

### 1) Normalize stage

Command:

```bash
python bin/benchmark_report.py normalize-jsonl --data-dir <run_json_dir> --output-dir <jsonl_bundle>
```

Responsibilities:

- read run JSON payloads
- normalize runs/tasks/metrics rows
- optionally normalize CUR parquet into `costs.jsonl`
- write:
  - `runs.jsonl`
  - `tasks.jsonl`
  - `metrics.jsonl`
  - optional `costs.jsonl`

### 2) Aggregate stage

Command:

```bash
python bin/benchmark_report.py aggregate-report-data --jsonl-dir <jsonl_bundle> --output <report_data.json>
```

Responsibilities:

- stream JSONL rows
- compute report sections:
  - `benchmark_overview`
  - `run_summary`
  - `run_metrics`
  - `run_costs`
  - `process_stats`
  - `task_instance_usage`
  - `task_table`
  - `task_scatter`
  - optional `cost_overview`

### 3) Render stage

Command:

```bash
python bin/benchmark_report.py render-html --data <report_data.json> --output <benchmark_report.html>
```

Responsibilities:

- load report JSON
- apply brand/logo overrides when provided
- render self-contained HTML from the Jinja template

## Benchmark CLI surface

`bin/benchmark_report.py` provides:

- `normalize-jsonl`
- `aggregate-report-data`
- `render-html`
- `report` (aggregate + render convenience wrapper)
- `fetch` (standalone API fetch helper)

## Inputs and outputs

### Input CSV

```csv
id,workspace,group,logs
4Bi5xBK6E2Nbhj,community/showcase,GroupA,
1JI5B1avuj3o58,external,GroupB,/path/to/run_dumps.tar.gz
```

### Published benchmark outputs

```
results/benchmark_report/
  benchmark_report.html
  report_data.json
  jsonl_bundle/
```

## Local verification commands

### Stage rebuild

```bash
uv run --with typer --with pyyaml --with pyarrow \
  python bin/benchmark_report.py normalize-jsonl \
  --data-dir /path/to/json_data --output-dir /tmp/jsonl_bundle

uv run --with typer --with pyyaml \
  python bin/benchmark_report.py aggregate-report-data \
  --jsonl-dir /tmp/jsonl_bundle --output /tmp/report_data.json

uv run --with jinja2 --with typer --with pyyaml \
  python bin/benchmark_report.py render-html \
  --data /tmp/report_data.json --brand assets/brand.yml --output /tmp/report.html
```

### Automated tests

```bash
uv run --with typer --with pyyaml --with jinja2 --with pyarrow --with pytest --with httpx \
  pytest -v \
  modules/local/aggregate_benchmark_report_data/tests/test_aggregate.py \
  modules/local/normalize_benchmark_jsonl/tests/test_normalize.py \
  modules/local/render_benchmark_report/tests/test_render.py \
  bin/test_benchmark_report_fetch.py

nf-test test --profile=+docker --verbose
```

## Notes

- JSONL is the primary handoff for streaming-friendly processing.
- `report_data.json` is the explicit boundary between aggregation and rendering.
- CUR join key uses `(run_id, process, hash_short)` to avoid collisions.
