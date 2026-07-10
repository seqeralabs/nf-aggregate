from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent
BIN_DIRS = [
    REPO_ROOT / "bin",
    REPO_ROOT / "modules" / "local" / "normalize_benchmark_jsonl" / "bin",
    REPO_ROOT / "modules" / "local" / "aggregate_benchmark_report_data" / "bin",
    REPO_ROOT / "modules" / "local" / "render_benchmark_report" / "bin",
    REPO_ROOT / "modules" / "local" / "aggregate_ic_report_data" / "bin",
    REPO_ROOT / "modules" / "local" / "render_ic_report" / "bin",
]
for bin_dir in BIN_DIRS:
    if str(bin_dir) not in sys.path:
        sys.path.insert(0, str(bin_dir))


@pytest.fixture
def make_run():
    def _make_run(
        run_id: str = "run1",
        group: str = "cpu",
        tasks: list | None = None,
        cached_count: int = 0,
        status: str = "SUCCEEDED",
    ):
        task_list = tasks or []
        return {
            "workflow": {
                "id": run_id,
                "status": status,
                "userName": "test",
                "repository": "https://github.com/test/pipeline",
                "revision": "main",
                "nextflow": {"version": "24.04.2"},
                "stats": {
                    "succeedCount": len(task_list),
                    "failedCount": 0,
                    "cachedCount": cached_count,
                },
                "duration": 3600000,
            },
            "metrics": [],
            "tasks": task_list,
            "progress": {"workflowProgress": {"cpuEfficiency": 50.0, "memoryEfficiency": 30.0, "cpuTime": 1000}},
            "meta": {"id": run_id, "workspace": "org/ws", "group": group},
        }

    return _make_run


@pytest.fixture
def flat_task():
    def _flat_task(name: str = "PROCESS_A", hash_val: str = "ab/cd1234", cost: float = 1.5, status: str = "COMPLETED"):
        return {
            "name": name,
            "hash": hash_val,
            "process": name,
            "status": status,
            "cpus": 4,
            "memory": 8_000_000_000,
            "realtime": 60000,
            "peakRss": 4_000_000_000,
            "cost": cost,
            "executor": "awsbatch",
            "machineType": "m5.xlarge",
            "cloudZone": "us-east-1a",
            "duration": 65000,
            "submit": "2024-01-01T00:00:00Z",
            "start": "2024-01-01T00:00:10Z",
            "complete": "2024-01-01T00:01:20Z",
        }

    return _flat_task


@pytest.fixture
def nested_task(flat_task):
    def _nested_task(**kwargs):
        return {"task": flat_task(**kwargs)}

    return _nested_task


@pytest.fixture
def write_run_json():
    def _write_run_json(data_dir: Path, runs: list[dict]):
        data_dir.mkdir(parents=True, exist_ok=True)
        for i, run in enumerate(runs):
            (data_dir / f"run_{i}.json").write_text(json.dumps(run))

    return _write_run_json


@pytest.fixture
def pr132_scheduler_vm_report_data():
    fixture_path = REPO_ROOT / "modules" / "local" / "render_benchmark_report" / "tests" / "fixtures" / "pr132_scheduler_vm_report_data.json"
    return json.loads(fixture_path.read_text())


@pytest.fixture
def minimal_report_data():
    return {
        "benchmark_overview": [
            {
                "pipeline": "pipeline",
                "group": "cpu",
                "run_id": "run1",
                "status": "SUCCEEDED",
                "status_label": "Succeeded",
                "status_category": "success",
                "report_included": True,
            }
        ],
        "run_summary": [{"group": "cpu", "run_id": "run1", "cachedCount": 1, "status": "SUCCEEDED", "status_label": "Succeeded", "status_category": "success", "report_included": True}],
        "run_metrics": [{"group": "cpu", "run_id": "run1"}],
        "run_costs": [{"group": "cpu", "run_id": "run1", "cost": 1.0, "used_cost": 1.0, "unused_cost": 0.0}],
        "process_stats": [],
        "combined_task_runtime": [],
        "task_instance_usage": [],
        "task_table": [],
        "task_scatter": [],
        "cost_overview": None,
    }


@pytest.fixture
def make_ic_run():
    def _make_ic_run(run_id: str = "icRUN0000000001", group: str = "ic"):
        return {
            "workflow": {
                "id": run_id, "status": "SUCCEEDED", "userName": "tester",
                "runName": "demo-ic-run", "projectName": "example/demo-pipeline",
                "revision": "1.0.0", "nextflow": {"version": "25.04.0"},
                "stats": {"succeedCount": 3, "failedCount": 0, "cachedCount": 0},
                "duration": 1717531,
            },
            "schedEnabled": True,
            "schedConfig": {"provisioningModel": "spotFirst", "predictionModel": "qr/v2"},
            "platform": {"id": "aws-cloud", "name": "AWS Cloud"},
            "progress": {"workflowProgress": {
                "cpuTime": 1247429, "memoryRss": 12339093504, "peakMemory": 32212254720,
                "cost": 0.0053921835, "cpuEfficiency": 41.6, "memoryEfficiency": 5.5,
            }},
            "tasks": [], "metrics": [],
            "meta": {"id": run_id, "workspace": "myorg/myworkspace", "group": group},
        }
    return _make_ic_run


@pytest.fixture
def make_batch_run():
    def _make_batch_run(run_id: str = "batchRUN00000001", group: str = "batch"):
        return {
            "workflow": {
                "id": run_id, "status": "SUCCEEDED", "userName": "tester",
                "runName": "demo-batch-run", "projectName": "example/demo-pipeline",
                "revision": "1.0.0", "nextflow": {"version": "25.04.0"},
                "stats": {"succeedCount": 3, "failedCount": 0, "cachedCount": 0},
                "duration": 3040821,
            },
            "platform": {"id": "aws-batch", "name": "AWS Batch"},
            "progress": {"workflowProgress": {
                "cpuTime": 480392, "memoryRss": 13447421952, "peakMemory": 32212254720,
                "cost": 0.006216994, "cpuEfficiency": 60.0, "memoryEfficiency": 6.0,
            }},
            "tasks": [], "metrics": [],
            "meta": {"id": run_id, "workspace": "myorg/myworkspace", "group": group},
        }
    return _make_batch_run
