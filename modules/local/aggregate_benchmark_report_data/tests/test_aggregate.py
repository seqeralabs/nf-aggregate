import json
from datetime import datetime, timedelta, timezone

from benchmark_report_aggregate import (
    _build_workspace_run_url,
    _classify_missing_cost,
    _compute_scheduler_booked,
    _iter_jsonl,
    _positive_gap,
    build_report_data,
)
from benchmark_report_normalize import normalize_jsonl


def test_build_report_data_has_all_sections(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data"
    jsonl_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task()])])
    normalize_jsonl(data_dir, jsonl_dir)

    data = build_report_data(jsonl_dir)
    assert set(data.keys()) == {
        "benchmark_overview",
        "run_summary",
        "run_metrics",
        "run_costs",
        "process_stats",
        "combined_task_runtime",
        "task_instance_usage",
        "task_table",
        "task_scatter",
        "cost_overview",
        "cost_coverage",
    }


def test_run_costs_without_cur_are_zero(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data"
    jsonl_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task(cost=4.2)])])
    normalize_jsonl(data_dir, jsonl_dir)

    data = build_report_data(jsonl_dir)
    assert data["run_costs"][0]["cost"] == 0.0
    assert data["run_costs"][0]["used_cost"] is None
    assert data["cost_coverage"] == {
        "cur_supplied": False,
        "has_any_cost_rows": False,
        "total_included_tasks": 0,
        "matched_task_count": 0,
        "missing_task_count": 0,
        "coverage_pct": None,
        "runs_with_missing_costs": [],
        "resumed_runs": [],
        "n_resumed_runs": 0,
        "n_incomplete_lineages": 0,
    }


def test_cur_zero_costs_do_not_fall_back_to_task_cost(tmp_path):
    jsonl_dir = tmp_path / "jsonl_bundle"
    jsonl_dir.mkdir(parents=True)

    runs = [
        {
            "run_id": "run1",
            "group": "cpu",
            "pipeline": "pipe",
            "username": "u",
            "pipeline_version": "main",
            "nextflow_version": "24.10.0",
            "platform_version": "x",
            "succeeded": 1,
            "failed": 0,
            "cached": 0,
            "executor": "awsbatch",
            "region": "us-east-1",
            "fusion_enabled": False,
            "wave_enabled": False,
            "container_engine": "docker",
            "duration_ms": 10,
            "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0,
            "memory_efficiency": 50.0,
            "read_bytes": 0,
            "write_bytes": 0,
        }
    ]
    tasks = [
        {
            "run_id": "run1",
            "group": "cpu",
            "hash": "ab/cdef12",
            "process": "foo:PROC_A",
            "process_short": "PROC_A",
            "name": "PROC_A",
            "status": "COMPLETED",
            "staging_ms": 0,
            "realtime_ms": 1000,
            "duration_ms": 1000,
            "cost": 9.0,
        }
    ]
    costs = [
        {"run_id": "run1", "process": "foo:PROC_A", "hash": "abcdef12", "cost": 0.0, "used_cost": 0.0, "unused_cost": 0.0}
    ]

    (jsonl_dir / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    (jsonl_dir / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))
    (jsonl_dir / "costs.jsonl").write_text("".join(json.dumps(c) + "\n" for c in costs))

    data = build_report_data(jsonl_dir)

    assert data["run_costs"][0]["cost"] == 0.0
    assert data["run_costs"][0]["used_cost"] == 0.0
    assert data["run_costs"][0]["unused_cost"] == 0.0
    assert data["cost_overview"][0]["total_cost"] == 0.0
    assert data["cost_overview"][0]["used_cost"] == 0.0
    assert data["cost_coverage"]["cur_supplied"] is True
    assert data["cost_coverage"]["coverage_pct"] == 100.0
    assert data["cost_coverage"]["missing_task_count"] == 0


def test_partial_cur_coverage_is_reported_per_run_and_process(tmp_path):
    jsonl_dir = tmp_path / "jsonl_bundle"
    jsonl_dir.mkdir(parents=True)

    runs = [
        {
            "run_id": "run1",
            "group": "cpu",
            "pipeline": "pipe",
            "username": "u",
            "pipeline_version": "main",
            "nextflow_version": "24.10.0",
            "platform_version": "x",
            "succeeded": 2,
            "failed": 0,
            "cached": 0,
            "executor": "awsbatch",
            "region": "us-east-1",
            "fusion_enabled": False,
            "wave_enabled": False,
            "container_engine": "docker",
            "duration_ms": 10,
            "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0,
            "memory_efficiency": 50.0,
            "read_bytes": 0,
            "write_bytes": 0,
        }
    ]
    tasks = [
        {
            "run_id": "run1",
            "group": "cpu",
            "hash": "ab/cdef12",
            "process": "foo:PROC_A",
            "process_short": "PROC_A",
            "name": "PROC_A",
            "status": "COMPLETED",
            "staging_ms": 0,
            "realtime_ms": 1000,
            "duration_ms": 1000,
            "cost": None,
        },
        {
            "run_id": "run1",
            "group": "cpu",
            "hash": "ab/cdef13",
            "process": "foo:PROC_B",
            "process_short": "PROC_B",
            "name": "PROC_B",
            "status": "COMPLETED",
            "staging_ms": 0,
            "realtime_ms": 1000,
            "duration_ms": 1000,
            "cost": None,
        },
        {
            "run_id": "run1",
            "group": "cpu",
            "hash": "ab/cdef14",
            "process": "foo:PROC_B",
            "process_short": "PROC_B",
            "name": "PROC_B_retry",
            "status": "CACHED",
            "staging_ms": 0,
            "realtime_ms": 1000,
            "duration_ms": 1000,
            "cost": None,
        },
    ]
    costs = [
        {"run_id": "run1", "process": "foo:PROC_A", "hash": "abcdef12", "cost": 5.0, "used_cost": 4.0, "unused_cost": 1.0}
    ]

    (jsonl_dir / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    (jsonl_dir / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))
    (jsonl_dir / "costs.jsonl").write_text("".join(json.dumps(c) + "\n" for c in costs))

    data = build_report_data(jsonl_dir)

    assert data["run_costs"][0]["cost"] == 5.0
    assert data["cost_coverage"]["cur_supplied"] is True
    assert data["cost_coverage"]["has_any_cost_rows"] is True
    assert data["cost_coverage"]["total_included_tasks"] == 3
    assert data["cost_coverage"]["matched_task_count"] == 1
    assert data["cost_coverage"]["missing_task_count"] == 2
    assert data["cost_coverage"]["coverage_pct"] == 33.3

    run_warning = data["cost_coverage"]["runs_with_missing_costs"][0]
    assert run_warning["run_id"] == "run1"
    assert run_warning["group"] == "cpu"
    assert run_warning["total_tasks"] == 3
    assert run_warning["matched_tasks"] == 1
    assert run_warning["missing_tasks"] == 2
    assert run_warning["missing_process_summary"] == "PROC_B (2)"
    assert run_warning["missing_processes"] == [{"process_short": "PROC_B", "missing_tasks": 2}]


