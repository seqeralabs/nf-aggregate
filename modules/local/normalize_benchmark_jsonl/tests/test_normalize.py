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
            "split_cost_present": True,
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
            "split_cost_present": True,
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
            "split_cost_present": True,
        }
    ]


def test_normalize_cost_rows_accepts_v2_struct_list_resource_tags(tmp_path):
    """CUR v2 data exports store resource labels as one list of {key,value} structs."""
    parquet_path = tmp_path / "costs-v2-struct.parquet"
    tag_type = pa.list_(pa.struct([("key", pa.string()), ("value", pa.string())]))
    table = pa.table(
        {
            "resource_tags": pa.array(
                [
                    [
                        {"key": "user_seqera_io_platform_workflow_id", "value": "run-v2"},
                        {"key": "user_pipeline_process", "value": "PROC_V2"},
                        {"key": "user_task_hash", "value": "deadbeef0001"},
                    ]
                ],
                type=tag_type,
            ),
            # v2 export with no split-cost column falls back to unblended cost
            "line_item_unblended_cost": [4.0],
        }
    )
    pq.write_table(table, parquet_path)

    rows = _normalize_cost_rows(parquet_path)

    assert rows == [
        {
            "run_id": "run-v2",
            "process": "PROC_V2",
            "hash": "deadbeef",
            "cost": 4.0,
            "used_cost": 4.0,
            "unused_cost": 0.0,
            "split_cost_present": False,
        }
    ]


def test_normalize_cost_rows_accepts_map_resource_tags(tmp_path):
    """CUR exports whose resource_tags is a genuine MAP(VARCHAR, VARCHAR).

    DuckDB MAP indexing returns a LIST per key, so the scalar tag value must be
    unwrapped — otherwise run_id lands as "[value]" and never joins to a run.
    """
    parquet_path = tmp_path / "costs-map.parquet"
    tag_type = pa.map_(pa.string(), pa.string())
    table = pa.table(
        {
            "resource_tags": pa.array(
                [
                    [
                        ("user_seqera_io_platform_workflow_id", "run-map-real"),
                        ("user_pipeline_process", "PROC_MAP_REAL"),
                        ("user_task_hash", "cafebabe0002"),
                    ]
                ],
                type=tag_type,
            ),
            "line_item_unblended_cost": [7.0],
        }
    )
    pq.write_table(table, parquet_path)

    rows = _normalize_cost_rows(parquet_path)

    assert rows == [
        {
            "run_id": "run-map-real",
            "process": "PROC_MAP_REAL",
            "hash": "cafebabe",
            "cost": 7.0,
            "used_cost": 7.0,
            "unused_cost": 0.0,
            "split_cost_present": False,
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


def test_normalize_cost_rows_reads_directory_of_parquets(tmp_path):
    """A directory of parquet files is scanned as one dataset (union_by_name),
    so heterogeneous CUR exports (v1 flat columns + v2 struct list) sum together."""
    cost_dir = tmp_path / "cur"
    cost_dir.mkdir()
    pq.write_table(
        pa.table(
            {
                "resource_tags_user_unique_run_id": ["run1"],
                "split_line_item_split_cost": [1.0],
                "split_line_item_unused_cost": [0.0],
            }
        ),
        cost_dir / "part-a.parquet",
    )
    tag_type = pa.list_(pa.struct([("key", pa.string()), ("value", pa.string())]))
    pq.write_table(
        pa.table(
            {
                "resource_tags": pa.array(
                    [[{"key": "user_unique_run_id", "value": "run1"}]], type=tag_type
                ),
                "line_item_unblended_cost": [2.0],
            }
        ),
        cost_dir / "part-b.parquet",
    )

    rows = _normalize_cost_rows(cost_dir)

    assert rows == [
        {
            "run_id": "run1",
            "process": "",
            "hash": "",
            "cost": 3.0,
            "used_cost": 3.0,
            "unused_cost": 0.0,
            "split_cost_present": True,
        }
    ]


def test_normalize_cost_rows_ignores_rows_without_run_label(tmp_path):
    """Only rows carrying a run-id resource label are costed; null/empty-labelled
    rows never contribute, so the scan operates on the labelled subset only."""
    parquet_path = tmp_path / "mixed.parquet"
    pq.write_table(
        pa.table(
            {
                "resource_tags_user_unique_run_id": ["run1", None, ""],
                "split_line_item_split_cost": [1.0, 9.0, 9.0],
                "split_line_item_unused_cost": [0.0, 0.0, 0.0],
            }
        ),
        parquet_path,
    )

    rows = _normalize_cost_rows(parquet_path)

    assert rows == [
        {
            "run_id": "run1",
            "process": "",
            "hash": "",
            "cost": 1.0,
            "used_cost": 1.0,
            "unused_cost": 0.0,
            "split_cost_present": True,
        }
    ]


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


def _base_run(**over):
    run = {
        "workflow": {"id": "icRUN0000000001", "status": "SUCCEEDED", "duration": 1000},
        "progress": {"workflowProgress": {
            "cpuTime": 3600000, "memoryRss": 2147483648, "peakMemory": 4294967296,
            "cost": 0.42, "cpuEfficiency": 50.0, "memoryEfficiency": 25.0,
        }},
        "tasks": [], "metrics": [],
        "meta": {"id": "icRUN0000000001", "workspace": "myorg/myworkspace", "group": "ic"},
    }
    run.update(over)
    return run


def test_extract_runs_emits_ic_fields():
    row = extract_runs([_base_run(
        schedEnabled=True, schedConfig={"predictionModel": "qr/v2"},
        platform={"id": "aws-cloud"},
    )])[0]
    assert row["memory_rss_bytes"] == 2147483648
    assert row["peak_memory_bytes"] == 4294967296
    assert row["run_cost"] == 0.42
    assert row["sched_enabled"] is True
    assert row["platform_id"] == "aws-cloud"


def test_extract_runs_batch_defaults_when_sched_absent():
    row = extract_runs([_base_run(platform={"id": "aws-batch"})])[0]
    assert row["sched_enabled"] is False
    assert row["platform_id"] == "aws-batch"
