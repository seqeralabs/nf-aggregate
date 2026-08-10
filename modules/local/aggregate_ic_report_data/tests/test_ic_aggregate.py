import json

from benchmark_report_ic_aggregate import _compute_type, build_ic_report_data
from benchmark_report_normalize import normalize_jsonl


def _bundle(tmp_path, runs, write_run_json):
    data_dir = tmp_path / "data"
    jsonl_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, runs)
    normalize_jsonl(data_dir, jsonl_dir)
    return jsonl_dir


def test_ic_report_shape_and_detection(tmp_path, make_ic_run, make_batch_run, write_run_json):
    jsonl_dir = _bundle(tmp_path, [make_ic_run(), make_batch_run()], write_run_json)
    data = build_ic_report_data(jsonl_dir, web_base="https://cloud.example.test")

    assert set(data.keys()) == {"ic_overview", "run_summary", "machine_usage"}
    assert data["ic_overview"] == {
        "n_runs": 2, "n_intelligent_compute": 1, "n_batch": 1, "cost_source": None,
        "cur_supplied": False, "n_runs_with_cost": 0, "n_runs_billed_cost": 0,
        "n_runs_comparable_cost": 0, "n_runs_missing_cost": 0,
    }
    assert {r["compute_type"] for r in data["run_summary"]} == {"intelligent_compute", "batch"}


def test_resource_usage_matches_scheduler_basis(tmp_path, make_run, write_run_json):
    # Reproduces the IC scheduler Metrics panel: CPU = Σ(resource × OCCUPANCY hours) in vCPU-h;
    # memory = plain Σ(task memory) in GiB (NOT time-weighted). Verified to the decimal against
    # the Platform UI on real mcmicro runs.
    # t1 (occupancy 2h): request 4 cores / 8 GiB, use 2 cores (pcpu 200) / 2 GiB RSS.
    # t2 (occupancy 1h): request 2 cores / 4 GiB, use 1 core  (pcpu 100) / 1 GiB RSS.
    tasks = [
        {"name": "t1", "process": "P:t1", "status": "COMPLETED", "hash": "aa/01", "cpus": 4,
         "memory": 8 * 1024**3, "realtime": 7_200_000, "pcpu": 200.0, "peakRss": 2 * 1024**3,
         "machineType": "t3.large", "start": "2026-01-01T00:00:00Z", "complete": "2026-01-01T02:00:00Z"},
        {"name": "t2", "process": "P:t2", "status": "COMPLETED", "hash": "aa/02", "cpus": 2,
         "memory": 4 * 1024**3, "realtime": 3_600_000, "pcpu": 100.0, "peakRss": 1 * 1024**3,
         "machineType": "t3.large", "start": "2026-01-01T00:00:00Z", "complete": "2026-01-01T01:00:00Z"},
    ]
    jsonl_dir = _bundle(tmp_path, [make_run(run_id="r1", tasks=tasks)], write_run_json)
    row = build_ic_report_data(jsonl_dir)["run_summary"][0]

    assert row["req_cpu_vcpu_h"] == 10.0  # 4×2h + 2×1h  (occupancy, not realtime)
    assert row["eff_cpu_vcpu_h"] == 5.0   # 2×2h + 1×1h
    assert row["req_mem_gib"] == 12.0     # 8 + 4        (summed, NO time weighting)
    assert row["eff_mem_gib"] == 3.0      # 2 + 1
    # efficiency removed entirely
    assert "cpu_efficiency" not in row and "mem_efficiency" not in row


def test_resource_usage_cpu_from_occupancy_not_realtime(tmp_path, make_run, write_run_json):
    # A task with NO realtime still contributes CPU vCPU-h via its occupancy window (start→
    # complete), matching the scheduler's slot-held-time basis. Absent memory/pcpu -> 0.
    task = {"name": "t", "process": "P:t", "status": "COMPLETED", "hash": "aa/01", "cpus": 4,
            "start": "2026-01-01T00:00:00Z", "complete": "2026-01-01T00:30:00Z", "machineType": "t3.large"}
    jsonl_dir = _bundle(tmp_path, [make_run(run_id="r1", tasks=[task])], write_run_json)
    row = build_ic_report_data(jsonl_dir)["run_summary"][0]
    assert row["req_cpu_vcpu_h"] == 2.0   # 4 cpus × 0.5h occupancy
    assert row["eff_cpu_vcpu_h"] == 0.0   # no pcpu
    assert row["req_mem_gib"] == 0.0      # no memory requested
    assert row["eff_mem_gib"] == 0.0      # no peak RSS