def test_task_table_includes_cached(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data"
    jsonl_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task(status="COMPLETED"), flat_task(status="CACHED")])])
    normalize_jsonl(data_dir, jsonl_dir)

    data = build_report_data(jsonl_dir)
    statuses = {row["Status"] for row in data["task_table"]}
    assert statuses == {"COMPLETED", "CACHED"}


def test_failed_and_cancelled_runs_only_appear_in_overview(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data"
    jsonl_dir = tmp_path / "jsonl_bundle"
    write_run_json(
        data_dir,
        [
            make_run(run_id="run-success", group="cpu", tasks=[flat_task()]),
            make_run(run_id="run-failed", group="gpu", tasks=[flat_task()], status="FAILED"),
            make_run(run_id="run-cancelled", group="spot", tasks=[flat_task()], status="CANCELLED"),
        ],
    )
    normalize_jsonl(data_dir, jsonl_dir)

    data = build_report_data(jsonl_dir)

    overview = {row["run_id"]: row for row in data["benchmark_overview"]}
    assert overview["run-success"]["report_included"] is True
    assert overview["run-success"]["status_category"] == "success"
    assert overview["run-failed"]["report_included"] is False
    assert overview["run-failed"]["status_category"] == "failed"
    assert overview["run-cancelled"]["report_included"] is False
    assert overview["run-cancelled"]["status_category"] == "cancelled"

    summary_ids = [row["run_id"] for row in data["run_summary"]]
    assert summary_ids == ["run-success", "run-failed", "run-cancelled"]
    assert data["run_summary"][0]["report_included"] is True
    assert data["run_summary"][1]["report_included"] is False
    assert data["run_summary"][2]["report_included"] is False
    assert [row["run_id"] for row in data["run_metrics"]] == ["run-success"]
    assert [row["run_id"] for row in data["run_costs"]] == ["run-success"]
    assert {row["Run ID"] for row in data["task_table"]} == {"run-success"}
    assert {row["run_id"] for row in data["task_scatter"]} == {"run-success"}


def test_include_failed_runs_override_includes_failed_in_downstream_sections(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data"
    jsonl_dir = tmp_path / "jsonl_bundle"
    write_run_json(
        data_dir,
        [
            make_run(run_id="run-success", group="cpu", tasks=[flat_task()]),
            make_run(run_id="run-failed", group="gpu", tasks=[flat_task()], status="FAILED"),
            make_run(run_id="run-cancelled", group="spot", tasks=[flat_task()], status="CANCELLED"),
        ],
    )
    normalize_jsonl(data_dir, jsonl_dir)

    data = build_report_data(jsonl_dir, include_failed_runs=True)

    overview = {row["run_id"]: row for row in data["benchmark_overview"]}
    assert overview["run-success"]["report_included"] is True
    assert overview["run-failed"]["report_included"] is True
    assert overview["run-failed"]["status_category"] == "failed"
    assert overview["run-cancelled"]["report_included"] is False

    summary = {row["run_id"]: row for row in data["run_summary"]}
    assert summary["run-success"]["report_included"] is True
    assert summary["run-failed"]["report_included"] is True
    assert summary["run-cancelled"]["report_included"] is False

    assert [row["run_id"] for row in data["run_metrics"]] == ["run-success", "run-failed"]
    assert [row["run_id"] for row in data["run_costs"]] == ["run-success", "run-failed"]
    assert {row["Run ID"] for row in data["task_table"]} == {"run-success", "run-failed"}
    assert {row["run_id"] for row in data["task_scatter"]} == {"run-success", "run-failed"}


def test_iter_jsonl_is_lazy(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('{"ok": 1}\nnot-json\n')

    rows = _iter_jsonl(path)
    assert next(rows) == {"ok": 1}


def test_cost_join_uses_process_and_hash(tmp_path):
    jsonl_dir = tmp_path / "jsonl_bundle"
    jsonl_dir.mkdir(parents=True)

    runs = [
        {
            "run_id": "run1",
            "group": "cpu",
            "pipeline": "pipe",
            "username": "u",
            "pipeline_version": "main",
            "nextflow_version": "24.10.0",
            "platform_version": "x",
            "succeeded": 2,
            "failed": 0,
            "cached": 0,
            "executor": "awsbatch",
            "region": "us-east-1",
            "fusion_enabled": False,
            "wave_enabled": False,
            "container_engine": "docker",
            "duration_ms": 10,
            "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0,
            "memory_efficiency": 50.0,
            "read_bytes": 0,
            "write_bytes": 0,
        }
    ]
    tasks = [
        {
            "run_id": "run1",
            "group": "cpu",
            "hash": "ab/cdef12",
            "process": "foo:PROC_A",
            "process_short": "PROC_A",
            "name": "PROC_A",
            "status": "COMPLETED",
            "staging_ms": 0,
            "realtime_ms": 1000,
            "duration_ms": 1000,
            "cost": 1.0,
        },
        {
            "run_id": "run1",
            "group": "cpu",
            "hash": "ab/cdef12",
            "process": "foo:PROC_B",
            "process_short": "PROC_B",
            "name": "PROC_B",
            "status": "COMPLETED",
            "staging_ms": 0,
            "realtime_ms": 1000,
            "duration_ms": 1000,
            "cost": 2.0,
        },
    ]
    costs = [
        {"run_id": "run1", "process": "foo:PROC_A", "hash": "abcdef12", "cost": 5.0, "used_cost": 4.0, "unused_cost": 1.0},
        {"run_id": "run1", "process": "foo:PROC_B", "hash": "abcdef12", "cost": 7.0, "used_cost": 6.0, "unused_cost": 1.0},
    ]

    (jsonl_dir / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    (jsonl_dir / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))
    (jsonl_dir / "costs.jsonl").write_text("".join(json.dumps(c) + "\n" for c in costs))

    data = build_report_data(jsonl_dir)

    assert data["run_costs"][0]["cost"] == 12.0
    assert data["run_costs"][0]["used_cost"] == 10.0
    assert data["run_costs"][0]["unused_cost"] == 2.0

    overview = {row["process_short"]: row for row in data["cost_overview"]}
    assert overview["PROC_A"]["total_cost"] == 5.0
    assert overview["PROC_B"]["total_cost"] == 7.0


def test_combined_task_runtime_splits_by_pipeline_and_group_and_uses_realtime(tmp_path):
    jsonl_dir = tmp_path / "jsonl_bundle"
    jsonl_dir.mkdir(parents=True)

    runs = [
        {
            "run_id": "run1",
            "group": "g1",
            "pipeline": "pipe_alpha",
            "username": "u",
            "pipeline_version": "main",
            "nextflow_version": "24.10.0",
            "platform_version": "x",
            "succeeded": 2,
            "failed": 0,
            "cached": 1,
            "executor": "awsbatch",
            "region": "us-east-1",
            "fusion_enabled": False,
            "wave_enabled": False,
            "container_engine": "docker",
            "duration_ms": 10,
            "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0,
            "memory_efficiency": 50.0,
            "read_bytes": 0,
            "write_bytes": 0,
        },
        {
            "run_id": "run2",
            "group": "g1",
            "pipeline": "rustqc",
            "username": "u",
            "pipeline_version": "main",
            "nextflow_version": "24.10.0",
            "platform_version": "x",
            "succeeded": 1,
            "failed": 0,
            "cached": 0,
            "executor": "awsbatch",
            "region": "us-east-1",
            "fusion_enabled": False,
            "wave_enabled": False,
            "container_engine": "docker",
            "duration_ms": 10,
            "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0,
            "memory_efficiency": 50.0,
            "read_bytes": 0,
            "write_bytes": 0,
        },
        {
            "run_id": "run3",
            "group": "g2",
            "pipeline": "pipe_alpha",
            "username": "u",
            "pipeline_version": "main",
            "nextflow_version": "24.10.0",
            "platform_version": "x",
            "succeeded": 1,
            "failed": 0,
            "cached": 0,
            "executor": "awsbatch",
            "region": "us-east-1",
            "fusion_enabled": False,
            "wave_enabled": False,
            "container_engine": "docker",
            "duration_ms": 10,
            "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0,
            "memory_efficiency": 50.0,
            "read_bytes": 0,
            "write_bytes": 0,
        },
    ]
    tasks = [
        {
            "run_id": "run1",
            "group": "g1",
            "hash": "ab/cdef12",
            "process": "PIPE:QC_STEP",
            "process_short": "QC_STEP",
            "name": "PIPE:QC_STEP",
            "status": "COMPLETED",
            "wait_ms": 10000,
            "staging_ms": 0,
            "realtime_ms": 60000,
            "duration_ms": 300000,
            "cost": 1.0,
        },
        {
            "run_id": "run1",
            "group": "g1",
            "hash": "ab/cdef13",
            "process": "PIPE:MAIN",
            "process_short": "MAIN",
            "name": "PIPE:MAIN",
            "status": "COMPLETED",
            "wait_ms": 20000,
            "staging_ms": 0,
            "realtime_ms": 120000,
            "duration_ms": 999999,
            "cost": 1.0,
        },
        {
            "run_id": "run1",
            "group": "g1",
            "hash": "ab/cdef14",
            "process": "PIPE:CACHED",
            "process_short": "CACHED",
            "name": "PIPE:CACHED",
            "status": "CACHED",
            "wait_ms": 600000,
            "staging_ms": 0,
            "realtime_ms": 500000,
            "duration_ms": 500000,
            "cost": 1.0,
        },
        {
            "run_id": "run2",
            "group": "g1",
            "hash": "ab/cdef15",
            "process": "RUSTQC:ASSEMBLE",
            "process_short": "ASSEMBLE",
            "name": "RUSTQC:ASSEMBLE",
            "status": "COMPLETED",
            "wait_ms": 15000,
            "staging_ms": 0,
            "realtime_ms": 30000,
            "duration_ms": 400000,
            "cost": 1.0,
        },
        {
            "run_id": "run3",
            "group": "g2",
            "hash": "ab/cdef16",
            "process": "PIPE:RSEQC_SUMMARY",
            "process_short": "RSEQC_SUMMARY",
            "name": "PIPE:RSEQC_SUMMARY",
            "status": "COMPLETED",
            "wait_ms": 5000,
            "staging_ms": 0,
            "realtime_ms": 40000,
            "duration_ms": 700000,
            "cost": 1.0,
        },
    ]

    (jsonl_dir / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    (jsonl_dir / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))

    data = build_report_data(jsonl_dir)
    panels = {panel["panel_id"]: panel for panel in data["combined_task_runtime"]}

    assert set(panels.keys()) == {"pipe_alpha::g1", "rustqc::g1", "pipe_alpha::g2"}

    p1 = panels["pipe_alpha::g1"]
    assert p1["total_runtime_ms"] == 180000
    assert p1["scheduling_runtime_ms"] == 30000
    assert p1["total_duration_ms"] == 210000
    assert p1["total_tasks"] == 2
    assert p1["unique_processes"] == 2
    assert p1["segments"][0]["process"] == "PIPE:MAIN"
    assert p1["segments"][0]["runtime_ms"] == 120000
    assert p1["segments"][1]["process"] == "PIPE:QC_STEP"
    assert p1["segments"][1]["highlight"] is True
    assert p1["highlight_totals"]["qc_runtime_ms"] == 60000
    assert p1["highlight_totals"]["other_runtime_ms"] == 120000

    rustqc = panels["rustqc::g1"]
    assert rustqc["pipeline"] == "rustqc"
    assert rustqc["total_runtime_ms"] == 30000
    assert rustqc["scheduling_runtime_ms"] == 15000
    assert rustqc["total_duration_ms"] == 45000

    p2 = panels["pipe_alpha::g2"]
    assert p2["segments"][0]["highlight"] is True
    assert p2["highlight_totals"]["qc_runtime_ms"] == 40000
    assert p2["scheduling_runtime_ms"] == 5000
    assert p2["total_duration_ms"] == 45000


def test_vm_metrics_merged_into_run_metrics(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data"
    jsonl_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task()])])
    normalize_jsonl(data_dir, jsonl_dir)

    machines = [{"run_id": "run1", "n_machines": 3, "vm_cpu_h": 12.5, "vm_mem_gib_h": 48.0, "sched_alloc_cpu_efficiency": 65.0, "sched_alloc_mem_efficiency": 42.0}]
    (jsonl_dir / "machines.jsonl").write_text(json.dumps(machines[0]) + "\n")

    data = build_report_data(jsonl_dir)
    m = data["run_metrics"][0]
    assert m["vmCpuH"] == 12.5
    assert m["nMachines"] == 3
    assert m["schedAllocCpuEfficiency"] == 65.0


