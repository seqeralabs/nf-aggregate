from benchmark_report_ic_aggregate import build_ic_report_data
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

    assert set(data.keys()) == {"ic_overview", "run_summary"}
    assert data["ic_overview"] == {
        "n_runs": 2, "n_intelligent_compute": 1, "n_batch": 1, "cost_source": None,
    }
    assert {r["compute_type"] for r in data["run_summary"]} == {"intelligent_compute", "batch"}


def test_ic_run_summary_fields(tmp_path, make_ic_run, write_run_json):
    jsonl_dir = _bundle(tmp_path, [make_ic_run(run_id="icRUN0000000001")], write_run_json)
    row = build_ic_report_data(jsonl_dir, web_base="https://cloud.example.test")["run_summary"][0]

    assert row["run_id"] == "icRUN0000000001"
    assert row["compute_type"] == "intelligent_compute"
    assert row["run_url"] == (
        "https://cloud.example.test/orgs/myorg/workspaces/myworkspace/watch/icRUN0000000001"
    )
    assert row["compute_hours"] == round(1247429 / 3.6e6, 2)
    assert row["memory_used_bytes"] == 12339093504
    assert row["memory_used_gb"] == round(12339093504 / 1024**3, 2)
    assert row["run_cost_platform"] == 0.0053921835
    assert row["cost"] is None


def test_batch_detected_when_sched_absent(tmp_path, make_batch_run, write_run_json):
    jsonl_dir = _bundle(tmp_path, [make_batch_run()], write_run_json)
    assert build_ic_report_data(jsonl_dir)["run_summary"][0]["compute_type"] == "batch"