def test_machine_usage_grouped_by_run(tmp_path, make_ic_run, make_batch_run, write_run_json):
    jsonl_dir = _bundle(tmp_path, [make_ic_run(), make_batch_run()], write_run_json)
    usage = build_ic_report_data(jsonl_dir)["machine_usage"]

    # one entry per run, same order as run_summary (IC first, then Batch)
    assert [u["run_id"] for u in usage] == ["icRUN0000000001", "batchRUN00000001"]
    ic, batch = usage

    assert ic["compute_type"] == "intelligent_compute"
    assert ic["total_tasks"] == 4
    assert ic["total_cpu_hours"] == 4.0  # 4 tasks x (2 cpus * 0.5h)
    # ordered by task_count desc, tie broken by machine_type asc
    assert [(m["machine_type"], m["task_count"], m["task_pct"]) for m in ic["machines"]] == [
        ("t3.large", 2, 50.0), ("t3a.xlarge", 1, 25.0), ("unknown", 1, 25.0),
    ]
    assert ic["machines"][0]["cpu_hours"] == 2.0

    # empty machineType is bucketed as "unknown"
    assert "unknown" in {m["machine_type"] for m in batch["machines"]}

    # same machine type => same color index across runs (t3.large appears in both)
    ic_t3 = next(m["color_idx"] for m in ic["machines"] if m["machine_type"] == "t3.large")
    batch_t3 = next(m["color_idx"] for m in batch["machines"] if m["machine_type"] == "t3.large")
    assert ic_t3 == batch_t3


def test_run_timing_metrics(tmp_path, make_ic_run, write_run_json):
    jsonl_dir = _bundle(tmp_path, [make_ic_run()], write_run_json)
    row = build_ic_report_data(jsonl_dir)["run_summary"][0]
    # wall time = run-level duration (submit -> complete), straight from the workflow
    assert row["wall_time_ms"] == 1717531
    # total run time = sum of task start->complete: 4 tasks x 30 min = 7,200,000 ms
    assert row["total_run_time_ms"] == 4 * 30 * 60 * 1000
    # staging = runtime - realtime, summed & clamped >= 0; never exceeds total run time
    assert 0 <= row["total_staging_time_ms"] <= row["total_run_time_ms"]


def test_machine_usage_empty_when_no_tasks(tmp_path, make_ic_run, write_run_json):
    run = make_ic_run()
    run["tasks"] = []
    jsonl_dir = _bundle(tmp_path, [run], write_run_json)
    usage = build_ic_report_data(jsonl_dir)["machine_usage"]
    assert len(usage) == 1
    assert usage[0]["total_tasks"] == 0
    assert usage[0]["machines"] == []


def test_ic_run_summary_fields(tmp_path, make_ic_run, write_run_json):
    jsonl_dir = _bundle(tmp_path, [make_ic_run(run_id="icRUN0000000001")], write_run_json)
    data = build_ic_report_data(jsonl_dir, web_base="https://cloud.example.test")
    row = data["run_summary"][0]

    assert row["run_id"] == "icRUN0000000001"
    assert row["compute_type"] == "intelligent_compute"
    assert row["run_url"] == (
        "https://cloud.example.test/orgs/myorg/workspaces/myworkspace/watch/icRUN0000000001"
    )
    # occupancy basis: 4 tasks x (2 cpus * 0.5h held) = 4.0 cpu-h
    assert row["compute_hours"] == 4.0
    assert row["memory_used_bytes"] == 12339093504
    assert row["memory_used_gb"] == round(12339093504 / 1024**3, 2)
    assert row["run_cost_platform"] == 0.0053921835
    assert row["cost"] is None


def test_compute_hours_reconciles_with_machine_usage(tmp_path, make_ic_run, make_batch_run, write_run_json):
    """The per-run 'compute hours' must equal the sum of that run's per-machine cpu-hours."""
    jsonl_dir = _bundle(tmp_path, [make_ic_run(), make_batch_run()], write_run_json)
    data = build_ic_report_data(jsonl_dir)

    machine_totals = {u["run_id"]: u["total_cpu_hours"] for u in data["machine_usage"]}
    for row in data["run_summary"]:
        summed = round(sum(m["cpu_hours"] for m in
                           next(u for u in data["machine_usage"] if u["run_id"] == row["run_id"])["machines"]), 2)
        assert row["compute_hours"] == machine_totals[row["run_id"]] == summed