def test_combined_task_runtime_legend_rollup(tmp_path):
    jsonl_dir = tmp_path / "jsonl_bundle"
    jsonl_dir.mkdir(parents=True)

    runs = [
        {
            "run_id": "run1",
            "group": "g1",
            "pipeline": "pipe_alpha",
            "username": "u",
            "pipeline_version": "main",
            "nextflow_version": "24.10.0",
            "platform_version": "x",
            "succeeded": 22,
            "failed": 0,
            "cached": 0,
            "executor": "awsbatch",
            "region": "us-east-1",
            "fusion_enabled": False,
            "wave_enabled": False,
            "container_engine": "docker",
            "duration_ms": 10,
            "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0,
            "memory_efficiency": 50.0,
            "read_bytes": 0,
            "write_bytes": 0,
        }
    ]

    tasks = []
    for i in range(22):
        tasks.append(
            {
                "run_id": "run1",
                "group": "g1",
                "hash": f"ab/cdef{i:02d}",
                "process": f"PIPE:PROC_{i:02d}",
                "process_short": f"PROC_{i:02d}",
                "name": f"PIPE:PROC_{i:02d}",
                "status": "COMPLETED",
                "wait_ms": i * 100,
                "staging_ms": 0,
                "realtime_ms": 22000 - i,
                "duration_ms": 100000 + i,
                "cost": 1.0,
            }
        )

    (jsonl_dir / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    (jsonl_dir / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))

    data = build_report_data(jsonl_dir)
    panel = data["combined_task_runtime"][0]

    assert len(panel["segments"]) == 22
    assert len(panel["legend"]) == 21
    assert panel["scheduling_runtime_ms"] == sum(i * 100 for i in range(22))
    assert panel["total_duration_ms"] == panel["total_runtime_ms"] + panel["scheduling_runtime_ms"]
    assert panel["legend"][-1]["process"] == "Other (2 small processes)"
    assert panel["legend"][-1]["runtime_ms"] == panel["segments"][-1]["runtime_ms"] + panel["segments"][-2]["runtime_ms"]


