"""Tests for clean_json.py — JSON to CSV normalization.

Run: uv run --with duckdb --with jinja2 --with typer --with pyyaml --with pyarrow --with pytest pytest bin/test_clean_json.py -v
"""
import json
import os

import duckdb
import pytest

from clean_json import (
    build_and_export,
    extract_metrics,
    extract_runs,
    extract_tasks,
    load_run_data,
)


def _make_run(run_id="run1", group="cpu", tasks=None, status="SUCCEEDED",
              cached_count=0, failed_count=0, succeed_count=None):
    """Minimal run dict matching SeqeraApi.fetchRunData() output."""
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
                "computeTimeFmt": "1h",
                "succeedCount": succeed_count if succeed_count is not None else len(task_list),
                "failedCount": failed_count,
                "cachedCount": cached_count,
            },
            "duration": 3600000,
            "configFiles": [],
        },
        "metrics": [],
        "tasks": task_list,
        "progress": {
            "workflowProgress": {
                "cpuEfficiency": 50.0,
                "memoryEfficiency": 30.0,
            }
        },
        "meta": {"id": run_id, "workspace": "org/ws", "group": group},
    }


def _flat_task(name="PROCESS_A", hash_val="ab/cd1234", cost=1.50, status="COMPLETED"):
    """Task in flat format (pre-unwrapped)."""
    return {
        "name": name,
        "hash": hash_val,
        "process": name.split(":")[0],
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
    }


def _nested_task(**kwargs):
    """Task in nested API format: {task: {...}}."""
    return {"task": _flat_task(**kwargs)}


# ── Cached task extraction ───────────────────────────────────────────────────

class TestCachedTaskExtraction:
    """Verify cachedCount is properly extracted from workflow.stats."""

    def test_cached_count_extracted(self):
        run = _make_run(cached_count=10, succeed_count=50)
        rows = extract_runs([run])
        assert len(rows) == 1
        assert rows[0]["cached"] == 10

    def test_zero_cached_count(self):
        run = _make_run(cached_count=0)
        rows = extract_runs([run])
        assert rows[0]["cached"] == 0

    def test_missing_cached_count_defaults_to_zero(self):
        run = _make_run()
        del run["workflow"]["stats"]["cachedCount"]
        rows = extract_runs([run])
        assert rows[0]["cached"] == 0


# ── Nested task unwrap ───────────────────────────────────────────────────────

class TestNestedTaskUnwrap:
    """API returns tasks as [{task: {...}}, ...] not flat dicts."""

    def test_nested_tasks_produce_cost_data(self):
        run = _make_run(tasks=[_nested_task(cost=2.50), _nested_task(cost=3.00)])
        rows = extract_tasks([run])
        total = sum(r["cost"] for r in rows if r["cost"])
        assert total == pytest.approx(5.50)

    def test_nested_tasks_produce_hash_data(self):
        run = _make_run(tasks=[_nested_task(hash_val="59/4f3195")])
        rows = extract_tasks([run])
        assert rows[0]["hash"] == "59/4f3195"

    def test_flat_tasks_still_work(self):
        run = _make_run(tasks=[_flat_task(cost=1.00)])
        rows = extract_tasks([run])
        assert rows[0]["cost"] == pytest.approx(1.00)


# ── Task filtering (remove_failed) ──────────────────────────────────────────

