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
    }
    assert {r["compute_type"] for r in data["run_summary"]} == {"intelligent_compute", "batch"}


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
