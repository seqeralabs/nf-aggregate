# PATTERNS.md — Codebase Conventions and Run Patterns

## Pipeline Architecture Patterns

### 1. Branch-and-Merge Input Strategy

The workflow uses `.branch {}` to split input into API vs external paths, then merges all JSON outputs via `.mix().collect()` before the benchmark pipeline. This pattern allows mixed-source runs in a single CSV.

```
ids.branch { api: ...; external: ... }
  → separate processing paths
  → ch_api_jsons.mix(ch_tarball_jsons).mix(ch_external_dir_jsons).collect()
```

### 2. In-Process API Fetch (No Task)

`SeqeraApi.fetchRunData()` runs inside the Nextflow process (Groovy), NOT as a Nextflow task. This means:

- No container, no retry directive, no task monitoring
- Retry logic is manually coded with exponential backoff (3 attempts)
- Token is read from environment at execution time
- Results are written to temp files and emitted as channel values

### 3. Three-Stage Python Pipeline

The benchmark report follows a strict data pipeline:

1. **Normalize** (raw JSON → JSONL bundle) — streaming, handles CUR parquet
2. **Aggregate** (JSONL → report_data.json) — statistical rollups
3. **Render** (report_data.json → HTML) — Jinja2 template + ECharts

Each stage is a separate Nextflow process with the same container image. The boundary between stages is explicit (JSONL files, then JSON), making debugging straightforward.

### 4. External Test Fixtures

Tests use pre-exported tarball fixtures (`workflows/nf_aggregate/assets/log_dirs/`, referenced from `test_benchmark.csv`) rather than live API calls. This enables fully offline CI.

## Coding Conventions

### Nextflow

- **DSL2** with `include {}` for all modules
- **No strict syntax yet** — uses `Channel.empty()`, implicit closures in places
- Processes use `conda` + `container` directives (Wave-compatible)
- All processes emit `versions.yml` for software version tracking
- `publishDir` configured per-process in `workflows/nf_aggregate/nextflow.config`

### Python (bin/)

- **Typer CLI** with subcommands for each pipeline stage
- Modular: `benchmark_report.py` is a thin dispatcher; logic lives in `benchmark_report_normalize.py`, `benchmark_report_aggregate.py`, `benchmark_report_render.py`, `benchmark_report_fetch.py`
- **JSONL** as intermediate format (streaming-friendly, Fusion-compatible)
- **Jinja2** for HTML templating with ECharts for charts
- **PyArrow** for CUR parquet reading (batched streaming for memory efficiency)
- Test runner: `pytest` with tests colocated under each module's `tests/` directory

### Testing

- **nf-test** for pipeline integration (4 test suites: benchmark-tarball, benchmark-directory, api-only, mixed-no-benchmark)
- **pytest** for Python unit tests (normalize, aggregate, render, fetch)
- **[nft-utils@0.0.4](mailto:nft-utils@0.0.4)** plugin for snapshot assertions
- Test config: `tests/nextflow.config` (intentionally empty — relies on profile `test`)
- Snapshots verify task counts, output file lists, and software versions

### Configuration

- Container registry: `quay.io` (default for all runtimes)
- Docker runs as current user: `-u $(id -u):$(id -g)`
- Process defaults: 1 CPU, 6 GB memory, 4h time
- Error strategy: retry on exit codes 130–145 and 104 (OOM/signal kills)

## Run Patterns (from Platform observations)

### Scheduling Overhead

Both observed runs show consistent 4–8 minute submit→start latency. This is a characteristic of AWS Batch with spot instances:

- Instance provisioning
- Container image pull (Wave-built images)
- S3 staging of inputs

### Instance Type Selection

AWS Batch auto-selects instance types based on resource requests:

- 1 CPU / 6 GB → m5d.large or c5d.large
- 2 CPU / 2 GB → c5d.large (compute-optimised)
- All spot pricing

### Cost Efficiency

Early QC tasks cost $0.001–$0.007 each. The dominant cost will come from STAR genome generation and alignment tasks (not yet observed in these in-progress runs).

## File Naming Conventions


| Pattern                | Convention                                  |
| ---------------------- | ------------------------------------------- |
| Modules                | `modules/local/<name>/main.nf`              |
| Module tests (Python)  | `modules/local/<name>/tests/test_<name>.py` |
| Module docs            | `modules/local/<name>/AGENTS.md`            |
| Pipeline tests         | `tests/<scenario>/main.nf.test`             |
| Pipeline test fixtures | `workflows/nf_aggregate/assets/`            |
| Bin scripts            | `bin/benchmark_report_<stage>.py`           |
| Agent docs             | `AGENTS.md` at each directory level         |


## Git Workflow

- Feature branches named `<user>/<description>`
- Conventional commits: `feat()`, `fix()`, `test()`, `refactor()`, `docs()`, `perf()`
- Commit signing required (GPG via SSH/1Password)
- Pre-commit hooks for linting