class TestTaskFiltering:
    """Verify that remove_failed keeps COMPLETED and CACHED, drops FAILED."""

    def test_completed_tasks_kept(self, tmp_path):
        run = _make_run(tasks=[_flat_task(status="COMPLETED")])
        build_and_export([run], tmp_path, remove_failed=True)
        db = duckdb.connect()
        count = db.execute(
            f"SELECT COUNT(*) FROM read_csv_auto('{tmp_path}/tasks.csv')"
        ).fetchone()[0]
        assert count == 1

    def test_cached_tasks_kept(self, tmp_path):
        run = _make_run(tasks=[_flat_task(status="CACHED")])
        build_and_export([run], tmp_path, remove_failed=True)
        db = duckdb.connect()
        count = db.execute(
            f"SELECT COUNT(*) FROM read_csv_auto('{tmp_path}/tasks.csv')"
        ).fetchone()[0]
        assert count == 1

    def test_failed_tasks_removed(self, tmp_path):
        run = _make_run(tasks=[
            _flat_task(status="COMPLETED"),
            _flat_task(status="FAILED"),
            _flat_task(status="CACHED"),
        ])
        build_and_export([run], tmp_path, remove_failed=True)
        db = duckdb.connect()
        count = db.execute(
            f"SELECT COUNT(*) FROM read_csv_auto('{tmp_path}/tasks.csv')"
        ).fetchone()[0]
        assert count == 2  # COMPLETED + CACHED, not FAILED

    def test_no_filtering_when_disabled(self, tmp_path):
        run = _make_run(tasks=[
            _flat_task(status="COMPLETED"),
            _flat_task(status="FAILED"),
        ])
        build_and_export([run], tmp_path, remove_failed=False)
        db = duckdb.connect()
        count = db.execute(
            f"SELECT COUNT(*) FROM read_csv_auto('{tmp_path}/tasks.csv')"
        ).fetchone()[0]
        assert count == 2


# ── CSV export ───────────────────────────────────────────────────────────────

class TestCsvExport:
    """Verify CSVs are written correctly."""

    def test_runs_csv_has_expected_columns(self, tmp_path):
        run = _make_run()
        build_and_export([run], tmp_path)
        db = duckdb.connect()
        cols = {r[0] for r in db.execute(
            f"DESCRIBE SELECT * FROM read_csv_auto('{tmp_path}/runs.csv')"
        ).fetchall()}
        assert "cached" in cols
        assert "succeeded" in cols
        assert "failed" in cols
        assert "run_id" in cols

    def test_tasks_csv_has_process_short(self, tmp_path):
        task = _flat_task(name="NF:PIPELINE:PROC_A")
        task["process"] = "NF:PIPELINE:PROC_A"  # process field drives process_short
        run = _make_run(tasks=[task])
        build_and_export([run], tmp_path)
        db = duckdb.connect()
        val = db.execute(
            f"SELECT process_short FROM read_csv_auto('{tmp_path}/tasks.csv') LIMIT 1"
        ).fetchone()[0]
        assert val == "PROC_A"

    def test_metrics_csv_written_when_data_present(self, tmp_path):
        run = _make_run()
        run["metrics"] = [{
            "process": "PROC_A",
            "cpu": {"mean": 50.0, "min": 10.0, "q1": 30.0, "q2": 50.0, "q3": 70.0, "max": 90.0},
        }]
        build_and_export([run], tmp_path)
        assert (tmp_path / "metrics.csv").exists()


# ── Integration: real fixture data ───────────────────────────────────────────

@pytest.fixture
def sarek_fixtures():
    """Load the committed sarek test fixtures if available."""
    from pathlib import Path
    data_dir = Path(__file__).resolve().parent.parent / "modules" / "local" / "benchmark_report" / "tests" / "data"
    if not data_dir.is_dir():
        pytest.skip("Test fixture data not present")
    runs = load_run_data(data_dir)
    if not runs:
        pytest.skip("No JSON fixtures found")
    return runs


class TestSarekFixtures:
    """Validate against real SD-1043 Sarek benchmark data."""

    def test_extract_runs_count(self, sarek_fixtures):
        rows = extract_runs(sarek_fixtures)
        assert len(rows) == 2

    def test_cached_count_in_fixture(self, sarek_fixtures):
        """The g5 run has cachedCount=4 in its stats."""
        rows = extract_runs(sarek_fixtures)
        g5_run = [r for r in rows if r["group"] == "g5"][0]
        assert g5_run["cached"] == 4

    def test_export_roundtrip(self, sarek_fixtures, tmp_path):
        build_and_export(sarek_fixtures, tmp_path)
        db = duckdb.connect()
        count = db.execute(
            f"SELECT COUNT(*) FROM read_csv_auto('{tmp_path}/runs.csv')"
        ).fetchone()[0]
        assert count == 2
