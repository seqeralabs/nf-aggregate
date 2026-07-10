# aggregate_ic_report_data

Aggregates the shared JSONL bundle into `report_data_ic.json` for the Intelligent Compute report. Auto-detects `compute_type` (schedEnabled/platform_id), reuses `_build_workspace_run_url`, and leaves the core-report `cost` column null. Logic in `bin/benchmark_report_ic_aggregate.py`; entrypoint `aggregate_ic_report_data.py` (top-level `bin/`).
