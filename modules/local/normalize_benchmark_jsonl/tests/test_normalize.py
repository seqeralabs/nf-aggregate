import json

from benchmark_report_normalize import extract_runs, extract_tasks, load_run_data, normalize_jsonl


def test_cached_count_extracted(make_run, flat_task):
    run = make_run(tasks=[flat_task()], cached_count=7)
    rows = extract_runs([run])
    assert rows[0]["cached"] == 7


def test_nested_tasks_unwrapped(make_run, nested_task):
    run = make_run(tasks=[nested_task(cost=2.0), nested_task(cost=3.0)])
    rows = extract_tasks([run])
    assert sum(r["cost"] for r in rows) == 5.0


def test_failed_tasks_filtered(make_run, flat_task):
    run = make_run(tasks=[flat_task(status="COMPLETED"), flat_task(status="FAILED"), flat_task(status="CACHED")])
    rows = extract_tasks([run])
    assert len(rows) == 2
    assert {r["status"] for r in rows} == {"COMPLETED", "CACHED"}


def test_normalize_writes_jsonl_bundle(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task()])])

    normalize_jsonl(data_dir, out_dir)

    assert (out_dir / "runs.jsonl").is_file()
    assert (out_dir / "tasks.jsonl").is_file()
    assert (out_dir / "metrics.jsonl").is_file()

    task_lines = (out_dir / "tasks.jsonl").read_text().strip().splitlines()
    task = json.loads(task_lines[0])
    assert task["process_short"] == "PROCESS_A"


def test_load_run_data(tmp_path, make_run, write_run_json):
    data_dir = tmp_path / "data"
    write_run_json(data_dir, [make_run(), make_run(run_id="run2")])
    rows = load_run_data(data_dir)
    assert len(rows) == 2