def test_batch_detected_when_sched_absent(tmp_path, make_batch_run, write_run_json):
    jsonl_dir = _bundle(tmp_path, [make_batch_run()], write_run_json)
    assert build_ic_report_data(jsonl_dir)["run_summary"][0]["compute_type"] == "batch"


def test_compute_type_platform_id_fallback():
    assert _compute_type({"sched_enabled": False, "platform_id": "aws-cloud"}) == "intelligent_compute"
    assert _compute_type({"sched_enabled": False, "platform_id": "aws-batch"}) == "batch"
    assert _compute_type({"sched_enabled": True, "platform_id": "aws-batch"}) == "intelligent_compute"


def test_run_summary_carries_start_time(tmp_path, make_ic_run, write_run_json):
    run = make_ic_run(run_id="icRUN0000000001")
    run["workflow"]["start"] = "2026-07-12T22:29:38Z"
    jsonl_dir = _bundle(tmp_path, [run], write_run_json)
    data = build_ic_report_data(jsonl_dir)

    row = data["run_summary"][0]
    assert row["started_at"] == "2026-07-12T22:29:38Z"
    assert row["date_short"] == "2026-07-12"
    # machine_usage carries the same fields for the chart
    assert data["machine_usage"][0]["started_at"] == "2026-07-12T22:29:38Z"
    assert data["machine_usage"][0]["date_short"] == "2026-07-12"


def test_missing_start_is_blank_not_crash(tmp_path, make_ic_run, write_run_json):
    run = make_ic_run()  # fixture sets no workflow.start
    run["workflow"].pop("start", None)
    jsonl_dir = _bundle(tmp_path, [run], write_run_json)
    row = build_ic_report_data(jsonl_dir)["run_summary"][0]
    assert row["started_at"] == ""
    assert row["date_short"] == ""


def test_runs_sorted_newest_first_within_pipeline_and_facet(tmp_path, make_ic_run, make_batch_run, write_run_json):
    old_ic = make_ic_run(run_id="icOLD0000001")
    old_ic["workflow"]["start"] = "2026-07-03T10:00:00Z"
    new_ic = make_ic_run(run_id="icNEW0000001")
    new_ic["workflow"]["start"] = "2026-07-12T10:00:00Z"
    batch = make_batch_run(run_id="batchRUN00001")
    batch["workflow"]["start"] = "2026-07-05T10:00:00Z"

    # deliberately shuffled input order
    jsonl_dir = _bundle(tmp_path, [old_ic, batch, new_ic], write_run_json)
    data = build_ic_report_data(jsonl_dir)

    # IC facet first (newest -> oldest), then Batch; machine_usage mirrors the order
    assert [r["run_id"] for r in data["run_summary"]] == ["icNEW0000001", "icOLD0000001", "batchRUN00001"]
    assert [u["run_id"] for u in data["machine_usage"]] == ["icNEW0000001", "icOLD0000001", "batchRUN00001"]


def test_failed_runs_excluded_by_default(tmp_path, make_ic_run, write_run_json):
    """A FAILED workflow is dropped from the report by default; cancelled always dropped."""
    ok = make_ic_run(run_id="icOK000000001")
    failed = make_ic_run(run_id="icFAIL0000001")
    failed["workflow"]["status"] = "FAILED"
    cancelled = make_ic_run(run_id="icCANCEL00001")
    cancelled["workflow"]["status"] = "CANCELLED"
    jsonl_dir = _bundle(tmp_path, [ok, failed, cancelled], write_run_json)

    data = build_ic_report_data(jsonl_dir)
    assert [r["run_id"] for r in data["run_summary"]] == ["icOK000000001"]
    assert [u["run_id"] for u in data["machine_usage"]] == ["icOK000000001"]
    assert data["ic_overview"]["n_runs"] == 1
    assert data["ic_overview"]["n_intelligent_compute"] == 1


def test_failed_runs_included_with_flag(tmp_path, make_ic_run, write_run_json):
    """include_failed_runs=True keeps FAILED runs (and their CUR cost); cancelled still dropped."""
    ok = make_ic_run(run_id="icOK000000001")
    failed = make_ic_run(run_id="icFAIL0000001")
    failed["workflow"]["status"] = "FAILED"
    cancelled = make_ic_run(run_id="icCANCEL00001")
    cancelled["workflow"]["status"] = "CANCELLED"
    jsonl_dir = _bundle(tmp_path, [ok, failed, cancelled], write_run_json)
    (jsonl_dir / "costs.jsonl").write_text(
        json.dumps({"run_id": "icFAIL0000001", "process": "FOO", "hash": "abcd1234", "unblended_cost": 4.0}) + "\n"
    )

    data = build_ic_report_data(jsonl_dir, include_failed_runs=True)
    run_ids = {r["run_id"] for r in data["run_summary"]}
    assert run_ids == {"icOK000000001", "icFAIL0000001"}  # cancelled still excluded
    failed_row = next(r for r in data["run_summary"] if r["run_id"] == "icFAIL0000001")
    assert failed_row["cost"] == 4.0


