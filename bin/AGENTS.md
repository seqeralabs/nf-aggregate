# bin/ — CLI Scripts

Python scripts executed inside Nextflow process containers. Placed in `bin/` so Nextflow auto-adds them to `$PATH`.

## benchmark_report.py

Thin Typer CLI wrapper around focused modules.

| Subcommand | Purpose |
|---|---|
| `normalize-jsonl` | Raw run JSON (+ optional CUR parquet) → `jsonl_bundle/` (`runs.jsonl`, `tasks.jsonl`, `metrics.jsonl`, optional `costs.jsonl`) |
| `aggregate-report-data` | `jsonl_bundle/` → `report_data.json` |
| `render-html` | `report_data.json` + brand/logo assets → self-contained HTML |
| `report` | Convenience wrapper (`aggregate-report-data` + `render-html`) |
| `fetch` | Calls Seqera Platform API → writes run JSON files (standalone use) |

## Focused modules

- `benchmark_report_normalize.py` — normalization stage
- `benchmark_report_aggregate.py` — report aggregation stage
- `benchmark_report_render.py` — HTML rendering stage
- `benchmark_report_fetch.py` — Seqera API fetch helpers

### Test ownership

Keep tests close to the stage they exercise:

- module-stage tests live under `modules/local/*/tests/`
- CLI- and fetch-specific tests stay in `bin/`
- shared pytest fixtures live in repo-root `conftest.py`

### Dependencies by stage

- normalize: `typer`, `pyyaml`, `pyarrow` (optional CUR parquet)
- aggregate: stdlib (+ Typer in wrapper)
- render: `jinja2`, `pyyaml`
- fetch: stdlib networking
