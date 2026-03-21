"""Regression tests for benchmark_report.py.

Each test documents a real bug that occurred and prevents recurrence.
Run: uv run --with duckdb --with jinja2 --with typer --with pyyaml --with pyarrow --with pytest pytest bin/test_benchmark_report.py -v
"""
import json
import os
import tempfile

import duckdb
import pytest

from benchmark_report import build_database, query_run_costs


def _make_run(run_id="run1", group="cpu", tasks=None, status="SUCCEEDED"):
    """Minimal run dict matching SeqeraApi.fetchRunData() output."""
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
                "succeedCount": len(tasks or []),
                "failedCount": 0,
            },
            "duration": 3600000,
            "configFiles": [],
        },
        "metrics": [],
        "tasks": tasks or [],
        "progress": {
            "workflowProgress": {
                "cpuEfficiency": 50.0,
                "memoryEfficiency": 30.0,
            }
        },
        "meta": {"id": run_id, "workspace": "org/ws", "group": group},
    }


def _flat_task(name="PROCESS_A", hash_val="ab/cd1234", cost=1.50):
    """Task in flat format (pre-unwrapped)."""
    return {
        "name": name,
        "hash": hash_val,
        "process": name.split(":")[0],
        "status": "COMPLETED",
        "cpus": 4,
        "memory": 8_000_000_000,
        "realtime": 60000,
        "peakRss": 4_000_000_000,
        "%cpu": "200.0%",
        "cost": cost,
        "executor": "awsbatch",
        "machineType": "m5.xlarge",
        "cloudZone": "us-east-1a",
        "duration": 65000,
    }


def _nested_task(**kwargs):
    """Task in nested API format: {task: {...}}."""
    return {"task": _flat_task(**kwargs)}


# ── Bug: nested task objects from Seqera API ─────────────────────────────────

class TestNestedTaskUnwrap:
    """API returns tasks as [{task: {...}}, ...] not flat dicts.

    Before fix: all task fields (cost, hash, duration) were None,
    task_table had 0 useful rows.
    """

    def test_nested_tasks_produce_cost_data(self):
        run = _make_run(tasks=[_nested_task(cost=2.50), _nested_task(cost=3.00)])
        db = build_database([run])
        costs = db.execute("SELECT SUM(cost) FROM tasks").fetchone()[0]
        assert costs == pytest.approx(5.50)

    def test_nested_tasks_produce_hash_data(self):
        run = _make_run(tasks=[_nested_task(hash_val="59/4f3195")])
        db = build_database([run])
        h = db.execute("SELECT hash FROM tasks").fetchone()[0]
        assert h == "59/4f3195"

    def test_flat_tasks_still_work(self):
        run = _make_run(tasks=[_flat_task(cost=1.00)])
        db = build_database([run])
        costs = db.execute("SELECT SUM(cost) FROM tasks").fetchone()[0]
        assert costs == pytest.approx(1.00)

    def test_mixed_nested_and_flat(self):
        """Can't test mixed until nested is fixed — mark xfail."""
        run = _make_run(
            tasks=[_nested_task(cost=2.00), _flat_task(cost=3.00)]
        )
        db = build_database([run])
        count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        # Both should load, but nested ones will have None fields pre-fix.
        # Just verify count — no xfail needed since both rows will exist,
        # they just won't have correct data.
        assert count == 2


# ── Bug: CUR old format missing nf_ column ──────────────────────────────────

class TestCurOldFormatColumnDetection:
    """Old CUR parquet may have resource_tags_user_unique_run_id but NOT
    resource_tags_user_nf_unique_run_id. Query must not reference missing columns.
    """

    def _write_old_cur_parquet(self, tmp_path, run_id="run1", include_nf_col=False):
        """Write a minimal old-format CUR parquet."""
        db = duckdb.connect()
        nf_col = f", NULL::VARCHAR AS resource_tags_user_nf_unique_run_id" if include_nf_col else ""
        path = os.path.join(tmp_path, "cur.parquet")
        db.execute(f"""
            COPY (
                SELECT
                    '{run_id}' AS resource_tags_user_unique_run_id,
                    'PROC_A' AS resource_tags_user_pipeline_process,
                    'abcdef1234567890' AS resource_tags_user_task_hash,
                    10.0 AS line_item_unblended_cost,
                    8.0 AS split_line_item_split_cost,
                    2.0 AS split_line_item_unused_cost
                    {nf_col}
            ) TO '{path}' (FORMAT PARQUET)
        """)
        db.close()
        return path

    def test_old_format_without_nf_column(self, tmp_path):
        cur = self._write_old_cur_parquet(tmp_path, run_id="run1")
        run = _make_run(tasks=[_flat_task()])
        db = build_database([run], cur)
        # Should not crash, and costs table should exist
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" in tables

    def test_old_format_with_both_columns(self, tmp_path):
        cur = self._write_old_cur_parquet(tmp_path, run_id="run1", include_nf_col=True)
        run = _make_run(tasks=[_flat_task()])
        db = build_database([run], cur)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" in tables


