# nf-aggregate

Nextflow pipeline to aggregate metrics across Seqera Platform pipeline runs. nf-core template based (v3.3.0.dev0).

## Architecture

```
input CSV (id, workspace, group, logs, fusion)
  → branch: api (SeqeraApi.fetchRunData) | external (EXTRACT_TARBALL)
  → collect JSON files
  → BENCHMARK_REPORT process (benchmark_report.py build-db + report)
  → benchmark.duckdb + benchmark_report.html
```

## Key Params

| Param                       | Default                       | Purpose                           |
| --------------------------- | ----------------------------- | --------------------------------- |
| `generate_benchmark_report` | false                         | Enable benchmark report           |
| `benchmark_aws_cur_report`  | null                          | AWS CUR parquet for cost analysis |
| `seqera_api_endpoint`       | `https://api.cloud.seqera.io` | Platform API URL                  |

## Plugins

- `nf-schema@2.3.0` — param validation, samplesheet parsing
- `nf-boost@0.6.0` — `request()`, `fromJson`/`toJson` for API calls

## Env Requirements

- `TOWER_ACCESS_TOKEN` — Seqera Platform API token (forwarded via `env {}` block in nextflow.config)

## Rebuild Command (local testing)

```bash
# Build DuckDB from JSON data:
uv run --with duckdb --with typer --with pyyaml --with pyarrow \
  python bin/benchmark_report.py build-db \
  --data-dir /path/to/json_data --output /tmp/benchmark.duckdb

# Render HTML report from DuckDB:
uv run --with duckdb --with jinja2 --with typer --with pyyaml \
  python bin/benchmark_report.py report \
  --db /tmp/benchmark.duckdb --brand assets/brand.yml --output /tmp/report.html

# Fetch run data from Seqera Platform API (standalone):
uv run --with duckdb --with typer --with pyyaml --with httpx \
  python bin/benchmark_report.py fetch \
  --run-ids <id> --workspace org/name --output-dir /tmp/json_data
```

## Gotchas

- Wave freeze strategy: `['conda', 'container', 'dockerfile']` — no `spack` (breaks builds)
- DuckDB `read_json_auto` needs file paths, not JSON strings — use temp files
- `commit.gpgsign` must be true (SSH signing via 1Password)
- RTK `buildOutputFiltering` / `testOutputAggregation` can swallow nf-test output — disable to debug
