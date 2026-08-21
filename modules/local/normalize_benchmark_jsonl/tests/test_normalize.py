import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from benchmark_report_normalize import (
    _load_cost_label_aliases,
    _normalize_cost_rows,
    _parquet_sources,
    _path_status,
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
            "session_id": "",
            "process": "PROC_A",
            "hash": "abcdef12",
            "unblended_cost": 0.0,
            "split_cost": 4.0,
            "unused_cost": 1.0,
            "spot_cost": 0.0,
            "ondemand_cost": 0.0,
            "split_cost_present": True,
            "cost": 5.0,
            "used_cost": 4.0,
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
            "session_id": "",
            "process": "PROC_Z",
            "hash": "11223344",
            "unblended_cost": 0.0,
            "split_cost": 3.0,
            "unused_cost": 0.75,
            "spot_cost": 0.0,
            "ondemand_cost": 0.0,
            "split_cost_present": True,
            "cost": 3.75,
            "used_cost": 3.0,
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
            "session_id": "",
            "process": "PROC_MAP",
            "hash": "aa11bb22",
            "unblended_cost": 0.0,
            "split_cost": 2.5,
            "unused_cost": 0.5,
            "spot_cost": 0.0,
            "ondemand_cost": 0.0,
            "split_cost_present": True,
            "cost": 3.0,
            "used_cost": 2.5,
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
            "session_id": "",
            "process": "PROC_V2",
            "hash": "deadbeef",
            "unblended_cost": 4.0,
            "split_cost": 0.0,
            "unused_cost": 0.0,
            "spot_cost": 0.0,
            "ondemand_cost": 0.0,
            "split_cost_present": False,
            "cost": 4.0,
            "used_cost": 4.0,
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
            "session_id": "",
            "process": "PROC_MAP_REAL",
            "hash": "cafebabe",
            "unblended_cost": 7.0,
            "split_cost": 0.0,
            "unused_cost": 0.0,
            "spot_cost": 0.0,
            "ondemand_cost": 0.0,
            "split_cost_present": False,
            "cost": 7.0,
            "used_cost": 7.0,
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
    """A directory of parquet files is scanned as one dataset (union_by_name), so
    heterogeneous CUR exports (v1 flat columns + v2 struct list) are read together.

    The two cost bases stay SEPARATE: this run has a $1.00 split figure and a $2.00 instance
    charge, and the single-basis ``cost`` is the billed instance charge alone ($2.00) — never
    $3.00. Adding them is the double count this schema exists to prevent, since split rows
    re-express the very instance cost the unblended rows already state.
    """
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
            "session_id": "",
            "process": "",
            "hash": "",
            "unblended_cost": 2.0,
            "split_cost": 1.0,
            "unused_cost": 0.0,
            "spot_cost": 0.0,
            "ondemand_cost": 0.0,
            "split_cost_present": True,
            "cost": 2.0,
            "used_cost": 2.0,
        }
    ]


def test_normalize_cost_rows_rejects_non_parquet_input(tmp_path):
    """A staged AWS console URL (or any other non-parquet file) is reported as a bad
    parameter instead of surfacing DuckDB's "No magic bytes found" traceback.
    """
    not_parquet = tmp_path / "intelligent-compute-testing-cost"
    not_parquet.write_text("<html>console page, not a CUR export</html>")

    with pytest.raises(ValueError, match="not a .parquet file"):
        _normalize_cost_rows(not_parquet)

    empty_dir = tmp_path / "cur-empty"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="no \\*.parquet files"):
        _normalize_cost_rows(empty_dir)


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
            "session_id": "",
            "process": "",
            "hash": "",
            "unblended_cost": 0.0,
            "split_cost": 1.0,
            "unused_cost": 0.0,
            "spot_cost": 0.0,
            "ondemand_cost": 0.0,
            "split_cost_present": True,
            "cost": 1.0,
            "used_cost": 1.0,
        }
    ]


