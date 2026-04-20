---
name: rebuild-benchmark-report-locally
description: >
  Rebuild nf-aggregate benchmark outputs locally from fetched JSON or external
  run dumps. Use when iterating on normalize/aggregate/render logic, chart
  changes, or benchmarking HTML output without re-running the full pipeline.
---

# Rebuild benchmark report locally

Use this skill when the user wants to regenerate or debug the nf-aggregate
benchmark report from local artifacts.

## When to use

- "Regenerate the benchmark report"
- "Re-render the HTML after template changes"
- "Debug normalize vs aggregate vs render"
- "Test a chart fix locally"
- "Build report data from already-fetched run JSON"

## Pipeline boundaries

nf-aggregate has an explicit three-stage local rebuild flow:

1. raw run JSON -> `jsonl_bundle/`
2. `jsonl_bundle/` -> `report_data.json`
3. `report_data.json` -> `benchmark_report.html`

Use those boundaries to isolate failures instead of re-running everything.

## Preferred commands

### 1) Normalize raw JSON to JSONL

```bash
uv run --with typer --with pyyaml --with pyarrow \
  python bin/benchmark_report.py normalize-jsonl \
  --data-dir /path/to/json_data \
  --output-dir /tmp/jsonl_bundle
```

Optional CUR cost enrichment:

```bash
uv run --with typer --with pyyaml --with pyarrow \
  python bin/benchmark_report.py normalize-jsonl \
  --data-dir /path/to/json_data \
  --costs /path/to/cur.parquet \
  --output-dir /tmp/jsonl_bundle
```

### 2) Aggregate JSONL to report data

```bash
uv run --with typer --with pyyaml \
  python bin/benchmark_report.py aggregate-report-data \
  --jsonl-dir /tmp/jsonl_bundle \
  --output /tmp/report_data.json
```

### 3) Render HTML from report data

```bash
uv run --with jinja2 --with typer --with pyyaml \
  python bin/benchmark_report.py render-html \
  --data /tmp/report_data.json \
  --brand assets/brand.yml \
  --output /tmp/report.html
```

## Fast debugging guidance

- If task/run parsing looks wrong, inspect the normalize stage output first.
- If summaries look wrong but raw rows look fine, inspect `report_data.json`.
- If numbers are right but charts/layout are wrong, debug only the render stage.
- Keep `jsonl_bundle/` as the handoff format for large-data and Fusion-friendly flows.

## Repo-specific gotchas

- `report_data.json` is the explicit contract between aggregation and rendering.
- The Wave freeze strategy must stay `['conda', 'container', 'dockerfile']` — do not add `spack`.
- The benchmark report publishes under `results/benchmark_report/` in full pipeline runs.
- Python stage logic lives in:
  - `bin/benchmark_report_normalize.py`
  - `bin/benchmark_report_aggregate.py`
  - `bin/benchmark_report_render.py`

## Verification

After a local rebuild:

- confirm `jsonl_bundle/` contains `runs.jsonl`, `tasks.jsonl`, and `metrics.jsonl`
- confirm `report_data.json` exists and is non-empty
- open the rendered HTML and verify expected charts/tables changed
- if touching Python logic, run the targeted pytest suites from `AGENTS.md`
