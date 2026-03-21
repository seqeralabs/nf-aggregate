# nf-aggregate

Nextflow pipeline to aggregate metrics across Seqera Platform pipeline runs. nf-core template based (v3.3.0.dev0).

## Architecture

Two parallel reporting paths:

1. **v2 (active)** — `generate_benchmark_report`: nf-boost `request()` → SeqeraApi.groovy → DuckDB → eCharts HTML
2. **v1 (legacy)** — `generate_benchmark_report_legacy`: tower-cli `tw runs dump` → R/Quarto/renv → HTML

Both coexist. v2 is the primary path going forward.

## Data Flow (v2)

```
input CSV (id, workspace, group)
  → SeqeraApi.fetchRunData() in map{} (4 API calls/run: workflow, metrics, tasks, progress)
  → collect JSON files
  → BENCHMARK_REPORT_V2 process (Python + DuckDB + eCharts)
  → benchmark_report.html (~70KB self-contained)
```

## Data Flow (legacy v1 + MultiQC)

```
input CSV → SEQERA_RUNS_DUMP (tower-cli) → run dump dirs
  → BENCHMARK_REPORT (R/Quarto, ~2GB container)
  → PLOT_RUN_GANTT (fusion-only runs, plotly)
  → MULTIQC (aggregate all run metrics)
```

## Key Params

| Param | Default | Purpose |
|---|---|---|
| `generate_benchmark_report` | false | Enable v2 benchmark report |
| `generate_benchmark_report_legacy` | false | Enable v1 R/Quarto report |
| `benchmark_aws_cur_report` | null | AWS CUR parquet for cost analysis |
| `seqera_api_endpoint` | `https://api.cloud.seqera.io` | Platform API URL |
| `skip_run_gantt` | false | Skip Gantt chart generation |
| `skip_multiqc` | false | Skip MultiQC aggregation |

## Plugins

- `nf-schema@2.3.0` — param validation, samplesheet parsing
- `nf-boost@0.6.0` — `request()`, `fromJson`/`toJson` for API calls

## Env Requirements

- `TOWER_ACCESS_TOKEN` — Seqera Platform API token (forwarded via `env {}` block in nextflow.config)

## Branch: `small-nf`

Active development branch. Contains the v2 rewrite + brand enforcement work.

## Rebuild Command (local testing)

```bash
uv run --with duckdb --with jinja2 --with typer --with pyyaml --with pyarrow \
  python bin/benchmark_report.py \
  --data-dir modules/local/benchmark_report_v2/tests/data \
  --brand assets/brand.yml \
  --output /tmp/benchmark_report.html
```

## Gotchas

- Wave freeze strategy: `['conda', 'container', 'dockerfile']` — no `spack` (breaks builds)
- DuckDB `read_json_auto` needs file paths, not JSON strings — use temp files
- `commit.gpgsign` must be true (SSH signing via 1Password)
- RTK `buildOutputFiltering` / `testOutputAggregation` can swallow nf-test output — disable to debug