def test_normalize_cost_rows_keeps_ic_instance_and_split_rows_apart(tmp_path):
    """An Intelligent Compute run on ECS: tagged EC2 instance rows PLUS the ECS split rows
    derived from those same instances.

    AWS adds split line items *in addition to* the parent instance rows, so the two describe
    the same compute. Because the scheduler tags the instances themselves, both classes carry
    the run-id tag and both are scanned — they must land in separate fields, never one total.
    Here: $10.00 billed on the instances, and split rows re-expressing $6.00 of it ($4.50
    consumed + $1.50 idle). The answer is 10.00 and 6.00 side by side, NOT $16.00.
    """
    parquet_path = tmp_path / "ic-ecs.parquet"
    tag_type = pa.map_(pa.string(), pa.string())

    def tags(**kv):
        return list(kv.items())

    table = pa.table(
        {
            "resource_tags": pa.array(
                [
                    # Parent EC2 instance rows: the scheduler tags them with the workflow id,
                    # but they carry no per-task labels, so process/hash come back empty.
                    tags(user_seqera_io_platform_workflow_id="ic-run"),
                    tags(user_seqera_io_platform_workflow_id="ic-run"),
                    # ECS split rows for tasks that ran on those instances.
                    tags(
                        user_seqera_io_platform_workflow_id="ic-run",
                        user_pipeline_process="PROC_A",
                        user_task_hash="aaaa1111bbbb",
                    ),
                    tags(
                        user_seqera_io_platform_workflow_id="ic-run",
                        user_pipeline_process="PROC_A",
                        user_task_hash="aaaa1111bbbb",
                    ),
                ],
                type=tag_type,
            ),
            "line_item_product_code": ["AmazonEC2", "AmazonEC2", "AmazonECS", "AmazonECS"],
            "line_item_resource_id": ["i-parent", "i-parent2", "task/a", "task/b"],
            "split_line_item_parent_resource_id": [None, None, "i-parent", "i-parent2"],
            # Parent rows hold the billed charge; split rows hold the re-attribution.
            "line_item_unblended_cost": [6.0, 4.0, 0.0, 0.0],
            "split_line_item_split_cost": [0.0, 0.0, 3.0, 1.5],
            "split_line_item_unused_cost": [0.0, 0.0, 1.0, 0.5],
        }
    )
    pq.write_table(table, parquet_path)

    rows = _normalize_cost_rows(parquet_path)
    by_group = {(r["run_id"], r["process"]): r for r in rows}

    instance_group = by_group[("ic-run", "")]
    assert instance_group["unblended_cost"] == 10.0
    assert instance_group["split_cost"] == 0.0
    assert instance_group["split_cost_present"] is False or instance_group["split_cost_present"] == 0

    split_group = by_group[("ic-run", "PROC_A")]
    assert split_group["split_cost"] == 4.5
    assert split_group["unused_cost"] == 1.5
    assert split_group["unblended_cost"] == 0.0

    # The whole point: per run the two bases total 10.00 and 6.00 — not 16.00.
    assert sum(r["unblended_cost"] for r in rows) == 10.0
    assert sum(r["split_cost"] + r["unused_cost"] for r in rows) == 6.0


