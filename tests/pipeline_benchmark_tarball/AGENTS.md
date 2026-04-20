# pipeline_benchmark_tarball

## Purpose

Covers benchmark generation when external logs are supplied as tarballs.

## Fixtures

- `workflows/nf_aggregate/assets/test_benchmark.csv`
- tarballs under `workflows/nf_aggregate/assets/logs/`

## Expected behavior

- `EXTRACT_TARBALL` should run for each external input.
- Benchmark stages should run once after collection:
  - `NORMALIZE_BENCHMARK_JSONL`
  - `AGGREGATE_BENCHMARK_REPORT_DATA`
  - `RENDER_BENCHMARK_REPORT`
- Benchmark outputs should include `jsonl_bundle/`, `report_data.json`, and HTML artifacts.
- The rendered HTML should mention the expected run IDs and groups.

## Edit guidance

If you change tarball extraction, benchmark aggregation, or HTML report content, update this test.
