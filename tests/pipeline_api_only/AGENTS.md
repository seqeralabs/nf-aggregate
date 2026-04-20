# pipeline_api_only

## Purpose

Covers the API-only input path when `generate_benchmark_report` is disabled.

## Fixtures

- `workflows/nf_aggregate/assets/test_run_ids.csv`

## Expected behavior

- No Nextflow processes should run.
- A warning should explain that API runs produce no output without benchmark generation.
- Only `pipeline_info/collated_software_versions.yml` should be emitted.
- No `benchmark_report/` directory should exist.

## Edit guidance

If you change API-only routing, benchmark gating, or warning text, update this test first.
