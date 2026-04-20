# aggregate_benchmark_report_data

Purpose

- Convert the JSONL bundle into a single `report_data.json` document for rendering.

Owns

- `AGGREGATE_BENCHMARK_REPORT_DATA` in `main.nf`
- Python aggregation logic in `bin/benchmark_report_aggregate.py`
- Stage-scoped tests under `tests/`

Inputs

- `jsonl_bundle/` from `normalize_benchmark_jsonl`

Outputs

- `report_data.json`
- `versions.yml`

Invariants

- This is the boundary between streaming records and presentation data.
- Prefer streaming iteration over JSONL inputs; avoid full-file eager loads unless clearly bounded.
- Cost joins must key by `(run_id, process, hash)` to avoid cross-process collisions.
- Output keys should remain stable:
  - `benchmark_overview`
  - `run_summary`
  - `run_metrics`
  - `run_costs`
  - `process_stats`
  - `task_instance_usage`
  - `task_table`
  - `task_scatter`
  - `cost_overview`

Edit guidance

- Keep rendering/template logic out of this stage.
- If output schema changes, update render tests and any HTML assertions.

Tests

- `pytest modules/local/aggregate_benchmark_report_data/tests/test_aggregate.py -q`
