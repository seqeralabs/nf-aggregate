# aggregate_ic_report_data

Aggregates the shared JSONL bundle into `report_data_ic.json` for the Intelligent Compute report. Auto-detects `compute_type` (schedEnabled/platform_id), reuses `_build_workspace_run_url`, and leaves the core-report `cost` column null. Logic in `bin/benchmark_report_ic_aggregate.py`; entrypoint `aggregate_ic_report_data.py` (top-level `bin/`).

**Two cost bases, never summed.** AWS emits ECS split cost allocation rows *in addition to*
the parent EC2 instance rows they were derived from, so the two describe the same compute.
Because Intelligent Compute tags the instances themselves, an IC run on the ECS architecture
matches both classes; summing them overstated affected runs by ~1.5x (median, measured on a
real export). AWS Batch tags only the task, so its instance rows carry no run tag and it was
never affected. See `_normalize_cost_rows` for the row-level detail.

So each run carries both figures side by side, each on a FIXED basis that never substitutes
for the other — a blank cell means that basis does not exist for the run, not that cost data is
missing:

- `cost` — the billed EC2 machine charge (`line_item_unblended_cost`). **Null for AWS Batch**,
  which labels only its ECS tasks: its machine rows carry no run tag, so no billed charge can be
  attributed to the run.
- `comparable_cost` — the ECS split basis (`used_cost` + `unused_cost`). **Null for Intelligent
  Compute on the VM architecture**, which runs no ECS tasks for AWS to split. This is the only
  basis AWS Batch reports, so cross-engine comparisons use it and runs without one are excluded
  from the comparison charts rather than compared on different terms (split cost is amortized,
  the billed charge is not).
- `used_cost`/`unused_cost` — consumed vs provisioned-but-idle capacity, populated only when
  split cost allocation is present.

An IC run on ECS is the only shape carrying both. There is deliberately no `cost_basis` field:
each column *is* a basis, so a per-run label would be a constant.

`cost_status` explains availability — `available`, `propagating` (CUR supplied, run
finished < `_COST_PROPAGATION_WINDOW_HOURS` ago, likely not landed yet), `not_found`
(CUR supplied but genuinely unmatched), or null (no CUR at all). `ic_overview` carries
`cur_supplied` plus `n_runs_with_cost`/`n_runs_billed_cost`/`n_runs_comparable_cost`/
`n_runs_missing_cost` for the report's cost-coverage note.
