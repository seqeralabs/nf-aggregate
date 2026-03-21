# benchmark_report (legacy v1)

R/Quarto benchmark report. **Legacy** — kept for backwards compat, controlled by `--generate_benchmark_report_legacy`.

## Process

**Container:** `cr.seqera.io/scidev/benchmark-reports:sha-48cfed7` (~2GB, R + renv + Quarto)

No conda spec — relies entirely on the pre-built container's renv library at `/project/renv/library/`.

### Inputs

| Input | Type | Description |
|---|---|---|
| `run_dumps` | path | Collected run dump directories from SEQERA_RUNS_DUMP |
| `groups` | val | Group labels matching each run dump |
| `benchmark_aws_cur_report` | path | Optional AWS CUR parquet |
| `remove_failed_tasks` | val | Boolean, filter out failed tasks |

### Outputs

- `benchmark_report.html` — Quarto-rendered report (~1.2MB)
- `versions.yml` — R + quarto-cli versions

### How It Works

1. Builds `benchmark_samplesheet.csv` mapping groups → dump paths
2. `cd /project && quarto render main_benchmark_report.qmd` with params
3. Copies output back to task dir

### Gotchas

- Container is pinned to a specific SHA — updating requires rebuilding `seqeralabs/benchmarking-reports`
- `R_LIBS_USER` hardcoded to container's renv path
- `QUARTO_CACHE` / `XDG_CACHE_HOME` set to `/tmp` to avoid permission issues
