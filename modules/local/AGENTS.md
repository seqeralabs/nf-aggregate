# modules/local/ — Nextflow Processes

## benchmark_report_v2/ (active)

Python + DuckDB + eCharts report. Conda: `python=3.12 duckdb=1.3 jinja2=3.1 typer=0.15 pyarrow=18 pyyaml=6`.

**Inputs:** data_dir (collected run JSONs), aws_cur_report (optional parquet), brand_yml, logo_svg
**Outputs:** `benchmark_report.html`, `versions.yml`

Has nf-test at `tests/main.nf.test` with local test data fixtures in `tests/data/`.

## benchmark_report/ (legacy v1)

R/Quarto report. Container: `cr.seqera.io/scidev/benchmark-reports:sha-48cfed7`. Requires renv R library setup inside container. Controlled by `--generate_benchmark_report_legacy`.

**Inputs:** run_dumps (from SEQERA_RUNS_DUMP), groups, aws_cur_report, remove_failed_tasks
**Outputs:** `benchmark_report.html`, `versions.yml`

## seqera_runs_dump/

Tower CLI (`tw runs dump`) to fetch run data. Container: `seqeralabs/nf-aggregate:tower-cli-0.9.2`.

**Key:** `functions.nf` contains `getRunMetadata()` which pre-fetches workflow details (run name, work dir, fusion detection) using raw `URL.getText()` Groovy calls. This is the legacy equivalent of `SeqeraApi.groovy`.

Fusion detection: regex match `fusion\s*\{\\n\s*enabled\s*=\s*true` on `configText`.

## plot_run_gantt/

Fusion-only Gantt chart. Container: plotly/pandas/click stack. Only runs when `meta.fusion && !skip_run_gantt`.
