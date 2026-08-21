from __future__ import annotations

import json
import os
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
def denied_path(tmp_path):
    """A path that exists but cannot be stat'ed — EACCES, not ENOENT.

    Stands in for a Nextflow-staged input on a Fusion mount, where a lookup is denied
    rather than missing. `Path.exists()` re-raises that on Python 3.12 and swallows it on
    3.13+, so every stage that probes a staged path needs a guard; this fixture is how each
    of those guards is exercised.
    """
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    locked = tmp_path / "locked"
    (locked / "data").mkdir(parents=True)
    locked.chmod(0o000)
    yield locked / "data"
    locked.chmod(0o755)


@pytest.fixture
def make_run():
    def _make_run(
        run_id: str = "run1",
        group: str = "cpu",
        tasks: list | None = None,
        cached_count: int = 0,
        status: str = "SUCCEEDED",
        session_id: str = "",
        resume: bool = False,
        complete: str | None = None,
    ):
        task_list = tasks or []
        return {
            "workflow": {
                "id": run_id,
                "sessionId": session_id,
                "resume": resume,
                "complete": complete,
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
    def _make_ic_run(
        run_id: str = "icRUN0000000001",
        group: str = "ic",
        session_id: str = "",
        cached_count: int = 0,
    ):
        return {
            "workflow": {
                "id": run_id, "status": "SUCCEEDED", "userName": "tester",
                "runName": "demo-ic-run", "projectName": "example/demo-pipeline",
                "revision": "1.0.0", "nextflow": {"version": "25.04.0"},
                "sessionId": session_id,
                "stats": {"succeedCount": 3, "failedCount": 0, "cachedCount": cached_count},
                "duration": 1717531,
            },
            "schedEnabled": True,
            "schedConfig": {"provisioningModel": "spotFirst", "predictionModel": "qr/v2"},
            "platform": {"id": "aws-cloud", "name": "AWS Cloud"},
            "progress": {"workflowProgress": {
                "cpuTime": 1247429, "memoryRss": 12339093504, "peakMemory": 32212254720,
                "cost": 0.0053921835, "cpuEfficiency": 41.6, "memoryEfficiency": 5.5,
            }},
            "tasks": [
                {"name": "t1", "process": "P:t1", "status": "COMPLETED", "hash": "aa/01", "cpus": 2, "start": "2026-01-01T00:00:00Z", "complete": "2026-01-01T00:30:00Z", "machineType": "t3.large"},
                {"name": "t2", "process": "P:t2", "status": "COMPLETED", "hash": "aa/02", "cpus": 2, "start": "2026-01-01T00:00:00Z", "complete": "2026-01-01T00:30:00Z", "machineType": "t3.large"},
                {"name": "t3", "process": "P:t3", "status": "COMPLETED", "hash": "aa/03", "cpus": 2, "start": "2026-01-01T00:00:00Z", "complete": "2026-01-01T00:30:00Z", "machineType": "t3a.xlarge"},
                {"name": "t4", "process": "P:t4", "status": "COMPLETED", "hash": "aa/04", "cpus": 2, "start": "2026-01-01T00:00:00Z", "complete": "2026-01-01T00:30:00Z", "machineType": ""},
            ],
            "metrics": [],
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
            "tasks": [
                {"name": "b1", "process": "P:b1", "status": "COMPLETED", "hash": "bb/01", "cpus": 2, "start": "2026-01-01T00:00:00Z", "complete": "2026-01-01T00:30:00Z", "machineType": "m6id.4xlarge"},
                {"name": "b2", "process": "P:b2", "status": "COMPLETED", "hash": "bb/02", "cpus": 2, "start": "2026-01-01T00:00:00Z", "complete": "2026-01-01T00:30:00Z", "machineType": "m6id.4xlarge"},
                {"name": "b3", "process": "P:b3", "status": "COMPLETED", "hash": "bb/03", "cpus": 2, "start": "2026-01-01T00:00:00Z", "complete": "2026-01-01T00:30:00Z", "machineType": "t3.large"},
                {"name": "b4", "process": "P:b4", "status": "COMPLETED", "hash": "bb/04", "cpus": 2, "start": "2026-01-01T00:00:00Z", "complete": "2026-01-01T00:30:00Z", "machineType": ""},
            ],
            "metrics": [],
            "meta": {"id": run_id, "workspace": "myorg/myworkspace", "group": group},
        }
    return _make_batch_run