def test_positive_gap():
    assert _positive_gap(10.0, 3.0) == 7.0
    assert _positive_gap(3.0, 10.0) == 0.0
    assert _positive_gap(None, 5.0) is None
    assert _positive_gap(5.0, None) is None


def test_compute_scheduler_booked():
    # capacity=100, efficiency=80% → booked = min(100, max(0, 80)) = 80
    assert _compute_scheduler_booked(100.0, 80.0) == 80.0
    # efficiency > 100 → clamped to capacity
    assert _compute_scheduler_booked(100.0, 150.0) == 100.0
    # missing capacity → fallback
    assert _compute_scheduler_booked(None, 80.0, fallback=5.0) == 5.0
    # missing efficiency → fallback
    assert _compute_scheduler_booked(100.0, None, fallback=5.0) == 5.0
    # negative fallback → clamped to 0
    assert _compute_scheduler_booked(None, None, fallback=-2.0) == 0.0
    # no fallback → None
    assert _compute_scheduler_booked(None, None) is None


def test_build_workspace_run_url_prefers_existing_url():
    assert (
        _build_workspace_run_url(
            run_id="run1",
            workspace="ignored/ws",
            platform="https://cloud.seqera.io",
            existing_url="https://custom.example/run1",
        )
        == "https://custom.example/run1"
    )


def test_build_workspace_run_url_requires_workspace_and_platform():
    assert _build_workspace_run_url("run1", None, None) == ""
    assert _build_workspace_run_url("run1", "org/ws", None) == ""
    assert _build_workspace_run_url("run1", None, "https://cloud.dev-seqera.io") == ""


def test_build_workspace_run_url_builds_from_explicit_metadata():
    assert (
        _build_workspace_run_url(
            "dev-run",
            "unified-compute/sched-testing",
            "https://cloud.dev-seqera.io",
        )
        == "https://cloud.dev-seqera.io/orgs/unified-compute/workspaces/sched-testing/watch/dev-run"
    )
    assert (
        _build_workspace_run_url(
            "batch-run",
            "scidev/testing",
            "https://cloud.seqera.io",
        )
        == "https://cloud.seqera.io/orgs/scidev/workspaces/testing/watch/batch-run"
    )


