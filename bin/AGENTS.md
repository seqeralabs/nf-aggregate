# bin/ — CLI Scripts

Python scripts executed inside Nextflow process containers. Placed in `bin/` so Nextflow auto-adds them to `$PATH`.

## benchmark_report.py

Unified benchmark report CLI. Typer app with 3 subcommands:

| Subcommand | Purpose |
|---|---|
| `build-db` | JSON files (+ optional CUR parquet) → `benchmark.duckdb` with normalized tables (runs, tasks, metrics, costs) |
| `report` | Opens `.duckdb` file → runs 9 SQL queries → renders self-contained HTML with eCharts |
| `fetch` | Calls Seqera Platform API → writes run JSON files (standalone use, not used by Nextflow pipeline) |

### DuckDB Tables

- `runs` — one row per workflow run (id, group, pipeline, status, duration, efficiency, etc.)
- `tasks` — one row per task (hash, process, cost, cpus, memory, realtime, etc.)
- `metrics` — per-process resource stats (cpu/mem/time mean/min/q1-q3/max)
- `costs` — optional, from AWS CUR parquet (run_id, process, hash, cost, used_cost, unused_cost)

### Dependencies

`duckdb`, `jinja2`, `typer`, `pyyaml`, `pyarrow`, `httpx` (fetch only)
