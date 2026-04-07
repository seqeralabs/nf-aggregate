# pipeline_benchmark_directory

## Purpose
Covers benchmark generation when external logs are provided as an already-extracted directory.

## Fixtures
- `workflows/nf_aggregate/assets/test_benchmark_directory.csv`
- JSON fixture directory under `workflows/nf_aggregate/assets/log_dirs/`

## Expected behavior
- `EXTRACT_TARBALL` must not run.
- `BENCHMARK_REPORT` should consume the directory directly.
- Benchmark outputs should include both HTML and DuckDB artifacts.
- The rendered HTML should mention the expected run ID and group.

## Edit guidance
If you change support for directory-based external logs, update this test first.