def test_normalize_cost_rows_splits_machine_spend_by_purchase_option(tmp_path):
    """Spot vs on-demand comes off the EC2 instance-hour rows, and ONLY those rows.

    The trap this pins down is real, measured on a production export: AWS labels the
    EBSOptimized surcharge of a *Spot* instance ``OnDemand``. Classifying on
    ``product_marketoption`` alone would book that surcharge as on-demand spend and make a
    100%-spot run look mixed. Gating on the usage type keeps it out, along with the EBS volume
    and data-transfer rows tagged to the same run — none of which are machine rental.
    """
    parquet_path = tmp_path / "purchase-option.parquet"

    table = pa.table(
        {
            "resource_tags_user_seqera_io_platform_workflow_id": ["ic-run"] * 5,
            "line_item_product_code": ["AmazonEC2"] * 4 + ["AmazonECS"],
            "line_item_usage_type": [
                "EU-SpotUsage:c5d.2xlarge",     # spot machine rental
                "EU-BoxUsage:r5a.2xlarge",      # on-demand machine rental (the fallback)
                "EU-EBSOptimized:c5d.2xlarge",  # surcharge on the SPOT box, mislabelled OnDemand
                "EU-EBS:VolumeUsage.gp3",       # storage, no purchase option at all
                "EU-ECS-EC2-vCPU-Hours",        # ECS split row, no purchase option at all
            ],
            "product_marketoption": ["Spot", "OnDemand", "OnDemand", None, None],
            "line_item_unblended_cost": [8.0, 2.0, 0.5, 1.0, 0.0],
            "split_line_item_split_cost": [0.0, 0.0, 0.0, 0.0, 3.0],
            "split_line_item_unused_cost": [0.0, 0.0, 0.0, 0.0, 1.0],
        }
    )
    pq.write_table(table, parquet_path)

    rows = _normalize_cost_rows(parquet_path)
    assert len(rows) == 1
    row = rows[0]

    assert row["spot_cost"] == 8.0
    assert row["ondemand_cost"] == 2.0       # 2.00 only — the 0.50 surcharge is NOT rental
    # The split is a subset of the unblended basis, never an addition to it: machine rental
    # (10.00) is short of the 11.50 unblended total by the surcharge and the EBS volume.
    assert row["unblended_cost"] == 11.5
    assert row["spot_cost"] + row["ondemand_cost"] < row["unblended_cost"]
    # And it is independent of the split basis, which carries no purchase option of its own.
    assert row["split_cost"] == 3.0
    assert row["unused_cost"] == 1.0


def test_normalize_cost_rows_purchase_option_falls_back_to_usage_type(tmp_path):
    """CUR 2.0 nests ``marketoption`` inside the ``product`` map, so the flat column is absent.

    The usage type carries the same distinction in every CUR version and is the gate either
    way, so dropping the column must not drop the figure.
    """
    parquet_path = tmp_path / "cur2-no-marketoption.parquet"
    table = pa.table(
        {
            "resource_tags_user_seqera_io_platform_workflow_id": ["ic-run"] * 3,
            "line_item_usage_type": [
                "EU-SpotUsage:c5d.2xlarge",
                "EU-BoxUsage:r5a.2xlarge",
                "EU-EBS:VolumeUsage.gp3",
            ],
            "line_item_unblended_cost": [8.0, 2.0, 1.0],
        }
    )
    pq.write_table(table, parquet_path)

    row = _normalize_cost_rows(parquet_path)[0]
    assert row["spot_cost"] == 8.0
    assert row["ondemand_cost"] == 2.0


def test_normalize_cost_rows_purchase_option_zero_without_usage_type(tmp_path):
    """No usage type column at all -> no classification, and 0.0 rather than a crash."""
    parquet_path = tmp_path / "no-usage-type.parquet"
    table = pa.table(
        {
            "resource_tags_user_seqera_io_platform_workflow_id": ["ic-run"],
            "line_item_unblended_cost": [8.0],
        }
    )
    pq.write_table(table, parquet_path)

    row = _normalize_cost_rows(parquet_path)[0]
    assert row["spot_cost"] == 0.0
    assert row["ondemand_cost"] == 0.0
    assert row["unblended_cost"] == 8.0


