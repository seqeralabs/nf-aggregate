# pipeline_mixed_no_benchmark

## Purpose
Covers mixed input routing when benchmark generation is disabled.

## Fixtures
- `workflows/nf_aggregate/assets/test_mixed_no_benchmark.csv`

## Expected behavior
- API rows should be skipped with a warning.
- External tarball rows should still run through `EXTRACT_TARBALL`.
- Benchmark stages must not run (`NORMALIZE_BENCHMARK_JSONL`, `AGGREGATE_BENCHMARK_REPORT_DATA`, `RENDER_BENCHMARK_REPORT`).
- No `benchmark_report/` output should exist.

## Edit guidance
If you change branching logic between API and external logs, or benchmark gating for mixed inputs, update this test.
