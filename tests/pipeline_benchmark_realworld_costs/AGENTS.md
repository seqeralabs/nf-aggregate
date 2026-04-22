# pipeline_benchmark_realworld_costs

## Purpose
Covers benchmark generation from real-world external run JSON directories plus a tiny filtered CUR parquet sidecar.

## Fixtures
- `workflows/nf_aggregate/assets/test_benchmark_realworld_costs.csv`
- JSON directories under `workflows/nf_aggregate/assets/realworld_log_dirs/`
- `workflows/nf_aggregate/assets/test_benchmark_realworld_costs.parquet`

## Expected behavior
- `EXTRACT_TARBALL` must not run.
- Benchmark stages should consume the external directories directly.
- The cost parquet should populate `jsonl_bundle/costs.jsonl` and aggregated `run_costs`.
- The synthetic red-herring row inside the parquet must not appear in `report_data.json` because it has no matching run JSON input.

## Edit guidance
If you change cost normalization, external-directory handling, or benchmark report aggregation, update this scenario along with the real-world fixture inputs.
