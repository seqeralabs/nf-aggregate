import json

import pyarrow as pa
import pyarrow.parquet as pq

from benchmark_report_normalize import _normalize_cost_rows, extract_runs, extract_tasks, load_run_data, normalize_jsonl


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

    run_lines = (out_dir / "runs.jsonl").read_text().strip().splitlines()
    run = json.loads(run_lines[0])
    assert run["workspace"] == "org/ws"
    assert run["platform"] == ""


def test_normalize_preserves_platform_and_run_url(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "jsonl_bundle"
    run = make_run(tasks=[flat_task()])
    run["meta"]["workspace"] = "unified-compute/sched-testing"
    run["meta"]["platform"] = "https://cloud.dev-seqera.io"
    run["workflow"]["runUrl"] = "https://cloud.dev-seqera.io/orgs/unified-compute/workspaces/sched-testing/watch/run1"
    write_run_json(data_dir, [run])

    normalize_jsonl(data_dir, out_dir)

    run_line = json.loads((out_dir / "runs.jsonl").read_text().strip().splitlines()[0])
    assert run_line["workspace"] == "unified-compute/sched-testing"
    assert run_line["platform"] == "https://cloud.dev-seqera.io"
    assert run_line["run_url"].endswith("/watch/run1")


def test_normalize_cost_rows_reads_parquet_in_batches(tmp_path):
    parquet_path = tmp_path / "costs.parquet"
    table = pa.table(
        {
            "resource_tags_user_unique_run_id": ["run1", "run1"],
            "resource_tags_user_pipeline_process": ["PROC_A", "PROC_A"],
            "resource_tags_user_task_hash": ["abcdef12", "abcdef12"],
            "split_line_item_split_cost": [1.25, 2.75],
            "split_line_item_unused_cost": [0.25, 0.75],
        }
    )
    pq.write_table(table, parquet_path, row_group_size=1)

    rows = _normalize_cost_rows(parquet_path)

    assert rows == [
        {
            "run_id": "run1",
            "process": "PROC_A",
            "hash": "abcdef12",
            "cost": 5.0,
            "used_cost": 4.0,
            "unused_cost": 1.0,
        }
    ]


def test_load_run_data(tmp_path, make_run, write_run_json):
    data_dir = tmp_path / "data"
    write_run_json(data_dir, [make_run(), make_run(run_id="run2")])
    rows = load_run_data(data_dir)
    assert len(rows) == 2
