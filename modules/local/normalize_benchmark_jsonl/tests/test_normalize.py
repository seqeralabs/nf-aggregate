import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from benchmark_report_normalize import (
    _load_cost_label_aliases,
    _normalize_cost_rows,
    _summarise_machines,
    extract_runs,
    extract_tasks,
    load_run_data,
    normalize_jsonl,
)


def test_cached_count_extracted(make_run, flat_task):
    run = make_run(tasks=[flat_task()], cached_count=7)
    rows = extract_runs([run])
    assert rows[0]["cached"] == 7


def test_nested_tasks_unwrapped(make_run, nested_task):
    run = make_run(tasks=[nested_task(cost=2.0), nested_task(cost=3.0)])
    rows = extract_tasks([run])
    assert all(r["cost"] is None for r in rows)


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


def test_summarise_machines_handles_mixed_scheduler_and_batch_rows(tmp_path):
    machines_dir = tmp_path / "machines"
    machines_dir.mkdir()
    (machines_dir / "machine_metrics.csv").write_text(
        "run_id,instance_id,vcpus,memory_gib,machine_hours,avg_cpu_utilization,avg_memory_utilization,ecs_instance_id,total_vcpu_hours,total_memory_gib_hours,total_requested_vcpu_hours,total_requested_memory_gib_hours\n"
        "sched1,i-123,8,32,2,50,25,,,,,\n"
        "batch1,,,,,, ,ecs-456,6,24,3,12\n".replace(", ,", ",,")
    )

    rows = {row["run_id"]: row for row in _summarise_machines(machines_dir)}
    assert rows["sched1"]["vm_cpu_h"] == 16.0
    assert rows["sched1"]["sched_alloc_cpu_efficiency"] == 50.0
    assert rows["batch1"]["vm_cpu_h"] == 6.0
    assert rows["batch1"]["sched_alloc_cpu_efficiency"] == 50.0
    assert rows["batch1"]["sched_alloc_mem_efficiency"] == 50.0


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


def test_normalize_cost_rows_accepts_custom_flat_aliases(tmp_path):
    parquet_path = tmp_path / "costs-flat-custom.parquet"
    label_map_path = tmp_path / "cur_label_map.yml"
    label_map_path.write_text(
        "run_id:\n"
        "  - manual_run_label\n"
        "process:\n"
        "  - manual_process_label\n"
        "task_hash:\n"
        "  - manual_hash_label\n"
    )
    table = pa.table(
        {
            "resource_tags_manual_run_label": ["run9", "run9"],
            "resource_tags_manual_process_label": ["PROC_Z", "PROC_Z"],
            "resource_tags_manual_hash_label": ["1122334455aa", "1122334455aa"],
            "split_line_item_split_cost": [1.0, 2.0],
            "split_line_item_unused_cost": [0.5, 0.25],
        }
    )
    pq.write_table(table, parquet_path, row_group_size=1)

    rows = _normalize_cost_rows(parquet_path, cost_label_map=label_map_path)

    assert rows == [
        {
            "run_id": "run9",
            "process": "PROC_Z",
            "hash": "11223344",
            "cost": 3.75,
            "used_cost": 3.0,
            "unused_cost": 0.75,
        }
    ]


def test_normalize_cost_rows_accepts_custom_resource_tag_aliases(tmp_path):
    parquet_path = tmp_path / "costs-map-custom.parquet"
    label_map_path = tmp_path / "cur_label_map.yml"
    label_map_path.write_text(
        "run_id: manual_run_label\n"
        "process: manual_process_label\n"
        "task_hash: manual_hash_label\n"
    )
    table = pa.table(
        {
            "resource_tags": [
                [
                    ("manual_run_label", "run-map"),
                    ("manual_process_label", "PROC_MAP"),
                    ("manual_hash_label", "aa11bb22cc33"),
                ]
            ],
            "split_line_item_split_cost": [2.5],
            "split_line_item_unused_cost": [0.5],
        }
    )
    pq.write_table(table, parquet_path)

    rows = _normalize_cost_rows(parquet_path, cost_label_map=label_map_path)

    assert rows == [
        {
            "run_id": "run-map",
            "process": "PROC_MAP",
            "hash": "aa11bb22",
            "cost": 3.0,
            "used_cost": 2.5,
            "unused_cost": 0.5,
        }
    ]


def test_normalize_cost_rows_prefers_user_aliases_before_defaults(tmp_path):
    parquet_path = tmp_path / "costs-prefer-custom.parquet"
    label_map_path = tmp_path / "cur_label_map.yml"
    label_map_path.write_text("run_id: manual_run_label\n")
    table = pa.table(
        {
            "resource_tags_manual_run_label": ["run-custom"],
            "resource_tags_user_unique_run_id": ["run-default"],
            "resource_tags_user_pipeline_process": ["PROC_A"],
            "resource_tags_user_task_hash": ["abcdef123456"],
            "split_line_item_split_cost": [1.0],
            "split_line_item_unused_cost": [0.0],
        }
    )
    pq.write_table(table, parquet_path)

    rows = _normalize_cost_rows(parquet_path, cost_label_map=label_map_path)

    assert rows[0]["run_id"] == "run-custom"


def test_load_cost_label_aliases_rejects_unknown_fields(tmp_path):
    label_map_path = tmp_path / "invalid_cur_label_map.yml"
    label_map_path.write_text("unexpected: value\n")

    with pytest.raises(ValueError, match="unsupported fields"):
        _load_cost_label_aliases(label_map_path)


def test_load_run_data(tmp_path, make_run, write_run_json):
    data_dir = tmp_path / "data"
    write_run_json(data_dir, [make_run(), make_run(run_id="run2")])
    rows = load_run_data(data_dir)
    assert len(rows) == 2