def test_build_report_data_adds_run_urls(tmp_path):
    jsonl_dir = tmp_path / "jsonl_bundle"
    jsonl_dir.mkdir(parents=True)

    runs = [
        {
            "run_id": "sched1",
            "group": "cpu",
            "pipeline": "pipe",
            "workspace": "unified-compute/sched-testing",
            "platform": "https://cloud.dev-seqera.io",
            "username": "u",
            "pipeline_version": "main",
            "nextflow_version": "24.10.0",
            "platform_version": "x",
            "succeeded": 1,
            "failed": 0,
            "cached": 0,
            "status": "SUCCEEDED",
            "executor": "awsbatch",
            "region": "us-east-1",
            "fusion_enabled": False,
            "wave_enabled": False,
            "container_engine": "docker",
            "duration_ms": 10,
            "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0,
            "memory_efficiency": 50.0,
            "read_bytes": 0,
            "write_bytes": 0,
        },
        {
            "run_id": "batch1",
            "group": "Batch-baseline",
            "pipeline": "pipe",
            "workspace": "scidev/testing",
            "platform": "https://cloud.seqera.io",
            "username": "u",
            "pipeline_version": "main",
            "nextflow_version": "24.10.0",
            "platform_version": "x",
            "succeeded": 1,
            "failed": 0,
            "cached": 0,
            "status": "SUCCEEDED",
            "executor": "awsbatch",
            "region": "us-east-1",
            "fusion_enabled": False,
            "wave_enabled": False,
            "container_engine": "docker",
            "duration_ms": 10,
            "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0,
            "memory_efficiency": 50.0,
            "read_bytes": 0,
            "write_bytes": 0,
        },
        {
            "run_id": "nolink1",
            "group": "cpu",
            "pipeline": "pipe",
            "workspace": "unified-compute/sched-testing",
            "platform": "",
            "username": "u",
            "pipeline_version": "main",
            "nextflow_version": "24.10.0",
            "platform_version": "x",
            "succeeded": 1,
            "failed": 0,
            "cached": 0,
            "status": "SUCCEEDED",
            "executor": "awsbatch",
            "region": "us-east-1",
            "fusion_enabled": False,
            "wave_enabled": False,
            "container_engine": "docker",
            "duration_ms": 10,
            "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0,
            "memory_efficiency": 50.0,
            "read_bytes": 0,
            "write_bytes": 0,
        },
    ]

    tasks = [
        {"run_id": "sched1", "group": "cpu", "hash": "aa/bbccdd", "process": "P:A", "process_short": "A", "name": "A", "status": "COMPLETED", "staging_ms": 0, "realtime_ms": 1000, "duration_ms": 1000, "cost": 0.0, "cpus": 1, "pcpu": 100.0, "memory_bytes": 1024**3, "peak_rss": 512**3},
        {"run_id": "batch1", "group": "Batch-baseline", "hash": "ee/ffgghh", "process": "P:B", "process_short": "B", "name": "B", "status": "COMPLETED", "staging_ms": 0, "realtime_ms": 1000, "duration_ms": 1000, "cost": 0.0, "cpus": 1, "pcpu": 100.0, "memory_bytes": 1024**3, "peak_rss": 512**3},
        {"run_id": "nolink1", "group": "cpu", "hash": "ii/jjkkll", "process": "P:C", "process_short": "C", "name": "C", "status": "COMPLETED", "staging_ms": 0, "realtime_ms": 1000, "duration_ms": 1000, "cost": 0.0, "cpus": 1, "pcpu": 100.0, "memory_bytes": 1024**3, "peak_rss": 512**3},
    ]

    (jsonl_dir / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    (jsonl_dir / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))

    data = build_report_data(jsonl_dir)
    summary = {row["run_id"]: row for row in data["run_summary"]}
    metrics = {row["run_id"]: row for row in data["run_metrics"]}

    assert summary["sched1"]["runUrl"] == "https://cloud.dev-seqera.io/orgs/unified-compute/workspaces/sched-testing/watch/sched1"
    assert summary["batch1"]["runUrl"] == "https://cloud.seqera.io/orgs/scidev/workspaces/testing/watch/batch1"
    assert summary["nolink1"]["runUrl"] == ""
    assert metrics["sched1"]["runUrl"].endswith("/sched1")
    assert metrics["batch1"]["runUrl"].endswith("/batch1")
    assert metrics["nolink1"]["runUrl"] == ""


def test_scheduler_performance_fields_with_vm(tmp_path):
    """Full scheduler-performance layer when machines.jsonl is present."""
    jsonl_dir = tmp_path / "jsonl_bundle"
    jsonl_dir.mkdir(parents=True)

    runs = [
        {
            "run_id": "run1", "group": "cpu", "pipeline": "pipe",
            "username": "u", "pipeline_version": "main",
            "nextflow_version": "24.10.0", "platform_version": "x",
            "succeeded": 1, "failed": 0, "cached": 0, "status": "SUCCEEDED",
            "executor": "awsbatch", "region": "us-east-1",
            "fusion_enabled": False, "wave_enabled": False,
            "container_engine": "docker",
            "duration_ms": 10, "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0, "memory_efficiency": 50.0,
            "read_bytes": 0, "write_bytes": 0,
        }
    ]
    # 1 task: 4 cpus, 3600s realtime → requested_cpu_h = 4.0
    # pcpu=200 → real_cpu_h = 2.0 * 1h = 2.0
    # memory_bytes = 8 GiB, peak_rss = 4 GiB
    tasks = [
        {
            "run_id": "run1", "group": "cpu",
            "hash": "ab/cdef12", "process": "P:A", "process_short": "A",
            "name": "A", "status": "COMPLETED",
            "staging_ms": 0, "realtime_ms": 3_600_000, "duration_ms": 3_600_000,
            "cost": 1.0, "cpus": 4, "pcpu": 200.0,
            "memory_bytes": 8 * 1024**3, "peak_rss": 4 * 1024**3,
        }
    ]
    machines = [
        {
            "run_id": "run1", "n_machines": 2,
            "vm_cpu_h": 10.0, "vm_mem_gib_h": 20.0,
            "sched_alloc_cpu_efficiency": 80.0,
            "sched_alloc_mem_efficiency": 60.0,
        }
    ]

    (jsonl_dir / "runs.jsonl").write_text(json.dumps(runs[0]) + "\n")
    (jsonl_dir / "tasks.jsonl").write_text(json.dumps(tasks[0]) + "\n")
    (jsonl_dir / "machines.jsonl").write_text(json.dumps(machines[0]) + "\n")

    data = build_report_data(jsonl_dir)
    m = data["run_metrics"][0]

    # Task-derived
    assert m["requestedCpuH"] == 4.0
    assert m["requestedMemGibH"] == 8.0
    assert m["realCpuH"] == 2.0
    assert m["realMemGibH"] == 4.0

    # Efficiency vs VM
    assert m["requestedVmCpuEfficiency"] == 40.0   # 4/10*100
    assert m["requestedVmMemEfficiency"] == 40.0    # 8/20*100
    assert m["realVmCpuEfficiency"] == 20.0         # 2/10*100
    assert m["realVmMemEfficiency"] == 20.0         # 4/20*100

    # schedulerBooked = min(capacity, capacity * eff / 100)
    # cpu: min(10, 10*80/100) = 8.0;  mem: min(20, 20*60/100) = 12.0
    assert m["schedulerBookedCpuH"] == 8.0
    assert m["schedulerBookedMemGibH"] == 12.0

    # rightsized = max(requested - booked, 0)
    assert m["schedulerRightsizedCpuH"] == 0.0   # 4 - 8 → 0
    assert m["schedulerRightsizedMemGibH"] == 0.0  # 8 - 12 → 0

    # overbook = max(booked - real, 0)
    assert m["schedulerOverbookCpuH"] == 6.0     # 8 - 2
    assert m["schedulerOverbookMemGibH"] == 8.0  # 12 - 4

    # vmPackingSlack = max(vm - booked, 0)
    assert m["vmPackingSlackCpuH"] == 2.0        # 10 - 8
    assert m["vmPackingSlackMemGibH"] == 8.0     # 20 - 12