def test_run_cost_none_without_cur(tmp_path, make_ic_run, write_run_json):
    """No CUR export -> run costs stay empty (never the Seqera estimate)."""
    jsonl_dir = _bundle(tmp_path, [make_ic_run(run_id="icRUN0000000001")], write_run_json)
    data = build_ic_report_data(jsonl_dir)
    assert data["ic_overview"]["cost_source"] is None
    assert all(r["cost"] is None for r in data["run_summary"])


def test_run_cost_summed_from_cur_costs_jsonl(tmp_path, make_ic_run, write_run_json):
    """When a CUR export is present, per-run cost is the sum of its task-grained rows."""
    jsonl_dir = _bundle(tmp_path, [make_ic_run(run_id="icRUN0000000001")], write_run_json)
    # costs.jsonl is written by the normalize step from the CUR parquet; simulate two
    # task-grained rows for one run that must sum to a single per-run cost.
    (jsonl_dir / "costs.jsonl").write_text(
        json.dumps({"run_id": "icRUN0000000001", "process": "FOO", "hash": "abcd1234", "unblended_cost": 1.25}) + "\n"
        + json.dumps({"run_id": "icRUN0000000001", "process": "BAR", "hash": "ef567890", "unblended_cost": 2.5}) + "\n"
        # a cost row for an unrelated run must not leak onto our run
        + json.dumps({"run_id": "otherRUN", "process": "BAZ", "hash": "00000000", "unblended_cost": 9.0}) + "\n"
    )
    data = build_ic_report_data(jsonl_dir)
    assert data["ic_overview"]["cost_source"] == "aws_cur"
    row = next(r for r in data["run_summary"] if r["run_id"] == "icRUN0000000001")
    assert row["cost"] == 3.75