def test_normalize_cost_rows_separates_bases_within_one_group(tmp_path):
    """The real Intelligent Compute shape: split rows carry NO process/task_hash labels, so
    they land in the same (run_id, '', '') group as the instance rows.

    Verified against a real CUR export — 0 of 49,106 IC split rows were task-labelled. The two
    bases therefore cannot be told apart after grouping, which is why they are accumulated into
    separate columns instead of being deduplicated by row class. $8.00 billed and $5.00
    re-expressed as split must survive as 8.00 and 5.00, never 13.00.
    """
    parquet_path = tmp_path / "ic-untagged-split.parquet"
    tag_type = pa.map_(pa.string(), pa.string())
    run_tag = [("user_seqera_io_platform_workflow_id", "ic-run")]
    table = pa.table(
        {
            "resource_tags": pa.array([run_tag, run_tag, run_tag], type=tag_type),
            "line_item_product_code": ["AmazonEC2", "AmazonECS", "AmazonECS"],
            "line_item_unblended_cost": [8.0, 0.0, 0.0],
            "split_line_item_split_cost": [0.0, 3.0, 1.0],
            "split_line_item_unused_cost": [0.0, 0.5, 0.5],
        }
    )
    pq.write_table(table, parquet_path)

    rows = _normalize_cost_rows(parquet_path)

    # Everything collapses to one group, yet both bases remain individually intact.
    assert len(rows) == 1
    assert rows[0] == {
        "run_id": "ic-run",
        "session_id": "",
        "process": "",
        "hash": "",
        "unblended_cost": 8.0,
        "split_cost": 4.0,
        "unused_cost": 1.0,
        "spot_cost": 0.0,
        "ondemand_cost": 0.0,
        "split_cost_present": True,
        # Single-basis convenience prefers the billed charge; it must never be 13.00, and it
        # must not silently drop the larger instance figure in favour of the split one.
        "cost": 8.0,
        "used_cost": 8.0,
    }


def test_normalize_cost_rows_vm_architecture_has_instance_basis_only(tmp_path):
    """An Intelligent Compute run on the VM architecture never runs ECS tasks, so AWS has
    nothing to split. Only the instance basis exists, and it must be reported in full."""
    parquet_path = tmp_path / "ic-vm.parquet"
    tag_type = pa.map_(pa.string(), pa.string())
    table = pa.table(
        {
            "resource_tags": pa.array(
                [[("user_seqera_io_platform_workflow_id", "vm-run")]], type=tag_type
            ),
            "line_item_product_code": ["AmazonEC2"],
            "line_item_unblended_cost": [12.5],
            "split_line_item_split_cost": [0.0],
            "split_line_item_unused_cost": [0.0],
        }
    )
    pq.write_table(table, parquet_path)

    rows = _normalize_cost_rows(parquet_path)

    assert len(rows) == 1
    assert rows[0]["unblended_cost"] == 12.5
    assert rows[0]["split_cost"] == 0.0
    assert rows[0]["unused_cost"] == 0.0
    assert not rows[0]["split_cost_present"]
    # No split basis, so the single-basis convenience falls back to the instance charge.
    assert rows[0]["cost"] == 12.5


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


def test_extract_runs_carries_session_and_resume_flags(make_run, flat_task):
    """Session id is the run's identity across resumes; cached tasks mark an attempt resumed."""
    plain, resumed_flag, cached = extract_runs(
        [
            make_run(run_id="r1", session_id="sess-aaa"),
            make_run(run_id="r2", session_id="sess-bbb", resume=True),
            make_run(run_id="r3", session_id="sess-ccc", tasks=[flat_task()], cached_count=2),
        ]
    )
    assert (plain["session_id"], plain["resumed"]) == ("sess-aaa", False)
    assert (resumed_flag["session_id"], resumed_flag["resumed"]) == ("sess-bbb", True)
    # No Platform resume flag, but cached tasks prove earlier work was reused.
    assert (cached["session_id"], cached["resumed"]) == ("sess-ccc", True)