def test_scheduler_performance_fields_without_vm(tmp_path):
    """Without machines.jsonl, task-derived fields present, VM-derived are None."""
    jsonl_dir = tmp_path / "jsonl_bundle"
    jsonl_dir.mkdir(parents=True)

    runs = [
        {
            "run_id": "run1", "group": "cpu", "pipeline": "pipe",
            "username": "u", "pipeline_version": "main",
            "nextflow_version": "24.10.0", "platform_version": "x",
            "succeeded": 1, "failed": 0, "cached": 0, "status": "SUCCEEDED",
            "executor": "awsbatch", "region": "us-east-1",
            "fusion_enabled": False, "wave_enabled": False,
            "container_engine": "docker",
            "duration_ms": 10, "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0, "memory_efficiency": 50.0,
            "read_bytes": 0, "write_bytes": 0,
        }
    ]
    tasks = [
        {
            "run_id": "run1", "group": "cpu",
            "hash": "ab/cdef12", "process": "P:A", "process_short": "A",
            "name": "A", "status": "COMPLETED",
            "staging_ms": 0, "realtime_ms": 3_600_000, "duration_ms": 3_600_000,
            "cost": 1.0, "cpus": 2, "pcpu": 100.0,
            "memory_bytes": 4 * 1024**3, "peak_rss": 2 * 1024**3,
        }
    ]

    (jsonl_dir / "runs.jsonl").write_text(json.dumps(runs[0]) + "\n")
    (jsonl_dir / "tasks.jsonl").write_text(json.dumps(tasks[0]) + "\n")

    data = build_report_data(jsonl_dir)
    m = data["run_metrics"][0]

    assert m["requestedCpuH"] == 2.0
    assert m["realCpuH"] == 1.0
    # No VM → schedulerBooked falls back to max(requested, 0)
    assert m["schedulerBookedCpuH"] == 2.0
    assert m["schedulerBookedMemGibH"] == 4.0
    # VM efficiency fields are None
    assert m["requestedVmCpuEfficiency"] is None
    assert m["realVmCpuEfficiency"] is None
    assert m["vmPackingSlackCpuH"] is None


def test_pr132_style_scheduler_vm_semantics(tmp_path):
    jsonl_dir = tmp_path / "jsonl_bundle"
    jsonl_dir.mkdir(parents=True)

    runs = [
        {
            "run_id": "batch-run",
            "group": "Batch-OnD",
            "pipeline": "nf-core/rnaseq",
            "username": "u",
            "pipeline_version": "main",
            "nextflow_version": "24.10.0",
            "platform_version": "x",
            "succeeded": 1,
            "failed": 0,
            "cached": 0,
            "status": "SUCCEEDED",
            "executor": "awsbatch",
            "region": "eu-west-1",
            "fusion_enabled": True,
            "wave_enabled": True,
            "container_engine": "docker",
            "duration_ms": 10,
            "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0,
            "memory_efficiency": 50.0,
            "read_bytes": 0,
            "write_bytes": 0,
        },
        {
            "run_id": "sched-run",
            "group": "Sched-SpotFirst-Predv1",
            "pipeline": "nf-core/rnaseq",
            "username": "u",
            "pipeline_version": "main",
            "nextflow_version": "26.03.0-edge",
            "platform_version": "x",
            "succeeded": 1,
            "failed": 0,
            "cached": 0,
            "status": "SUCCEEDED",
            "executor": "awsbatch",
            "region": "eu-west-1",
            "fusion_enabled": True,
            "wave_enabled": True,
            "container_engine": "docker",
            "duration_ms": 10,
            "cpu_time_ms": 1000,
            "cpu_efficiency": 50.0,
            "memory_efficiency": 50.0,
            "read_bytes": 0,
            "write_bytes": 0,
        },
    ]
    tasks = [
        {
            "run_id": "batch-run",
            "group": "Batch-OnD",
            "hash": "ab/cdef12",
            "process": "NFCORE_RNASEQ:FASTQC",
            "process_short": "FASTQC",
            "name": "FASTQC",
            "status": "COMPLETED",
            "staging_ms": 0,
            "realtime_ms": 3_600_000,
            "duration_ms": 3_600_000,
            "cost": 1.0,
            "cpus": 4,
            "memory_bytes": 16 * 1024**3,
            "pcpu": 300.0,
            "peak_rss": 8 * 1024**3,
            "machine_type": "c6id.8xlarge",
            "cloud_zone": "eu-west-1a",
            "executor": "awsbatch",
        },
        {
            "run_id": "sched-run",
            "group": "Sched-SpotFirst-Predv1",
            "hash": "ab/cdef34",
            "process": "NFCORE_RNASEQ:FASTQC",
            "process_short": "FASTQC",
            "name": "FASTQC",
            "status": "COMPLETED",
            "staging_ms": 0,
            "realtime_ms": 3_600_000,
            "duration_ms": 3_600_000,
            "cost": 1.0,
            "cpus": 4,
            "memory_bytes": 16 * 1024**3,
            "pcpu": 200.0,
            "peak_rss": 8 * 1024**3,
            "machine_type": "m7i.4xlarge",
            "cloud_zone": "eu-west-1b",
            "executor": "awsbatch",
        },
    ]
    machines = [
        {
            "run_id": "batch-run",
            "n_machines": 2,
            "vm_cpu_h": 4.0,
            "vm_mem_gib_h": 16.0,
            "sched_alloc_cpu_efficiency": 100.0,
            "sched_alloc_mem_efficiency": 100.0,
        },
        {
            "run_id": "sched-run",
            "n_machines": 1,
            "vm_cpu_h": 6.0,
            "vm_mem_gib_h": 24.0,
            "sched_alloc_cpu_efficiency": 50.0,
            "sched_alloc_mem_efficiency": 50.0,
        },
    ]

    (jsonl_dir / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    (jsonl_dir / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))
    (jsonl_dir / "machines.jsonl").write_text("".join(json.dumps(m) + "\n" for m in machines))

    data = build_report_data(jsonl_dir)
    metrics = {row["group"]: row for row in data["run_metrics"]}

    batch = metrics["Batch-OnD"]
    sched = metrics["Sched-SpotFirst-Predv1"]

    assert batch["nMachines"] == 2
    assert batch["schedulerBookedCpuH"] == 4.0
    assert batch["schedulerRightsizedCpuH"] == 0.0
    assert batch["schedulerOverbookCpuH"] == 1.0
    assert batch["vmPackingSlackCpuH"] == 0.0
    assert batch["realVmCpuEfficiency"] == 75.0

    assert sched["nMachines"] == 1
    assert sched["schedulerBookedCpuH"] == 3.0
    assert sched["schedulerRightsizedCpuH"] == 1.0
    assert sched["schedulerOverbookCpuH"] == 1.0
    assert sched["vmPackingSlackCpuH"] == 3.0
    assert sched["realVmCpuEfficiency"] == 33.33

