# bin/ — CLI Scripts

Python scripts executed inside Nextflow process containers. Placed in `bin/` so Nextflow auto-adds them to `$PATH`.

## benchmark_report.py

Main report generator (~1135 lines). Typer CLI.

### Pipeline

```
load_brand(brand.yml) → load_run_data(*.json) → build_database(DuckDB) → query_*() → render_report(Jinja2+eCharts)
```

### Key Functions

| Function | Purpose |
|---|---|
| `load_brand()` | Parse `assets/brand.yml` → flat color map with defaults |
| `build_database()` | Load run JSONs → DuckDB tables: `runs`, `tasks`, `metrics`, `costs` |
| `query_benchmark_overview()` | Grouped bars: wall time, cost, CPU time per group |
| `query_run_summary()` | Summary table of all runs |
| `query_run_metrics()` | Per-run metrics: duration, CPU time, read/write |
| `query_run_costs()` | Cost data per run (requires AWS CUR) |
| `query_process_stats()` | Runtime/memory/cost per process (mean ± SD) |
| `query_task_instance_usage()` | Machine type distribution per group |
| `query_task_table()` | Full task-level data table |
| `query_task_scatter()` | Realtime vs staging scatter data |
| `query_cost_overview()` | Process-level cost breakdown (if costs table exists) |
| `render_report()` | Jinja2 HTML with embedded eCharts JS |

### CLI Flags

- `--data-dir` — directory of run JSON files
- `--costs` — optional AWS CUR parquet
- `--brand` — brand.yml for colors
- `--logo` — SVG logo file
- `--output` — output HTML path
- `--theme` — eCharts theme JSON

### Dependencies

`duckdb`, `jinja2`, `typer`, `pyyaml`, `pyarrow` — no pandas/numpy.

### Brand System

Colors flow: `brand.yml` → `load_brand()` defaults → Jinja template variables → eCharts theme. No hardcoded hex values in the template. Green-dominant palette: `#31C9AC`, `#087F68`, `#201637`, `#0BB392`, `#055C4B`, `#50E3C2`, `#CFD0D1`, `#8A8B8C`.

### Editing Tips

- HTML template is a Jinja2 string inside `render_report()` — not a separate file
- Chart configs use `echarts.init(el, 'seqera')` theme — don't add inline color overrides
- Data injected as `const DATA = {{ data_json }};` — all query results are JSON blobs
- `COLORS` array is the brand palette, referenced by index in chart series

## plot_run_gantt.py

Fusion-only Gantt chart. Reads `workflow-tasks.json` + `.fusion.log` from dump directory. Groups tasks by instance ID + machine type. pandas + plotly_express timeline. Only runs for fusion-enabled workflows.
