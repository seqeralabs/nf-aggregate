# nf-aggregate

Nextflow pipeline to aggregate metrics across Seqera Platform pipeline runs. nf-core template based (v3.3.0.dev0).

## Architecture

```
input CSV (id, workspace, group)
  → SeqeraApi.fetchRunData() in map{} (4 API calls/run: workflow, metrics, tasks, progress)
  → collect JSON files
  → BENCHMARK_REPORT process (Python + DuckDB + eCharts)
  → benchmark_report.html (~70KB self-contained)
```

Additional paths (always active):
- `SEQERA_RUNS_DUMP` (tower-cli) → run dump dirs → `MULTIQC` + `PLOT_RUN_GANTT`

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

- `TOWER_ACCESS_TOKEN` — Seqera Platform API token (forwarded via `env {}` block in nextflow.config)

## Rebuild Command (local testing)

```bash
# New decomposed pipeline:
uv run --with duckdb --with typer --with pyyaml python bin/clean_json.py \
  --data-dir modules/local/benchmark_report/tests/data --output-dir /tmp/cleaned
uv run --with duckdb --with typer python bin/build_tables.py \
  --runs-csv /tmp/cleaned/runs.csv --tasks-csv /tmp/cleaned/tasks.csv \
  --metrics-csv /tmp/cleaned/metrics.csv --output-dir /tmp/tables
uv run --with jinja2 --with typer --with pyyaml python bin/render_report.py \
  --tables-dir /tmp/tables --brand assets/brand.yml --output /tmp/benchmark_report.html

# Legacy monolithic (still works):
uv run --with duckdb --with jinja2 --with typer --with pyyaml --with pyarrow \
  python bin/benchmark_report.py \
  --data-dir modules/local/benchmark_report/tests/data \
  --brand assets/brand.yml \
  --output /tmp/benchmark_report.html
```

## Gotchas

- Wave freeze strategy: `['conda', 'container', 'dockerfile']` — no `spack` (breaks builds)
- DuckDB `read_json_auto` needs file paths, not JSON strings — use temp files
- `commit.gpgsign` must be true (SSH signing via 1Password)
- RTK `buildOutputFiltering` / `testOutputAggregation` can swallow nf-test output — disable to debug