def test_classify_missing_cost_recent_run_is_propagating():
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    recent = (now - timedelta(hours=3)).isoformat()
    assert _classify_missing_cost(recent, now) == "propagating"


def test_classify_missing_cost_old_run_is_not_found():
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    old = (now - timedelta(days=5)).isoformat()
    assert _classify_missing_cost(old, now) == "not_found"


def test_classify_missing_cost_boundary_uses_24h_window():
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    just_inside = (now - timedelta(hours=23, minutes=59)).isoformat()
    just_outside = (now - timedelta(hours=24, minutes=1)).isoformat()
    assert _classify_missing_cost(just_inside, now) == "propagating"
    assert _classify_missing_cost(just_outside, now) == "not_found"


def test_classify_missing_cost_handles_z_suffix_and_missing_timestamp():
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    assert _classify_missing_cost("2026-07-16T10:00:00Z", now) == "propagating"
    assert _classify_missing_cost(None, now) == "not_found"
    assert _classify_missing_cost("not-a-timestamp", now) == "not_found"


def _write_cost_status_bundle(jsonl_dir, complete_ts):
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    runs = [
        {"run_id": "run_ok", "group": "g", "pipeline": "p", "status": "SUCCEEDED", "complete": complete_ts},
        {"run_id": "run_missing", "group": "g", "pipeline": "p", "status": "SUCCEEDED", "complete": complete_ts},
    ]
    tasks = [
        {"run_id": "run_ok", "group": "g", "hash": "ab/cdef12", "process": "foo:PROC", "process_short": "PROC",
         "name": "PROC", "status": "COMPLETED", "staging_ms": 0, "realtime_ms": 1000, "duration_ms": 1000, "cost": 0.0},
        {"run_id": "run_missing", "group": "g", "hash": "cd/ef3456", "process": "foo:PROC", "process_short": "PROC",
         "name": "PROC", "status": "COMPLETED", "staging_ms": 0, "realtime_ms": 1000, "duration_ms": 1000, "cost": 0.0},
    ]
    # Only run_ok has a matching CUR cost row; run_missing has none.
    costs = [
        {"run_id": "run_ok", "process": "foo:PROC", "hash": "abcdef12", "cost": 5.0, "used_cost": 4.0, "unused_cost": 1.0},
    ]
    (jsonl_dir / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    (jsonl_dir / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))
    (jsonl_dir / "costs.jsonl").write_text("".join(json.dumps(c) + "\n" for c in costs))


def test_run_costs_flag_recent_missing_as_propagating(tmp_path):
    jsonl_dir = tmp_path / "jsonl_bundle"
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _write_cost_status_bundle(jsonl_dir, recent)

    costs = {row["run_id"]: row for row in build_report_data(jsonl_dir)["run_costs"]}

    assert costs["run_ok"]["cost_status"] == "available"
    assert costs["run_ok"]["cost"] == 5.0

    missing = costs["run_missing"]
    assert missing["cost_status"] == "propagating"
    assert missing["cost"] is None
    assert missing["used_cost"] is None
    assert missing["unused_cost"] is None


def test_run_costs_flag_old_missing_as_not_found(tmp_path):
    jsonl_dir = tmp_path / "jsonl_bundle"
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    _write_cost_status_bundle(jsonl_dir, old)

    costs = {row["run_id"]: row for row in build_report_data(jsonl_dir)["run_costs"]}

    assert costs["run_ok"]["cost_status"] == "available"
    assert costs["run_missing"]["cost_status"] == "not_found"
    assert costs["run_missing"]["cost"] is None


def test_run_costs_without_cur_have_no_cost_status(tmp_path, make_run, flat_task, write_run_json):
    from benchmark_report_normalize import normalize_jsonl

    data_dir = tmp_path / "data"
    jsonl_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task(cost=4.2)])])
    normalize_jsonl(data_dir, jsonl_dir)

    assert build_report_data(jsonl_dir)["run_costs"][0]["cost_status"] is None


def _resume_bundle(jsonl_dir, runs, tasks, costs):
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    (jsonl_dir / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    (jsonl_dir / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))
    (jsonl_dir / "costs.jsonl").write_text("".join(json.dumps(c) + "\n" for c in costs))


def _run_row(run_id, session_id="", resumed=False, cached=0, succeeded=1, complete="2026-01-02T00:00:00Z"):
    return {
        "run_id": run_id,
        "group": "cpu",
        "pipeline": "pipe",
        "session_id": session_id,
        "resumed": resumed,
        "cached": cached,
        "succeeded": succeeded,
        "failed": 0,
        "complete": complete,
        "duration_ms": 10,
        "cpu_time_ms": 1000,
    }


def _task_row(run_id, process_short, hash_short, status="COMPLETED"):
    return {
        "run_id": run_id,
        "group": "cpu",
        "hash": hash_short,
        "process": f"foo:{process_short}",
        "process_short": process_short,
        "name": process_short,
        "status": status,
        "staging_ms": 0,
        "realtime_ms": 1000,
        "duration_ms": 1000,
    }