# ── Feature+Bug: new CUR MAP format with erroneous [1] index ────────────────

class TestCurNewMapFormat:
    """New AWS CUR exports use a single MAP(VARCHAR,VARCHAR) resource_tags
    column instead of flattened resource_tags_user_* columns.

    The initial MAP implementation used resource_tags['key'][1] which is wrong —
    DuckDB MAP lookup returns a scalar, not a list. The [1] index causes NULL.
    """

    def _write_new_cur_parquet(self, tmp_path, run_id="run1"):
        """Write a minimal new-format CUR parquet with MAP column."""
        db = duckdb.connect()
        path = os.path.join(tmp_path, "cur_new.parquet")
        db.execute(f"""
            COPY (
                SELECT
                    MAP {{
                        'user_unique_run_id': '{run_id}',
                        'user_pipeline_process': 'PROC_A',
                        'user_task_hash': 'abcdef1234567890'
                    }} AS resource_tags,
                    10.0 AS line_item_unblended_cost,
                    8.0 AS split_line_item_split_cost,
                    2.0 AS split_line_item_unused_cost
            ) TO '{path}' (FORMAT PARQUET)
        """)
        db.close()
        return path

    def test_map_format_creates_costs_table(self, tmp_path):
        cur = self._write_new_cur_parquet(tmp_path, run_id="run1")
        run = _make_run(tasks=[_flat_task()])
        db = build_database([run], cur)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" in tables

    def test_map_format_extracts_run_id(self, tmp_path):
        cur = self._write_new_cur_parquet(tmp_path, run_id="run1")
        run = _make_run(tasks=[_flat_task()])
        db = build_database([run], cur)
        rid = db.execute("SELECT run_id FROM costs").fetchone()[0]
        assert rid == "run1"

    def test_map_format_extracts_costs(self, tmp_path):
        cur = self._write_new_cur_parquet(tmp_path, run_id="run1")
        run = _make_run(tasks=[_flat_task()])
        db = build_database([run], cur)
        row = db.execute("SELECT used_cost, unused_cost FROM costs").fetchone()
        assert row[0] == pytest.approx(8.0)
        assert row[1] == pytest.approx(2.0)


# ── Bug: CUR hash-join mismatch (task hash contains '/') ────────────────────

class TestCurHashJoinMismatch:
    """Task hash 'ab/cdef12' (with '/') never matched CUR hash 'abcdef12'
    in query_run_costs JOIN: LEFT(t.hash, 8) = c.hash.

    The '/' in Nextflow workdir hashes (e.g. 45/d87388) means LEFT(t.hash, 8)
    gives 'ab/cdef1' (7 hex chars + slash) while CUR stores 'abcdef12' (8 hex).
    Fix: normalize task hash by stripping '/' before comparing.
    """

    def _write_cur_parquet(self, tmp_path, run_id="run1", task_hash_md5="abcdef1234567890"):
        """Write CUR parquet with a known full MD5 task hash."""
        db = duckdb.connect()
        path = os.path.join(tmp_path, "cur.parquet")
        db.execute(f"""
            COPY (
                SELECT
                    '{run_id}' AS resource_tags_user_unique_run_id,
                    'PROC_A' AS resource_tags_user_pipeline_process,
                    '{task_hash_md5}' AS resource_tags_user_task_hash,
                    10.0 AS line_item_unblended_cost,
                    8.0 AS split_line_item_split_cost,
                    2.0 AS split_line_item_unused_cost
            ) TO '{path}' (FORMAT PARQUET)
        """)
        db.close()
        return path

    def test_cur_costs_override_task_costs(self, tmp_path):
        """When CUR data is present, query_run_costs should use CUR cost (10.0)
        not the task-level cost (1.50)."""
        task = _flat_task(hash_val="ab/cdef1234567890", cost=1.50)
        run = _make_run(run_id="run1", tasks=[task])
        cur = self._write_cur_parquet(tmp_path, run_id="run1", task_hash_md5="abcdef1234567890")

        db = build_database([run], cur)
        costs = query_run_costs(db)
        assert len(costs) == 1
        # Should use CUR cost, not task-level
        assert costs[0]["cost"] == pytest.approx(10.0)

    def test_cur_used_and_unused_cost_split(self, tmp_path):
        """CUR provides used_cost and unused_cost breakdown."""
        task = _flat_task(hash_val="ab/cdef1234567890", cost=1.50)
        run = _make_run(run_id="run1", tasks=[task])
        cur = self._write_cur_parquet(tmp_path, run_id="run1", task_hash_md5="abcdef1234567890")

        db = build_database([run], cur)
        costs = query_run_costs(db)
        assert costs[0]["used_cost"] == pytest.approx(8.0)
        assert costs[0]["unused_cost"] == pytest.approx(2.0)
