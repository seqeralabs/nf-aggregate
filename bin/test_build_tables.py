"""Tests for build_tables.py — DuckDB query result generation.

Run: uv run --with duckdb --with jinja2 --with typer --with pyyaml --with pyarrow --with pytest pytest bin/test_build_tables.py -v
"""
import json
import os

import duckdb
import pytest

from build_tables import (
    fetch_dicts,
    load_tables,
    query_benchmark_overview,
    query_cost_overview,
    query_process_stats,
    query_run_costs,
    query_run_metrics,
    query_run_summary,
    query_task_instance_usage,
    query_task_scatter,
    query_task_table,
    table_exists,
)

from clean_json import build_and_export


def _make_run(run_id="run1", group="cpu", tasks=None, status="SUCCEEDED",
              cached_count=0, failed_count=0, succeed_count=None):
    """Minimal run dict."""
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
                "succeedCount": succeed_count if succeed_count is not None else len(task_list),
                "failedCount": failed_count,
                "cachedCount": cached_count,
            },
            "duration": 3600000,
        },
        "metrics": [],
        "tasks": task_list,
        "progress": {"workflowProgress": {"cpuEfficiency": 50.0, "memoryEfficiency": 30.0}},
        "meta": {"id": run_id, "workspace": "org/ws", "group": group},
    }


def _flat_task(name="PROCESS_A", hash_val="ab/cd1234", cost=1.50, status="COMPLETED"):
    return {
        "name": name, "hash": hash_val, "process": name.split(":")[0],
        "status": status, "cpus": 4, "memory": 8_000_000_000,
        "realtime": 60000, "peakRss": 4_000_000_000, "cost": cost,
        "executor": "awsbatch", "machineType": "m5.xlarge",
        "cloudZone": "us-east-1a", "duration": 65000,
    }


def _setup_csvs(runs, tmp_path, remove_failed=True):
    """Write CSVs and load into DuckDB for testing queries."""
    csv_dir = tmp_path / "cleaned"
    build_and_export(runs, csv_dir, remove_failed=remove_failed)
    db = duckdb.connect()
    load_tables(
        db,
        csv_dir / "runs.csv",
        csv_dir / "tasks.csv",
        csv_dir / "metrics.csv" if (csv_dir / "metrics.csv").exists() else None,
        None,
    )
    return db


# ── Run summary with cached count ───────────────────────────────────────────

class TestRunSummaryWithCached:
    """Verify cached count appears in run_summary query results."""

    def test_cached_count_in_summary(self, tmp_path):
        run = _make_run(
            tasks=[_flat_task()],
            cached_count=5,
            succeed_count=10,
        )
        db = _setup_csvs([run], tmp_path)
        summary = query_run_summary(db)
        assert len(summary) == 1
        assert summary[0]["cachedCount"] == 5

    def test_zero_cached_in_summary(self, tmp_path):
        run = _make_run(tasks=[_flat_task()])
        db = _setup_csvs([run], tmp_path)
        summary = query_run_summary(db)
        assert summary[0]["cachedCount"] == 0


# ── Task table includes CACHED tasks ────────────────────────────────────────

class TestTaskTableWithCached:
    """Task table and scatter should include CACHED status tasks."""

    def test_cached_tasks_in_task_table(self, tmp_path):
        run = _make_run(tasks=[
            _flat_task(name="P1", status="COMPLETED"),
            _flat_task(name="P2", status="CACHED"),
        ])
        db = _setup_csvs([run], tmp_path)
        table = query_task_table(db)
        statuses = {r["Status"] for r in table}
        assert "CACHED" in statuses
        assert "COMPLETED" in statuses

    def test_cached_tasks_in_scatter(self, tmp_path):
        run = _make_run(tasks=[
            _flat_task(name="P1", status="COMPLETED"),
            _flat_task(name="P2", status="CACHED"),
        ])
        db = _setup_csvs([run], tmp_path)
        scatter = query_task_scatter(db)
        assert len(scatter) == 2


# ── CUR hash-join mismatch ──────────────────────────────────────────────────

class TestCurHashJoinViaCSV:
    """Verify CUR cost join works through the CSV pipeline."""

    def _write_cur_csv(self, tmp_path, run_id="run1", task_hash="abcdef12"):
        path = tmp_path / "costs.csv"
        path.write_text(
            "run_id,process,hash,cost,used_cost,unused_cost\n"
            f"{run_id},PROCESS_A,{task_hash},10.0,8.0,2.0\n"
        )
        return path

    def test_cur_costs_override_task_costs(self, tmp_path):
        task = _flat_task(hash_val="ab/cdef1234567890", cost=1.50)
        run = _make_run(run_id="run1", tasks=[task])
        csv_dir = tmp_path / "cleaned"
        build_and_export([run], csv_dir)

        costs_csv = self._write_cur_csv(
            tmp_path, run_id="run1", task_hash="abcdef12"
        )
        db = duckdb.connect()
        load_tables(db, csv_dir / "runs.csv", csv_dir / "tasks.csv", None, costs_csv)

        costs = query_run_costs(db)
        assert len(costs) == 1
        assert costs[0]["cost"] == pytest.approx(10.0)