def _write_costs(jsonl_dir, rows):
    jsonl_dir.joinpath("costs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_ic_run_cost_never_sums_instance_and_split_bases(tmp_path, make_ic_run, write_run_json):
    """An IC run on ECS has both bases; they must be reported side by side, never added.

    $10.00 billed on the instances, split rows re-expressing $6.00 of it. The cost of record
    is the $10.00 actually billed; the comparable figure is the $6.00 split basis. The old
    behaviour summed them to $16.00, overstating affected runs by ~1.5x.
    """
    jsonl_dir = _bundle(tmp_path, [make_ic_run(run_id="icRUN0000000001")], write_run_json)
    _write_costs(jsonl_dir, [
        # Parent EC2 instance rows: no per-task labels, so they group under an empty process.
        {"run_id": "icRUN0000000001", "process": "", "hash": "",
         "unblended_cost": 10.0, "split_cost": 0.0, "unused_cost": 0.0,
         "split_cost_present": False},
        # ECS split rows for tasks that ran on those same instances.
        {"run_id": "icRUN0000000001", "process": "FOO", "hash": "abcd1234",
         "unblended_cost": 0.0, "split_cost": 3.0, "unused_cost": 1.0,
         "split_cost_present": True},
        {"run_id": "icRUN0000000001", "process": "BAR", "hash": "ef567890",
         "unblended_cost": 0.0, "split_cost": 1.5, "unused_cost": 0.5,
         "split_cost_present": True},
    ])
    data = build_ic_report_data(jsonl_dir)
    row = next(r for r in data["run_summary"] if r["run_id"] == "icRUN0000000001")
    assert row["cost"] == 10.0             # billed machine charge, not 16.0
    assert row["comparable_cost"] == 6.0   # split basis kept separate for comparison
    assert row["used_cost"] == 4.5         # consumed capacity, summed across split rows
    assert row["unused_cost"] == 1.5
    assert row["cost_status"] == "available"
    assert data["ic_overview"]["n_runs_billed_cost"] == 1
    assert data["ic_overview"]["n_runs_comparable_cost"] == 1


def test_ic_run_cost_vm_architecture_is_instance_basis_only(tmp_path, make_ic_run, write_run_json):
    """VM-architecture IC: no ECS tasks to split, so there is no comparable figure at all."""
    jsonl_dir = _bundle(tmp_path, [make_ic_run(run_id="icRUN0000000001")], write_run_json)
    _write_costs(jsonl_dir, [
        {"run_id": "icRUN0000000001", "process": "", "hash": "",
         "unblended_cost": 2.5, "split_cost": 0.0, "unused_cost": 0.0,
         "split_cost_present": False},
    ])
    data = build_ic_report_data(jsonl_dir)
    row = next(r for r in data["run_summary"] if r["run_id"] == "icRUN0000000001")
    assert row["cost"] == 2.5
    assert row["comparable_cost"] is None  # excluded from IC-vs-Batch comparison charts
    assert row["used_cost"] is None
    assert row["unused_cost"] is None
    assert row["cost_status"] == "available"
    assert data["ic_overview"]["n_runs_billed_cost"] == 1
    assert data["ic_overview"]["n_runs_comparable_cost"] == 0


def test_ic_run_billed_cost_stays_empty_without_instance_rows(tmp_path, make_ic_run, write_run_json):
    """A Batch run labels only its ECS tasks, so no billed machine charge can be attributed.

    ``cost`` must stay None rather than borrowing the split figure: otherwise the two columns
    show the same number twice and a reader cannot tell a billed charge from an allocation.
    """
    jsonl_dir = _bundle(tmp_path, [make_ic_run(run_id="icRUN0000000001")], write_run_json)
    _write_costs(jsonl_dir, [
        {"run_id": "icRUN0000000001", "process": "FOO", "hash": "abcd1234",
         "unblended_cost": 0.0, "split_cost": 2.0, "unused_cost": 0.5,
         "split_cost_present": True},
    ])
    data = build_ic_report_data(jsonl_dir)
    row = next(r for r in data["run_summary"] if r["run_id"] == "icRUN0000000001")
    assert row["cost"] is None             # no billed machine charge exists for this run
    assert row["comparable_cost"] == 2.5   # the split basis is all AWS Batch reports
    assert row["cost_status"] == "available"
    assert data["ic_overview"]["n_runs_billed_cost"] == 0
    assert data["ic_overview"]["n_runs_comparable_cost"] == 1


def test_ic_run_cost_status_not_found_when_cur_supplied_but_unmatched(tmp_path, make_ic_run, write_run_json):
    """CUR supplied but nothing matched this run (no timestamp) -> not_found."""
    jsonl_dir = _bundle(tmp_path, [make_ic_run(run_id="icRUN0000000001")], write_run_json)
    _write_costs(jsonl_dir, [
        {"run_id": "otherRUN", "process": "FOO", "hash": "abcd1234",
         "unblended_cost": 9.0, "split_cost": 0.0, "unused_cost": 0.0, "split_cost_present": False},
    ])
    data = build_ic_report_data(jsonl_dir)
    row = next(r for r in data["run_summary"] if r["run_id"] == "icRUN0000000001")
    assert row["cost"] is None
    assert row["comparable_cost"] is None
    assert row["cost_status"] == "not_found"
    assert data["ic_overview"]["n_runs_missing_cost"] == 1


def test_ic_run_cost_status_propagating_for_recent_run(tmp_path, make_ic_run, write_run_json):
    """A run that finished < 24h ago with no cost yet is 'propagating', not 'not_found'."""
    from datetime import datetime, timedelta, timezone

    run = make_ic_run(run_id="icRUN0000000001")
    run["workflow"]["complete"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    jsonl_dir = _bundle(tmp_path, [run], write_run_json)
    _write_costs(jsonl_dir, [
        {"run_id": "otherRUN", "process": "FOO", "hash": "abcd1234", "unblended_cost": 9.0},
    ])
    data = build_ic_report_data(jsonl_dir)
    row = next(r for r in data["run_summary"] if r["run_id"] == "icRUN0000000001")
    assert row["cost"] is None
    assert row["cost_status"] == "propagating"


def test_ic_run_cost_status_none_without_cur(tmp_path, make_ic_run, write_run_json):
    """No CUR export at all -> cost_status is None (cost analysis off), not a miss."""
    jsonl_dir = _bundle(tmp_path, [make_ic_run(run_id="icRUN0000000001")], write_run_json)
    data = build_ic_report_data(jsonl_dir)
    row = data["run_summary"][0]
    assert row["cost_status"] is None
    assert row["comparable_cost"] is None
    assert data["ic_overview"]["cur_supplied"] is False
    assert data["ic_overview"]["n_runs_missing_cost"] == 0