def test_normalize_cost_rows_reads_intelligent_compute_session_label(tmp_path):
    """`nextflow.io/sessionId` reaches CUR as `user_nextflow_io_session_id`."""
    parquet_path = tmp_path / "costs-ic-session.parquet"
    pq.write_table(
        pa.table(
            {
                "resource_tags_user_seqera_io_platform_workflow_id": ["icRUN1"],
                "resource_tags_user_nextflow_io_session_id": ["sess-ic-1"],
                "line_item_unblended_cost": [3.0],
            }
        ),
        parquet_path,
    )

    rows = _normalize_cost_rows(parquet_path)

    assert [(r["run_id"], r["session_id"], r["cost"]) for r in rows] == [("icRUN1", "sess-ic-1", 3.0)]


def test_normalize_cost_rows_reads_batch_session_label_from_tag_map(tmp_path):
    """The blog-template Batch label `pipelineSessionId` -> `user_pipeline_session_id`."""
    parquet_path = tmp_path / "costs-batch-session.parquet"
    pq.write_table(
        pa.table(
            {
                "resource_tags": [
                    [
                        ("user_unique_run_id", "batchRUN1"),
                        ("user_pipeline_session_id", "sess-batch-1"),
                    ]
                ],
                "split_line_item_split_cost": [2.0],
            }
        ),
        parquet_path,
    )

    rows = _normalize_cost_rows(parquet_path)

    assert [(r["run_id"], r["session_id"]) for r in rows] == [("batchRUN1", "sess-batch-1")]


def test_normalize_cost_rows_accepts_custom_session_alias(tmp_path):
    label_map_path = tmp_path / "cur_label_map.yml"
    label_map_path.write_text("session_id: my_session_label\n")
    parquet_path = tmp_path / "costs-custom-session.parquet"
    pq.write_table(
        pa.table(
            {
                "resource_tags_user_unique_run_id": ["run1"],
                "resource_tags_my_session_label": ["sess-custom"],
                "line_item_unblended_cost": [1.0],
            }
        ),
        parquet_path,
    )

    rows = _normalize_cost_rows(parquet_path, cost_label_map=label_map_path)

    assert rows[0]["session_id"] == "sess-custom"
    # Built-in aliases stay as fallbacks behind the custom one.
    assert _load_cost_label_aliases(label_map_path)["session_id"] == [
        "my_session_label",
        "user_nextflow_io_session_id",
        "user_pipeline_session_id",
        "user_session_id",
    ]


def test_normalize_cost_rows_without_session_label_keep_working(tmp_path):
    """No session label in the export -> blank session, run-id join unaffected."""
    parquet_path = tmp_path / "costs-no-session.parquet"
    pq.write_table(
        pa.table(
            {
                "resource_tags_user_unique_run_id": ["run1"],
                "line_item_unblended_cost": [4.0],
            }
        ),
        parquet_path,
    )

    rows = _normalize_cost_rows(parquet_path)

    assert [(r["run_id"], r["session_id"], r["cost"]) for r in rows] == [("run1", "", 4.0)]


# ---------------------------------------------------------------------------------------
# Staged-path readability. Nextflow stages inputs as symlinks and, on Fusion, they resolve
# into the NFS mount where a lookup can fail with EACCES instead of ENOENT. `Path.exists()`
# re-raises that on Python 3.12, which used to kill the whole report over an optional input.
# ---------------------------------------------------------------------------------------

def test_path_status_separates_absent_from_unreadable(tmp_path, denied_path):
    present = tmp_path / "real.parquet"
    present.write_text("")

    assert _path_status(present) == "present"
    assert _path_status(tmp_path / "missing.parquet") == "absent"
    # The distinction this whole guard exists for: a path we cannot stat is NOT absent.
    assert _path_status(denied_path) == "unreadable"
    # Path.exists() is the trap being avoided — it raises here on 3.12 and lies on 3.13+.
    with pytest.raises(PermissionError):
        denied_path.exists()