def _cost_row(run_id, session_id, process_short, hash_short, cost):
    return {
        "run_id": run_id,
        "session_id": session_id,
        "process": f"foo:{process_short}",
        "hash": hash_short,
        "cost": cost,
        "used_cost": cost,
        "unused_cost": 0.0,
        "unblended_cost": cost,
    }


def test_resumed_run_cost_pools_every_attempt_of_its_session(tmp_path):
    """A resumed run is billed across its session: attempt 1's spend belongs to it too."""
    jsonl_dir = tmp_path / "jsonl_bundle"
    _resume_bundle(
        jsonl_dir,
        runs=[_run_row("attempt2", session_id="sess-1", resumed=True, cached=1, succeeded=1)],
        tasks=[
            # PROC_A was cached from attempt 1; PROC_B ran in this attempt.
            _task_row("attempt2", "PROC_A", "aa/aaaa11", status="CACHED"),
            _task_row("attempt2", "PROC_B", "bb/bbbb22"),
        ],
        costs=[
            _cost_row("attempt1", "sess-1", "PROC_A", "aaaaaa11", 4.0),
            _cost_row("attempt2", "sess-1", "PROC_B", "bbbbbb22", 6.0),
        ],
    )

    data = build_report_data(jsonl_dir)
    cost_row = data["run_costs"][0]

    assert cost_row["cost"] == 10.0, "pooled across both attempts"
    assert cost_row["cost_last_attempt"] == 6.0, "ratio-safe figure stays this attempt only"
    assert cost_row["attempts"] == 2
    assert cost_row["session_pooled"] is True
    assert cost_row["cost_status"] == "available"

    # The cached task now resolves to the attempt that actually paid for it, so coverage is
    # complete and the earlier attempt's cost lands in the per-process overview.
    assert data["cost_coverage"]["missing_task_count"] == 0
    assert data["cost_coverage"]["n_incomplete_lineages"] == 0
    overview = {row["process_short"]: row["total_cost"] for row in data["cost_overview"]}
    assert overview == {"PROC_A": 4.0, "PROC_B": 6.0}

    resumed = data["cost_coverage"]["resumed_runs"]
    assert [(r["run_id"], r["attempts"], r["cached_tasks"]) for r in resumed] == [("attempt2", 2, 1)]


def test_non_resumed_run_ignores_other_attempts_sharing_a_session(tmp_path):
    """No cached tasks -> no pooling, even when the session has other billed attempts."""
    jsonl_dir = tmp_path / "jsonl_bundle"
    _resume_bundle(
        jsonl_dir,
        runs=[_run_row("attempt1", session_id="sess-1")],
        tasks=[_task_row("attempt1", "PROC_A", "aa/aaaa11")],
        costs=[
            _cost_row("attempt1", "sess-1", "PROC_A", "aaaaaa11", 4.0),
            _cost_row("attempt2", "sess-1", "PROC_B", "bbbbbb22", 6.0),
        ],
    )

    data = build_report_data(jsonl_dir)

    assert data["run_costs"][0]["cost"] == 4.0
    assert data["run_costs"][0]["attempts"] == 1
    assert data["run_costs"][0]["session_pooled"] is False
    assert data["cost_coverage"]["resumed_runs"] == []


def test_two_attempts_of_one_session_do_not_double_count(tmp_path):
    """Only the newest attempt claims the pool, so the same dollars appear once."""
    jsonl_dir = tmp_path / "jsonl_bundle"
    _resume_bundle(
        jsonl_dir,
        runs=[
            _run_row(
                "attempt2", session_id="sess-1", resumed=True, cached=1,
                complete="2026-01-02T00:00:00Z",
            ),
            _run_row(
                "attempt3", session_id="sess-1", resumed=True, cached=2,
                complete="2026-01-03T00:00:00Z",
            ),
        ],
        tasks=[
            _task_row("attempt2", "PROC_C", "cc/cccc33"),
            _task_row("attempt3", "PROC_B", "bb/bbbb22"),
            _task_row("attempt3", "PROC_A", "aa/aaaa11", status="CACHED"),
        ],
        costs=[
            _cost_row("attempt1", "sess-1", "PROC_A", "aaaaaa11", 4.0),
            _cost_row("attempt2", "sess-1", "PROC_C", "cccccc33", 5.0),
            _cost_row("attempt3", "sess-1", "PROC_B", "bbbbbb22", 6.0),
        ],
    )

    data = build_report_data(jsonl_dir)
    by_run = {row["run_id"]: row for row in data["run_costs"]}

    assert by_run["attempt3"]["cost"] == 15.0, "newest attempt owns the whole session"
    assert by_run["attempt3"]["session_pooled"] is True
    assert by_run["attempt2"]["cost"] == 5.0, "older attempt keeps only its own spend"
    assert by_run["attempt2"]["session_pooled"] is False
    assert sum(row["cost"] for row in data["run_costs"]) == 20.0, "15 + its own 5, never 15 + 15"


def test_incomplete_lineage_is_flagged_not_presented_as_complete(tmp_path, capsys):
    """Fewer billed task hashes than the run has tasks -> pooled cost is a floor."""
    jsonl_dir = tmp_path / "jsonl_bundle"
    _resume_bundle(
        jsonl_dir,
        runs=[_run_row("attempt2", session_id="sess-1", resumed=True, cached=2, succeeded=1)],
        tasks=[
            _task_row("attempt2", "PROC_A", "aa/aaaa11", status="CACHED"),
            _task_row("attempt2", "PROC_C", "cc/cccc33", status="CACHED"),
            _task_row("attempt2", "PROC_B", "bb/bbbb22"),
        ],
        # PROC_C's original attempt is missing from this export entirely.
        costs=[
            _cost_row("attempt1", "sess-1", "PROC_A", "aaaaaa11", 4.0),
            _cost_row("attempt2", "sess-1", "PROC_B", "bbbbbb22", 6.0),
        ],
    )

    data = build_report_data(jsonl_dir)
    resumed = data["cost_coverage"]["resumed_runs"][0]

    assert resumed["lineage_incomplete"] is True
    assert (resumed["pool_task_count"], resumed["total_tasks"]) == (2, 3)
    assert data["cost_coverage"]["n_incomplete_lineages"] == 1
    assert "lower bound" in capsys.readouterr().err
