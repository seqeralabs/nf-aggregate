# normalize_benchmark_jsonl

Purpose

- Normalize collected run JSON into a stream-friendly `jsonl_bundle/`.

Owns

- `NORMALIZE_BENCHMARK_JSONL` in `main.nf`
- Python stage logic in `bin/benchmark_report_normalize.py`
- Stage-scoped tests under `tests/`

Inputs

- `data_dir/` of per-run JSON payloads
- optional CUR parquet

Outputs

- `jsonl_bundle/runs.jsonl`
- `jsonl_bundle/tasks.jsonl`
- `jsonl_bundle/metrics.jsonl`
- optional `jsonl_bundle/costs.jsonl`
- `versions.yml`

Invariants

- JSONL is the handoff format for Fusion-friendly streaming.
- One JSON object per line.
- Task rows should already include derived fields needed downstream (`process_short`, `wait_ms`, `staging_ms`).
- Failed tasks are filtered here so downstream stages stay simple.

Edit guidance

- Keep this stage about normalization only; no report aggregation or HTML concerns.
- If you change row shape, update:
  - `bin/benchmark_report_normalize.py`
  - `modules/local/aggregate_benchmark_report_data/tests/test_aggregate.py`
  - any CLI compatibility tests affected

Tests

- `pytest modules/local/normalize_benchmark_jsonl/tests/test_normalize.py -q`
