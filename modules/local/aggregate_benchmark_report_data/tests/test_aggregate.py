import json

from benchmark_report_aggregate import _iter_jsonl, build_report_data
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
    }


def test_run_costs_without_cur_uses_task_cost(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data"
    jsonl_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task(cost=4.2)])])
    normalize_jsonl(data_dir, jsonl_dir)

    data = build_report_data(jsonl_dir)
    assert data["run_costs"][0]["cost"] == 4.2
    assert data["run_costs"][0]["used_cost"] is None


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


def test_task_table_includes_cached(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data"
    jsonl_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task(status="COMPLETED"), flat_task(status="CACHED")])])
    normalize_jsonl(data_dir, jsonl_dir)

    data = build_report_data(jsonl_dir)
    statuses = {row["Status"] for row in data["task_table"]}
    assert statuses == {"COMPLETED", "CACHED"}


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
