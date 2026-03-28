# benchmark_report

Python + DuckDB + eCharts benchmark report.

## Process

**Conda:** `python=3.12 duckdb=1.3 jinja2=3.1 typer=0.15 pyarrow=18 pyyaml=6`
**Container:** `ghcr.io/seqeralabs/nf-agg:python-duckdb`

### Inputs

| Input                      | Type | Description                                                             |
| -------------------------- | ---- | ----------------------------------------------------------------------- |
| `data_dir`                 | path | Directory of per-run JSON files (collected from SeqeraApi.fetchRunData) |
| `benchmark_aws_cur_report` | path | Optional AWS CUR parquet for cost analysis                              |
| `brand_yml`                | path | `assets/brand.yml` — brand color definitions                            |
| `logo_svg`                 | path | `assets/seqera_logo_color.svg` — Seqera logo                            |

### Outputs

- `benchmark_report.html` — self-contained eCharts HTML (~70KB)
- `versions.yml` — python + duckdb versions for MultiQC

### Invocation

Calls `bin/benchmark_report.py` with `--data-dir`, `--costs`, `--brand`, `--logo`, `--output` flags. See `bin/AGENTS.md` for the full function map.

## Tests

`tests/main.nf.test` — nf-test using local fixtures in `tests/data/`. Asserts process success, output file exists, and contains "Pipeline benchmarking report".

```bash
nf-test test modules/local/benchmark_report/tests/main.nf.test
```
