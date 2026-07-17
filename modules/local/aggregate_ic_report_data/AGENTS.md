# aggregate_ic_report_data

Aggregates the shared JSONL bundle into `report_data_ic.json` for the Intelligent Compute report. Auto-detects `compute_type` (schedEnabled/platform_id), reuses `_build_workspace_run_url`, and leaves the core-report `cost` column null. Logic in `bin/benchmark_report_ic_aggregate.py`; entrypoint `aggregate_ic_report_data.py` (top-level `bin/`).

Per-run cost prefers ECS split cost allocation: when a run's CUR rows carry genuine
split cost (any `split_cost_present`), `run_summary[].cost_basis` is `split` and
`used_cost`/`unused_cost` (used vs idle capacity) are populated; otherwise it falls back
to `blended` and both are null. `cost` is always the billed total (used + unused).
`cost_status` explains availability — `available`, `propagating` (CUR supplied, run
finished < `_COST_PROPAGATION_WINDOW_HOURS` ago, likely not landed yet), `not_found`
(CUR supplied but genuinely unmatched), or null (no CUR at all). `ic_overview` carries
`cur_supplied` plus `n_runs_with_cost`/`n_runs_split_cost`/`n_runs_blended_cost`/
`n_runs_missing_cost` for the report's cost-coverage note.