def test_unreadable_cur_path_fails_with_an_actionable_message(tmp_path, denied_path, make_run, flat_task, write_run_json):
    """The reported bug: `PermissionError: [Errno 13] Permission denied: 'data'` and no report."""
    data_dir = tmp_path / "data_in"
    out_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task()])])

    with pytest.raises(RuntimeError) as excinfo:
        normalize_jsonl(data_dir, out_dir, costs_parquet=denied_path)

    message = str(excinfo.value)
    assert "benchmark_aws_cur_report" in message
    assert str(denied_path) in message
    assert "s3:ListBucket" in message
    assert isinstance(excinfo.value.__cause__, Exception)
    # Everything that did not depend on the CUR file was still produced.
    assert (out_dir / "runs.jsonl").is_file()
    assert (out_dir / "tasks.jsonl").is_file()
    assert not (out_dir / "costs.jsonl").exists()


def test_unreadable_cur_path_defers_to_duckdb_instead_of_giving_up(denied_path):
    """A path we cannot walk still gets a read attempt: DuckDB globs and opens it itself."""
    assert _parquet_sources(denied_path) == [str(denied_path / "**" / "*.parquet")]
    # A file-shaped path is passed through verbatim rather than globbed.
    assert _parquet_sources(denied_path.parent / "x.parquet") == [str(denied_path.parent / "x.parquet")]


def test_missing_cur_path_is_skipped_not_an_error(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data_in"
    out_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task()])])

    normalize_jsonl(data_dir, out_dir, costs_parquet=tmp_path / "nope.parquet")

    assert (out_dir / "runs.jsonl").is_file()
    assert not (out_dir / "costs.jsonl").exists()


def test_no_file_placeholder_is_rejected_on_name_alone(tmp_path, denied_path, make_run, flat_task, write_run_json):
    """The placeholder short-circuits before the fallible stat, even inside an unreadable dir."""
    data_dir = tmp_path / "data_in"
    out_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task()])])

    normalize_jsonl(data_dir, out_dir, costs_parquet=denied_path.parent / "NO_FILE")

    assert (out_dir / "runs.jsonl").is_file()
    assert not (out_dir / "costs.jsonl").exists()


def test_unreadable_machines_dir_warns_and_keeps_the_report(tmp_path, denied_path, make_run, flat_task, write_run_json, capsys):
    """Machine telemetry is supplementary, so it degrades instead of failing the run."""
    data_dir = tmp_path / "data_in"
    out_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task()])])

    normalize_jsonl(data_dir, out_dir, machines_dir=denied_path)

    assert (out_dir / "runs.jsonl").is_file()
    assert not (out_dir / "machines.jsonl").exists()
    assert "machines directory" in capsys.readouterr().err


def test_unreadable_run_data_dir_names_the_real_problem(tmp_path, denied_path):
    with pytest.raises(RuntimeError) as excinfo:
        normalize_jsonl(denied_path, tmp_path / "out")
    assert "run data directory" in str(excinfo.value)


def test_short_workflow_and_session_label_variant_is_attributed(tmp_path):
    """`user_workflow_id`/`user_session_id`: a real variant that used to be dropped entirely.

    Measured in the SciDev Intelligent Compute export: 76 rows carrying $1.07 of ECS split
    cost that matched none of the other run-id aliases.
    """
    parquet_path = tmp_path / "costs-short-labels.parquet"
    pq.write_table(
        pa.table(
            {
                "resource_tags": [
                    [("user_workflow_id", "406PkyuDM3sf5r"),
                     ("user_session_id", "6f0d8a0d-0a15-4735-a448-32485bfafaa1")]
                ],
                "split_line_item_split_cost": [0.2143],
            }
        ),
        parquet_path,
    )

    rows = _normalize_cost_rows(parquet_path)

    assert [(r["run_id"], r["session_id"], r["cost"]) for r in rows] == [
        ("406PkyuDM3sf5r", "6f0d8a0d-0a15-4735-a448-32485bfafaa1", 0.2143)
    ]
