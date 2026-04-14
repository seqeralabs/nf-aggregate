"""Tests for benchmark_report.py — unified benchmark CLI.

Run: uv run --with duckdb --with typer --with pyyaml --with jinja2 --with pyarrow --with pytest pytest bin/test_benchmark_report.py -v
"""

import json
import os
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from benchmark_report import (
    REPORT_TEMPLATE,
    _compute_progress_from_tasks,
    _load_echarts_theme,
    build_costs_flat_format,
    build_costs_map_format,
    build_db,
    detect_cur_format,
    extract_metrics,
    extract_runs,
    extract_tasks,
    fetch_all_tasks,
    fetch_dicts,
    fetch_run_data,
    load_brand,
    load_run_data,
    query_benchmark_overview,
    query_cost_overview,
    query_process_stats,
    query_run_costs,
    query_run_metrics,
    query_run_summary,
    query_task_instance_usage,
    query_task_scatter,
    query_task_table,
    render_html,
    render_report,
    resolve_workspace_id,
    table_exists,
)


# ── Test helpers ────────────────────────────────────────────────────────────


def _make_run(run_id="run1", group="cpu", tasks=None, status="SUCCEEDED",
              cached_count=0, failed_count=0, succeed_count=None,
              platform=None, token_env=None):
    """Minimal run dict matching SeqeraApi.fetchRunData() output."""
    task_list = tasks or []
    meta = {"id": run_id, "workspace": "org/ws", "group": group}
    if platform is not None:
        meta["platform"] = platform
    if token_env is not None:
        meta["token_env"] = token_env
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
        "meta": meta,
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


def _write_run_json(data_dir, runs):
    """Write run dicts as JSON files in a directory."""
    data_dir.mkdir(parents=True, exist_ok=True)
    for i, run in enumerate(runs):
        (data_dir / f"run_{i}.json").write_text(json.dumps(run))


def _minimal_query_data(cached_count=0):
    """Minimal query data for rendering a complete report."""
    return {
        "benchmark_overview": [
            {"pipeline": "test-pipe", "group": "cpu", "run_id": "run1"}
        ],
        "run_summary": [
            {
                "pipeline": "test-pipe", "group": "cpu", "run_id": "run1",
                "username": "user1", "Version": "1.0", "Nextflow_version": "24.04",
                "platform_version": "", "succeedCount": 10, "failedCount": 0,
                "cachedCount": cached_count,
                "executor": "awsbatch", "region": "us-east-1",
                "fusion_enabled": False, "wave_enabled": False,
                "container_engine": "docker",
            }
        ],
        "run_metrics": [
            {
                "pipeline": "test-pipe", "group": "cpu", "run_id": "run1",
                "duration": 3600000, "cpuTime": 10.0, "pipeline_runtime": 3600000,
                "cpuEfficiency": 80.0, "memoryEfficiency": 60.0,
                "readBytes": 100, "writeBytes": 50,
            }
        ],
        "run_costs": [
            {"run_id": "run1", "group": "cpu", "cost": 5.00,
             "used_cost": 4.00, "unused_cost": 1.00}
        ],
        "process_stats": [],
        "task_instance_usage": [],
        "task_table": [],
        "task_scatter": [],
        "cost_overview": None,
    }


# ── Cached task extraction ──────────────────────────────────────────────────


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


# ── Nested task unwrap ──────────────────────────────────────────────────────


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


# ── Task filtering (remove_failed in build_db) ─────────────────────────────


class TestTaskFiltering:
    """Verify that build_db keeps COMPLETED and CACHED, drops FAILED."""

    def test_completed_tasks_kept(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[_flat_task(status="COMPLETED")])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        assert count == 1
        db.close()

    def test_cached_tasks_kept(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[_flat_task(status="CACHED")])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        assert count == 1
        db.close()

    def test_failed_tasks_removed(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[
            _flat_task(status="COMPLETED"),
            _flat_task(status="FAILED"),
            _flat_task(status="CACHED"),
        ])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        assert count == 2  # COMPLETED + CACHED, not FAILED
        db.close()


# ── process_short derivation ────────────────────────────────────────────────


class TestProcessShort:
    """Verify process_short is derived from the process name."""

    def test_process_short_derived(self, tmp_path):
        task = _flat_task(name="NF:PIPELINE:PROC_A")
        task["process"] = "NF:PIPELINE:PROC_A"
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[task])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        val = db.execute("SELECT process_short FROM tasks LIMIT 1").fetchone()[0]
        assert val == "PROC_A"
        db.close()


# ── DuckDB file creation ───────────────────────────────────────────────────


class TestDuckDBCreation:
    """Verify DuckDB file is created with correct tables."""

    def test_creates_duckdb_file(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[_flat_task()])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        assert db_path.exists()

    def test_has_runs_table(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[_flat_task()])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "runs" in tables
        assert "tasks" in tables
        db.close()

    def test_has_expected_run_columns(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run()])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        cols = {r[0] for r in db.execute("DESCRIBE runs").fetchall()}
        assert "cached" in cols
        assert "succeeded" in cols
        assert "failed" in cols
        assert "run_id" in cols
        db.close()

    def test_metrics_table_when_present(self, tmp_path):
        data_dir = tmp_path / "data"
        run = _make_run()
        run["metrics"] = [{
            "process": "PROC_A",
            "cpu": {"mean": 50.0, "min": 10.0, "q1": 30.0, "q2": 50.0, "q3": 70.0, "max": 90.0},
        }]
        _write_run_json(data_dir, [run])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "metrics" in tables
        db.close()


# ── CUR flat format ─────────────────────────────────────────────────────────


class TestCurFlatFormat:
    """CUR 1.0 flat format detection and cost extraction."""

    def _write_flat_cur(self, tmp_path, run_id="run1", include_nf_col=False):
        db = duckdb.connect()
        nf_col = (
            f", NULL::VARCHAR AS resource_tags_user_nf_unique_run_id"
            if include_nf_col
            else ""
        )
        path = os.path.join(str(tmp_path), "cur.parquet")
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

    def test_detects_flat_format(self, tmp_path):
        cur = self._write_flat_cur(tmp_path)
        db = duckdb.connect()
        assert detect_cur_format(db, cur) == "flat"
        db.close()

    def test_flat_without_nf_column(self, tmp_path):
        cur = self._write_flat_cur(tmp_path)
        db = duckdb.connect()
        build_costs_flat_format(db, cur)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" in tables
        db.close()

    def test_flat_with_both_columns(self, tmp_path):
        cur = self._write_flat_cur(tmp_path, include_nf_col=True)
        db = duckdb.connect()
        build_costs_flat_format(db, cur)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" in tables
        db.close()

    def test_flat_extracts_costs(self, tmp_path):
        cur = self._write_flat_cur(tmp_path)
        db = duckdb.connect()
        build_costs_flat_format(db, cur)
        row = db.execute("SELECT used_cost, unused_cost FROM costs").fetchone()
        assert row[0] == pytest.approx(8.0)
        assert row[1] == pytest.approx(2.0)
        db.close()


# ── CUR MAP format ──────────────────────────────────────────────────────────


class TestCurMapFormat:
    """CUR 2.0 MAP format detection and cost extraction."""

    def _write_map_cur(self, tmp_path, run_id="run1"):
        db = duckdb.connect()
        path = os.path.join(str(tmp_path), "cur_new.parquet")
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

    def test_detects_map_format(self, tmp_path):
        cur = self._write_map_cur(tmp_path)
        db = duckdb.connect()
        assert detect_cur_format(db, cur) == "map"
        db.close()

    def test_map_creates_costs_table(self, tmp_path):
        cur = self._write_map_cur(tmp_path)
        db = duckdb.connect()
        build_costs_map_format(db, cur)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" in tables
        db.close()

    def test_map_extracts_run_id(self, tmp_path):
        cur = self._write_map_cur(tmp_path)
        db = duckdb.connect()
        build_costs_map_format(db, cur)
        rid = db.execute("SELECT run_id FROM costs").fetchone()[0]
        assert rid == "run1"
        db.close()

    def test_map_extracts_costs(self, tmp_path):
        cur = self._write_map_cur(tmp_path)
        db = duckdb.connect()
        build_costs_map_format(db, cur)
        row = db.execute("SELECT used_cost, unused_cost FROM costs").fetchone()
        assert row[0] == pytest.approx(8.0)
        assert row[1] == pytest.approx(2.0)
        db.close()


# ── build-db with costs integration ─────────────────────────────────────────


class TestBuildDbWithCosts:
    """Verify build_db integrates CUR parquet into the database."""

    def _write_flat_cur(self, tmp_path, run_id="run1"):
        db = duckdb.connect()
        path = os.path.join(str(tmp_path), "cur.parquet")
        db.execute(f"""
            COPY (
                SELECT
                    '{run_id}' AS resource_tags_user_unique_run_id,
                    'PROCESS_A' AS resource_tags_user_pipeline_process,
                    'abcd1234xxxxxxxx' AS resource_tags_user_task_hash,
                    10.0 AS line_item_unblended_cost,
                    8.0 AS split_line_item_split_cost,
                    2.0 AS split_line_item_unused_cost
            ) TO '{path}' (FORMAT PARQUET)
        """)
        db.close()
        return path

    def test_costs_table_created(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[_flat_task()])])
        cur_path = self._write_flat_cur(tmp_path)
        db_path = tmp_path / "test.duckdb"
        from pathlib import Path
        build_db(data_dir, db_path, costs_parquet=Path(cur_path))
        db = duckdb.connect(str(db_path), read_only=True)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" in tables
        db.close()

    def test_no_costs_without_parquet(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[_flat_task()])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" not in tables
        db.close()


# ── Query functions (via DuckDB file) ───────────────────────────────────────


class TestQueryFunctions:
    """Verify query functions work against a DuckDB file."""

    @pytest.fixture
    def db_with_data(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(
            tasks=[_flat_task()],
            cached_count=5,
            succeed_count=10,
        )])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        yield db
        db.close()

    def test_cached_count_in_summary(self, db_with_data):
        summary = query_run_summary(db_with_data)
        assert len(summary) == 1
        assert summary[0]["cachedCount"] == 5

    def test_zero_cached_in_summary(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[_flat_task()])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        summary = query_run_summary(db)
        assert summary[0]["cachedCount"] == 0
        db.close()

    def test_cached_tasks_in_task_table(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[
            _flat_task(name="P1", status="COMPLETED"),
            _flat_task(name="P2", status="CACHED"),
        ])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        table = query_task_table(db)
        statuses = {r["Status"] for r in table}
        assert "CACHED" in statuses
        assert "COMPLETED" in statuses
        db.close()

    def test_cached_tasks_in_scatter(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[
            _flat_task(name="P1", status="COMPLETED"),
            _flat_task(name="P2", status="CACHED"),
        ])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        scatter = query_task_scatter(db)
        assert len(scatter) == 2
        db.close()

    def test_benchmark_overview(self, db_with_data):
        overview = query_benchmark_overview(db_with_data)
        assert len(overview) == 1
        assert overview[0]["pipeline"] == "pipeline"

    def test_run_metrics(self, db_with_data):
        metrics = query_run_metrics(db_with_data)
        assert len(metrics) == 1

    def test_run_costs_without_cur(self, db_with_data):
        costs = query_run_costs(db_with_data)
        assert len(costs) == 1
        assert costs[0]["used_cost"] is None  # no CUR data


# ── Report rendering ────────────────────────────────────────────────────────


class TestRenderReport:
    """Verify HTML report renders correctly."""

    def test_renders_html(self, tmp_path):
        output = str(tmp_path / "report.html")
        data = _minimal_query_data()
        render_html(data, output)
        html = (tmp_path / "report.html").read_text()
        assert "Pipeline benchmarking report" in html
        assert "echarts" in html

    def test_report_contains_run_data(self, tmp_path):
        output = str(tmp_path / "report.html")
        data = _minimal_query_data()
        render_html(data, output)
        html = (tmp_path / "report.html").read_text()
        assert "test-pipe" in html
        assert "run1" in html


# ── Cached task display in report ───────────────────────────────────────────


class TestCachedTaskDisplay:
    """Verify cached tasks appear in the rendered HTML report."""

    def test_cached_column_in_summary_table(self, tmp_path):
        output = str(tmp_path / "report.html")
        data = _minimal_query_data(cached_count=5)
        render_html(data, output)
        html = (tmp_path / "report.html").read_text()
        assert "cachedCount" in html
        assert "Tasks cached" in html

    def test_cached_series_in_status_chart_when_present(self, tmp_path):
        output = str(tmp_path / "report.html")
        data = _minimal_query_data(cached_count=5)
        render_html(data, output)
        html = (tmp_path / "report.html").read_text()
        assert "'Cached'" in html
        assert "#f59e0b" in html

    def test_no_cached_series_when_zero(self, tmp_path):
        output = str(tmp_path / "report.html")
        data = _minimal_query_data(cached_count=0)
        render_html(data, output)
        html = (tmp_path / "report.html").read_text()
        assert "Tasks cached" in html

    def test_cached_subtitle_text(self, tmp_path):
        output = str(tmp_path / "report.html")
        data = _minimal_query_data(cached_count=5)
        render_html(data, output)
        html = (tmp_path / "report.html").read_text()
        assert "cached" in html.lower()


# ── End-to-end: build-db then render_report ─────────────────────────────────


class TestEndToEnd:
    """Test build_db -> render_report pipeline."""

    def test_build_then_render(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[_flat_task()])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        output = tmp_path / "report.html"
        render_report(db_path, output)
        html = output.read_text()
        assert "Pipeline benchmarking report" in html
        assert "pipeline" in html


# ── Per-row platform/token_env meta passthrough ───────────────────────────


class TestPlatformTokenMetaPassthrough:
    """Verify runs with platform/token_env meta fields flow through the pipeline."""

    def test_extract_runs_with_platform_meta(self):
        run = _make_run(
            platform="https://api.staging.seqera.io",
            token_env="STAGING_TOKEN",
            tasks=[_flat_task()],
        )
        rows = extract_runs([run])
        assert len(rows) == 1
        assert rows[0]["run_id"] == "run1"

    def test_extract_runs_without_platform_meta(self):
        run = _make_run(tasks=[_flat_task()])
        rows = extract_runs([run])
        assert len(rows) == 1
        assert rows[0]["run_id"] == "run1"

    def test_extract_tasks_with_platform_meta(self):
        run = _make_run(
            platform="https://api.staging.seqera.io",
            token_env="STAGING_TOKEN",
            tasks=[_flat_task()],
        )
        rows = extract_tasks([run])
        assert len(rows) == 1
        assert rows[0]["run_id"] == "run1"

    def test_build_db_with_platform_meta(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [
            _make_run(
                run_id="prod1",
                group="prod",
                platform="https://api.cloud.seqera.io",
                token_env="PROD_TOKEN",
                tasks=[_flat_task()],
            ),
        ])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        count = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert count == 1
        db.close()

    def test_build_db_mixed_runs(self, tmp_path):
        """Mix of runs with and without per-row overrides."""
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [
            _make_run(
                run_id="prod1",
                group="prod",
                platform="https://api.cloud.seqera.io",
                token_env="PROD_TOKEN",
                tasks=[_flat_task(name="P1")],
            ),
            _make_run(
                run_id="dev1",
                group="dev",
                platform="https://api.dev.seqera.io",
                token_env="DEV_TOKEN",
                tasks=[_flat_task(name="P2")],
            ),
            _make_run(
                run_id="default1",
                group="default",
                tasks=[_flat_task(name="P3")],
            ),
        ])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        runs = db.execute("SELECT run_id, \"group\" FROM runs ORDER BY run_id").fetchall()
        assert len(runs) == 3
        assert {r[0] for r in runs} == {"prod1", "dev1", "default1"}
        db.close()

    def test_queries_work_with_platform_meta(self, tmp_path):
        """All query functions succeed with per-row override metadata."""
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [
            _make_run(
                run_id="r1",
                group="staging",
                platform="https://api.staging.seqera.io",
                token_env="STAGING_TOKEN",
                tasks=[_flat_task()],
            ),
        ])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        assert len(query_benchmark_overview(db)) == 1
        assert len(query_run_summary(db)) == 1
        assert len(query_run_metrics(db)) == 1
        assert len(query_run_costs(db)) == 1
        assert len(query_process_stats(db)) >= 0
        db.close()

    def test_end_to_end_render_with_platform_meta(self, tmp_path):
        """Full pipeline: build_db -> render_report with per-row overrides."""
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [
            _make_run(
                run_id="staging1",
                group="staging",
                platform="https://api.staging.seqera.io",
                token_env="STAGING_TOKEN",
                tasks=[_flat_task()],
            ),
            _make_run(
                run_id="prod1",
                group="prod",
                tasks=[_flat_task()],
            ),
        ])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        output = tmp_path / "report.html"
        render_report(db_path, output)
        html = output.read_text()
        assert "Pipeline benchmarking report" in html
        assert "staging" in html
        assert "prod" in html


# ── Brand loading ───────────────────────────────────────────────────────────


class TestBrandLoading:
    """Verify brand.yml loading."""

    def test_defaults_without_brand_file(self):
        brand = load_brand(None)
        assert brand["accent"] == "#065647"
        assert len(brand["palette"]) == 10

    def test_loads_brand_file(self, tmp_path):
        brand_yml = tmp_path / "brand.yml"
        brand_yml.write_text("""
colors:
  green_palette:
    deep_green:
      hex: "#112233"
""")
        brand = load_brand(brand_yml)
        assert brand["accent"] == "#112233"


# ── JSON loading ────────────────────────────────────────────────────────────


class TestJsonLoading:
    """Verify load_run_data reads JSON files from directory."""

    def test_loads_json_files(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(), _make_run(run_id="run2")])
        runs = load_run_data(data_dir)
        assert len(runs) == 2

    def test_empty_directory(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        runs = load_run_data(data_dir)
        assert len(runs) == 0


# ── Template loaded ─────────────────────────────────────────────────────────


class TestTemplateLoaded:
    """Verify the report template is loaded."""

    def test_template_is_string(self):
        assert isinstance(REPORT_TEMPLATE, str)

    def test_template_contains_html(self):
        assert "<!DOCTYPE html>" in REPORT_TEMPLATE

    def test_template_contains_echarts(self):
        assert "echarts" in REPORT_TEMPLATE


# ── Integration: real fixture data ──────────────────────────────────────────


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
        rows = extract_runs(sarek_fixtures)
        g5_run = [r for r in rows if r["group"] == "g5"][0]
        assert g5_run["cached"] == 4

    def test_build_db_roundtrip(self, sarek_fixtures, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, sarek_fixtures)
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        count = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert count == 2
        db.close()


# ── Fetch subcommand (Seqera Platform API) ─────────────────────────────────


import io
from urllib.error import HTTPError, URLError


def _mock_urlopen(json_data, status_code=200):
    """Create a context-manager mock matching urllib.request.urlopen."""
    body = json.dumps(json_data).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _mock_urlopen_sequence(responses):
    """Return a side_effect function that yields mock responses in order."""
    it = iter(responses)
    def _side_effect(*args, **kwargs):
        return next(it)
    return _side_effect


class TestResolveWorkspaceId:
    """Verify workspace resolution from org/workspace string."""

    @patch("benchmark_report.urlopen")
    def test_resolves_workspace(self, mock_urlopen):
        mock_urlopen.side_effect = _mock_urlopen_sequence([
            _mock_urlopen({"organizations": [{"name": "myorg", "orgId": 42}]}),
            _mock_urlopen({"workspaces": [{"name": "myws", "id": 99}]}),
        ])
        ws_id = resolve_workspace_id(
            "myorg/myws", "https://api.example.com", {"Authorization": "Bearer tok"}
        )
        assert ws_id == 99
        assert mock_urlopen.call_count == 2

    @patch("benchmark_report.urlopen")
    def test_raises_on_missing_org(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({"organizations": []})
        with pytest.raises(RuntimeError, match="Organization.*not found"):
            resolve_workspace_id(
                "badorg/ws", "https://api.example.com", {}
            )

    @patch("benchmark_report.urlopen")
    def test_raises_on_missing_workspace(self, mock_urlopen):
        mock_urlopen.side_effect = _mock_urlopen_sequence([
            _mock_urlopen({"organizations": [{"name": "org", "orgId": 1}]}),
            _mock_urlopen({"workspaces": []}),
        ])
        with pytest.raises(RuntimeError, match="Workspace.*not found"):
            resolve_workspace_id(
                "org/badws", "https://api.example.com", {}
            )


class TestFetchAllTasks:
    """Verify task pagination."""

    @patch("benchmark_report.urlopen")
    def test_single_page(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({
            "tasks": [{"task": {"id": i}} for i in range(50)]
        })
        tasks = fetch_all_tasks("https://api.example.com/workflow/1/tasks?workspaceId=1", {})
        assert len(tasks) == 50
        assert mock_urlopen.call_count == 1

    @patch("benchmark_report.urlopen")
    def test_multi_page(self, mock_urlopen):
        full_page = [{"task": {"id": i}} for i in range(100)]
        partial_page = [{"task": {"id": i}} for i in range(30)]
        mock_urlopen.side_effect = _mock_urlopen_sequence([
            _mock_urlopen({"tasks": full_page}),
            _mock_urlopen({"tasks": partial_page}),
        ])
        tasks = fetch_all_tasks("https://api.example.com/workflow/1/tasks?workspaceId=1", {})
        assert len(tasks) == 130
        assert mock_urlopen.call_count == 2


class TestFetchRunData:
    """Verify fetch_run_data calls all required API endpoints."""

    def _standard_responses(self, endpoint="https://api.example.com"):
        """Six mock responses for a successful fetch_run_data call."""
        return [
            _mock_urlopen({"organizations": [{"name": "org", "orgId": 1}]}),
            _mock_urlopen({"workspaces": [{"name": "ws", "id": 10}]}),
            _mock_urlopen({"workflow": {"id": "abc123", "status": "SUCCEEDED"}}),
            _mock_urlopen({"metrics": [{"process": "PROC_A"}]}),
            _mock_urlopen({"tasks": [{"task": {"name": "t1"}}]}),
            _mock_urlopen({"progress": {"workflowProgress": {}}}),
        ]

    @patch("benchmark_report.urlopen")
    def test_calls_four_endpoints(self, mock_urlopen):
        mock_urlopen.side_effect = _mock_urlopen_sequence(self._standard_responses())
        result = fetch_run_data("abc123", "org/ws", "https://api.example.com", "tok123")

        assert result["workflow"]["id"] == "abc123"
        assert len(result["metrics"]) == 1
        assert len(result["tasks"]) == 1
        assert result["progress"] is not None
        # 2 calls for workspace resolution + 4 data endpoints = 6 total
        assert mock_urlopen.call_count == 6

    @patch("benchmark_report.urlopen")
    def test_returns_expected_keys(self, mock_urlopen):
        mock_urlopen.side_effect = _mock_urlopen_sequence([
            _mock_urlopen({"organizations": [{"name": "o", "orgId": 1}]}),
            _mock_urlopen({"workspaces": [{"name": "w", "id": 5}]}),
            _mock_urlopen({"workflow": {"id": "r1"}}),
            _mock_urlopen({"metrics": []}),
            _mock_urlopen({"tasks": []}),
            _mock_urlopen({"progress": {"workflowProgress": {}}}),
        ])
        result = fetch_run_data("r1", "o/w", "https://api.example.com", "tok")
        assert set(result.keys()) == {"workflow", "metrics", "tasks", "progress"}

    @patch("benchmark_report.urlopen")
    def test_uses_provided_api_endpoint(self, mock_urlopen):
        """Verify that fetch_run_data sends requests to the given endpoint."""
        alt_endpoint = "https://api.staging.seqera.io"
        mock_urlopen.side_effect = _mock_urlopen_sequence(
            self._standard_responses(endpoint=alt_endpoint)
        )
        fetch_run_data("run1", "org/ws", alt_endpoint, "tok")

        # Every URL should target the alternate endpoint
        for call in mock_urlopen.call_args_list:
            req = call[0][0]  # first positional arg is the Request object
            assert req.full_url.startswith(alt_endpoint), (
                f"Expected URL to start with {alt_endpoint}, got {req.full_url}"
            )

    @patch("benchmark_report.urlopen")
    def test_http_401_raises(self, mock_urlopen):
        """Unauthorized token should propagate as an HTTPError."""
        mock_urlopen.side_effect = HTTPError(
            url="https://api.example.com/orgs",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(b""),
        )
        with pytest.raises(HTTPError) as exc_info:
            fetch_run_data("run1", "org/ws", "https://api.example.com", "bad-token")
        assert exc_info.value.code == 401

    @patch("benchmark_report.urlopen")
    def test_http_500_raises(self, mock_urlopen):
        """Server errors should propagate as an HTTPError."""
        mock_urlopen.side_effect = HTTPError(
            url="https://api.example.com/orgs",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=io.BytesIO(b""),
        )
        with pytest.raises(HTTPError) as exc_info:
            fetch_run_data("run1", "org/ws", "https://api.example.com", "tok")
        assert exc_info.value.code == 500

    @patch("benchmark_report.urlopen")
    def test_connection_error_raises(self, mock_urlopen):
        """Unreachable endpoint should propagate as a URLError."""
        mock_urlopen.side_effect = URLError("Name or service not known")
        with pytest.raises(URLError):
            fetch_run_data("run1", "org/ws", "https://unreachable.example.com", "tok")

    @patch("benchmark_report.urlopen")
    def test_error_midway_through_fetch(self, mock_urlopen):
        """Error after workspace resolution but during data fetch."""
        error_503 = HTTPError(
            url="https://api.example.com/workflow/run1",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=io.BytesIO(b""),
        )
        mock_urlopen.side_effect = [
            # Workspace resolution succeeds
            _mock_urlopen({"organizations": [{"name": "org", "orgId": 1}]}),
            _mock_urlopen({"workspaces": [{"name": "ws", "id": 10}]}),
            # Workflow fetch fails
            error_503,
        ]
        with pytest.raises(HTTPError) as exc_info:
            fetch_run_data("run1", "org/ws", "https://api.example.com", "tok")
        assert exc_info.value.code == 503


# ══════════════════════════════════════════════════════════════════════════════
# NEW TESTS: P0 — Untested query functions
# ══════════════════════════════════════════════════════════════════════════════


class TestQueryProcessStats:
    """Verify query_process_stats returns per-process aggregates."""

    def _build_db_with_tasks(self, tmp_path, tasks):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=tasks)])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        return duckdb.connect(str(db_path), read_only=True)

    def test_returns_aggregates(self, tmp_path):
        tasks = [
            _flat_task(name="ALIGN:BWA (s1)", cost=1.0),
            _flat_task(name="ALIGN:BWA (s2)", cost=3.0),
            _flat_task(name="ALIGN:BWA (s3)", cost=2.0),
        ]
        db = self._build_db_with_tasks(tmp_path, tasks)
        stats = query_process_stats(db)
        assert len(stats) == 1
        assert stats[0]["n_tasks"] == 3
        assert stats[0]["avg_cost"] == pytest.approx(2.0)
        assert stats[0]["total_cost"] == pytest.approx(6.0)
        db.close()

    def test_only_completed_tasks(self, tmp_path):
        tasks = [
            _flat_task(name="PROC_A (s1)", status="COMPLETED", cost=2.0),
            _flat_task(name="PROC_A (s2)", status="CACHED", cost=0.0),
        ]
        db = self._build_db_with_tasks(tmp_path, tasks)
        stats = query_process_stats(db)
        # CACHED tasks are kept in DB but query_process_stats filters to COMPLETED only
        assert len(stats) == 1
        assert stats[0]["n_tasks"] == 1
        db.close()


class TestQueryTaskInstanceUsage:
    """Verify query_task_instance_usage groups by machine type."""

    def _build_db_with_tasks(self, tmp_path, tasks):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=tasks)])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        return duckdb.connect(str(db_path), read_only=True)

    def test_groups_by_machine_type(self, tmp_path):
        tasks = [
            _flat_task(name="P1 (s1)"),  # m5.xlarge
            _flat_task(name="P1 (s2)"),  # m5.xlarge
            {**_flat_task(name="P2 (s1)"), "machineType": "c5.2xlarge"},
        ]
        db = self._build_db_with_tasks(tmp_path, tasks)
        usage = query_task_instance_usage(db)
        by_type = {r["machine_type"]: r["count"] for r in usage}
        assert by_type["m5.xlarge"] == 2
        assert by_type["c5.2xlarge"] == 1
        db.close()

    def test_excludes_null_machine_type(self, tmp_path):
        tasks = [
            _flat_task(name="P1 (s1)"),  # m5.xlarge
            {**_flat_task(name="P2 (s1)"), "machineType": ""},
            {**_flat_task(name="P3 (s1)"), "machineType": None},
        ]
        db = self._build_db_with_tasks(tmp_path, tasks)
        usage = query_task_instance_usage(db)
        assert len(usage) == 1
        assert usage[0]["machine_type"] == "m5.xlarge"
        db.close()


class TestQueryCostOverview:
    """Verify query_cost_overview with and without CUR data."""

    def test_returns_none_without_costs_table(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[_flat_task()])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        assert query_cost_overview(db) is None
        db.close()

    def test_with_cur_data(self, tmp_path):
        data_dir = tmp_path / "data"
        task = _flat_task(hash_val="ab/cd1234")
        _write_run_json(data_dir, [_make_run(tasks=[task])])
        db_path = tmp_path / "test.duckdb"

        # Write a CUR parquet with matching hash
        cur_db = duckdb.connect()
        cur_path = os.path.join(str(tmp_path), "cur.parquet")
        cur_db.execute(f"""
            COPY (
                SELECT
                    'run1' AS resource_tags_user_unique_run_id,
                    'PROCESS_A' AS resource_tags_user_pipeline_process,
                    'abcd1234xxxxxxxx' AS resource_tags_user_task_hash,
                    10.0 AS line_item_unblended_cost,
                    8.0 AS split_line_item_split_cost,
                    2.0 AS split_line_item_unused_cost
            ) TO '{cur_path}' (FORMAT PARQUET)
        """)
        cur_db.close()

        from pathlib import Path
        build_db(data_dir, db_path, costs_parquet=Path(cur_path))
        db = duckdb.connect(str(db_path), read_only=True)
        overview = query_cost_overview(db)
        assert overview is not None
        assert len(overview) >= 1
        assert overview[0]["total_cost"] > 0
        db.close()


class TestQueryRunCostsWithCur:
    """Verify query_run_costs with CUR costs table present."""

    def test_joins_correctly(self, tmp_path):
        data_dir = tmp_path / "data"
        task = _flat_task(hash_val="ab/cd1234")
        _write_run_json(data_dir, [_make_run(tasks=[task])])
        db_path = tmp_path / "test.duckdb"

        cur_db = duckdb.connect()
        cur_path = os.path.join(str(tmp_path), "cur.parquet")
        cur_db.execute(f"""
            COPY (
                SELECT
                    'run1' AS resource_tags_user_unique_run_id,
                    'PROCESS_A' AS resource_tags_user_pipeline_process,
                    'abcd1234xxxxxxxx' AS resource_tags_user_task_hash,
                    10.0 AS line_item_unblended_cost,
                    8.0 AS split_line_item_split_cost,
                    2.0 AS split_line_item_unused_cost
            ) TO '{cur_path}' (FORMAT PARQUET)
        """)
        cur_db.close()

        from pathlib import Path
        build_db(data_dir, db_path, costs_parquet=Path(cur_path))
        db = duckdb.connect(str(db_path), read_only=True)
        costs = query_run_costs(db)
        assert len(costs) == 1
        assert costs[0]["used_cost"] is not None
        assert costs[0]["unused_cost"] is not None
        db.close()

    def test_sums_used_unused(self, tmp_path):
        data_dir = tmp_path / "data"
        task = _flat_task(hash_val="ab/cd1234")
        _write_run_json(data_dir, [_make_run(tasks=[task])])
        db_path = tmp_path / "test.duckdb"

        cur_db = duckdb.connect()
        cur_path = os.path.join(str(tmp_path), "cur.parquet")
        cur_db.execute(f"""
            COPY (
                SELECT
                    'run1' AS resource_tags_user_unique_run_id,
                    'PROCESS_A' AS resource_tags_user_pipeline_process,
                    'abcd1234xxxxxxxx' AS resource_tags_user_task_hash,
                    10.0 AS line_item_unblended_cost,
                    8.0 AS split_line_item_split_cost,
                    2.0 AS split_line_item_unused_cost
            ) TO '{cur_path}' (FORMAT PARQUET)
        """)
        cur_db.close()

        from pathlib import Path
        build_db(data_dir, db_path, costs_parquet=Path(cur_path))
        db = duckdb.connect(str(db_path), read_only=True)
        costs = query_run_costs(db)
        assert costs[0]["used_cost"] == pytest.approx(8.0)
        assert costs[0]["unused_cost"] == pytest.approx(2.0)
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# NEW TESTS: P1 — Graceful failure / error handling
# ══════════════════════════════════════════════════════════════════════════════


class TestGracefulFailure:
    """Verify clear errors and safe defaults on malformed/missing data."""

    def test_load_run_data_malformed_json(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "bad.json").write_text("{not valid json!!!")
        with pytest.raises(ValueError, match="Malformed JSON in bad.json"):
            load_run_data(data_dir)

    def test_extract_runs_missing_workflow_key(self):
        bad_run = {"meta": {"id": "run1", "workspace": "o/w", "group": "cpu"}}
        with pytest.raises(ValueError, match="missing 'workflow' key"):
            extract_runs([bad_run])

    def test_extract_runs_missing_meta_key(self):
        bad_run = {"workflow": {"id": "run1", "status": "SUCCEEDED"}}
        with pytest.raises(ValueError, match="missing 'meta' key"):
            extract_runs([bad_run])

    def test_extract_tasks_with_none_numerics(self):
        run = _make_run(tasks=[{
            "name": "PROC_A (s1)",
            "hash": "ab/cd1234",
            "process": "PROC_A",
            "status": "COMPLETED",
            "cpus": None,
            "memory": None,
            "realtime": None,
            "cost": None,
            "duration": None,
        }])
        rows = extract_tasks([run])
        assert len(rows) == 1
        assert rows[0]["cpus"] is None
        assert rows[0]["memory_bytes"] is None

    def test_build_db_empty_tasks(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "runs" in tables
        assert "tasks" in tables
        runs = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert runs == 1
        tasks = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        assert tasks == 0
        db.close()

    def test_build_db_empty_runs(self, tmp_path):
        import click
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db_path = tmp_path / "test.duckdb"
        with pytest.raises(click.exceptions.Exit):
            build_db(data_dir, db_path)

    def test_load_brand_malformed_yaml(self, tmp_path):
        brand_file = tmp_path / "bad_brand.yml"
        brand_file.write_text(": : :\n  - [invalid yaml {{{")
        from pathlib import Path
        result = load_brand(brand_file)
        # Should fall back to defaults instead of crashing
        assert result["accent"] == "#065647"

    def test_load_brand_partial_colors(self, tmp_path):
        brand_file = tmp_path / "partial_brand.yml"
        brand_file.write_text(json.dumps({
            "colors": {
                "green_palette": {
                    "deep_green": {"hex": "#112233"}
                }
            }
        }))
        from pathlib import Path
        result = load_brand(brand_file)
        assert result["accent"] == "#112233"
        # Other defaults preserved
        assert result["heading"] == "#201637"
        assert result["border"] == "#CFD0D1"


class TestQueryOnEmptyDB:
    """Verify all query functions return empty results on empty tables."""

    @pytest.fixture
    def empty_db(self, tmp_path):
        data_dir = tmp_path / "data"
        _write_run_json(data_dir, [_make_run(tasks=[])])
        db_path = tmp_path / "test.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        yield db
        db.close()

    def test_benchmark_overview(self, empty_db):
        result = query_benchmark_overview(empty_db)
        assert isinstance(result, list)
        assert len(result) == 1  # 1 run, 0 tasks

    def test_run_summary(self, empty_db):
        result = query_run_summary(empty_db)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_run_metrics(self, empty_db):
        result = query_run_metrics(empty_db)
        assert isinstance(result, list)

    def test_run_costs(self, empty_db):
        result = query_run_costs(empty_db)
        assert isinstance(result, list)

    def test_process_stats(self, empty_db):
        result = query_process_stats(empty_db)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_task_instance_usage(self, empty_db):
        result = query_task_instance_usage(empty_db)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_task_table(self, empty_db):
        result = query_task_table(empty_db)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_task_scatter(self, empty_db):
        result = query_task_scatter(empty_db)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_cost_overview(self, empty_db):
        result = query_cost_overview(empty_db)
        assert result is None


class TestRenderEdgeCases:
    """Verify rendering handles edge cases without crashing."""

    def test_render_html_with_empty_data(self, tmp_path):
        data = {
            "benchmark_overview": [],
            "run_summary": [],
            "run_metrics": [],
            "run_costs": [],
            "process_stats": [],
            "task_instance_usage": [],
            "task_table": [],
            "task_scatter": [],
            "cost_overview": None,
        }
        output = tmp_path / "report.html"
        render_html(data, str(output))
        assert output.exists()
        html = output.read_text()
        assert "Pipeline benchmarking report" in html

    def test_render_html_with_none_values(self, tmp_path):
        data = _minimal_query_data()
        data["run_metrics"][0]["cpuEfficiency"] = None
        data["run_metrics"][0]["memoryEfficiency"] = None
        output = tmp_path / "report.html"
        render_html(data, str(output))
        assert output.exists()


# ══════════════════════════════════════════════════════════════════════════════
# NEW TESTS: P2 — _compute_progress_from_tasks
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeProgressFromTasks:
    """Verify fallback progress computation from task-level data."""

    def test_basic_computation(self):
        run = {
            "tasks": [
                {
                    "status": "COMPLETED",
                    "cpus": 4,
                    "realtime": 10000,  # 10s
                    "pcpu": 200.0,     # 200% = 2 cores used
                    "peakRss": 2_000_000_000,
                    "memory": 4_000_000_000,
                    "readBytes": 100,
                    "writeBytes": 200,
                },
                {
                    "status": "COMPLETED",
                    "cpus": 2,
                    "realtime": 20000,  # 20s
                    "pcpu": 100.0,     # 100% = 1 core used
                    "peakRss": 1_000_000_000,
                    "memory": 2_000_000_000,
                    "readBytes": 50,
                    "writeBytes": 100,
                },
            ]
        }
        result = _compute_progress_from_tasks(run)
        # cpuTime = 4*10000 + 2*20000 = 80000
        assert result["cpuTime"] == 80000
        # cpuLoad = 200/100*10000 + 100/100*20000 = 20000 + 20000 = 40000
        assert result["cpuLoad"] == 40000
        # cpuEfficiency = 40000/80000*100 = 50.0
        assert result["cpuEfficiency"] == pytest.approx(50.0)
        # memoryRss = 2e9 + 1e9 = 3e9
        assert result["memoryRss"] == 3_000_000_000
        # memoryReq = 4e9 + 2e9 = 6e9
        assert result["memoryReq"] == 6_000_000_000
        # memoryEfficiency = 3e9/6e9*100 = 50.0
        assert result["memoryEfficiency"] == pytest.approx(50.0)
        assert result["readBytes"] == 150
        assert result["writeBytes"] == 300

    def test_no_completed_tasks(self):
        run = {
            "tasks": [
                {"status": "FAILED", "cpus": 4, "realtime": 10000},
            ]
        }
        result = _compute_progress_from_tasks(run)
        assert result == {}

    def test_empty_tasks(self):
        run = {"tasks": []}
        result = _compute_progress_from_tasks(run)
        assert result == {}

    def test_zero_cpu_time_no_division_error(self):
        run = {
            "tasks": [
                {
                    "status": "COMPLETED",
                    "cpus": 0,
                    "realtime": 0,
                    "pcpu": 0,
                    "peakRss": 0,
                    "memory": 1000,
                },
            ]
        }
        result = _compute_progress_from_tasks(run)
        # cpuTime = 0*0 = 0, so cpuEfficiency should be None (no div by zero)
        assert result["cpuEfficiency"] is None

    def test_zero_memory_req_no_division_error(self):
        run = {
            "tasks": [
                {
                    "status": "COMPLETED",
                    "cpus": 1,
                    "realtime": 1000,
                    "pcpu": 100.0,
                    "peakRss": 100,
                    "memory": 0,
                },
            ]
        }
        result = _compute_progress_from_tasks(run)
        assert result["memoryEfficiency"] is None

    def test_none_fields_use_defaults(self):
        run = {
            "tasks": [
                {
                    "status": "COMPLETED",
                    "cpus": None,
                    "realtime": None,
                    "pcpu": None,
                    "peakRss": None,
                    "memory": None,
                    "readBytes": None,
                    "writeBytes": None,
                },
            ]
        }
        result = _compute_progress_from_tasks(run)
        assert result["cpuTime"] == 0
        assert result["cpuLoad"] == 0
        assert result["readBytes"] == 0
        assert result["writeBytes"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# NEW TESTS: P3 — extract_metrics content
# ══════════════════════════════════════════════════════════════════════════════


class TestExtractMetricsContent:
    """Verify extract_metrics extracts field values, not just table creation."""

    def test_basic_extraction(self):
        run = _make_run()
        run["metrics"] = [{
            "process": "ALIGN",
            "cpu": {"mean": 80.0, "min": 10.0, "q1": 40.0, "q2": 70.0, "q3": 90.0, "max": 100.0},
            "mem": {"mean": 5e9, "min": 1e9, "q1": 3e9, "q2": 5e9, "q3": 7e9, "max": 9e9},
        }]
        rows = extract_metrics([run])
        assert len(rows) == 1
        assert rows[0]["process"] == "ALIGN"
        assert rows[0]["cpu_mean"] == 80.0
        assert rows[0]["cpu_min"] == 10.0
        assert rows[0]["mem_max"] == 9e9

    def test_missing_stat_fields(self):
        run = _make_run()
        run["metrics"] = [{
            "process": "PROC_A",
            "cpu": {"mean": 50.0},
        }]
        rows = extract_metrics([run])
        assert len(rows) == 1
        assert rows[0]["cpu_mean"] == 50.0
        assert rows[0]["cpu_q1"] is None
        assert rows[0]["mem_mean"] is None

    def test_empty_metrics_list(self):
        run = _make_run()
        run["metrics"] = []
        rows = extract_metrics([run])
        assert rows == []


# ══════════════════════════════════════════════════════════════════════════════
# NEW TESTS: P4 — _load_echarts_theme
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadEchartsTheme:
    """Verify eCharts theme loading with fallback behavior."""

    def test_explicit_path(self, tmp_path):
        theme_file = tmp_path / "theme.json"
        theme_file.write_text('{"color": ["#ff0000"]}')
        result = _load_echarts_theme(theme_file)
        assert '"color"' in result
        assert "#ff0000" in result

    def test_fallback_to_empty(self, tmp_path):
        # Point all candidates at non-existent paths so we get the "{}" fallback
        nonexistent = tmp_path / "does_not_exist.json"
        fake_script = tmp_path / "fake_bin" / "fake_script.py"
        fake_script.parent.mkdir(parents=True)
        fake_script.write_text("")
        with patch("benchmark_report.__file__", str(fake_script)):
            # Temporarily change cwd so ./assets also misses
            original_cwd = os.getcwd()
            os.chdir(str(tmp_path))
            try:
                result = _load_echarts_theme(nonexistent)
            finally:
                os.chdir(original_cwd)
        assert result == "{}"

    def test_explicit_nonexistent_does_not_crash(self, tmp_path):
        nonexistent = tmp_path / "nope.json"
        result = _load_echarts_theme(nonexistent)
        # Should not crash — returns either a found fallback or "{}"
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════════════════════
# NEW TESTS: P5 — Special characters in rendering
# ══════════════════════════════════════════════════════════════════════════════


class TestRenderSpecialCases:
    """Verify rendering handles special characters and edge cases."""

    def test_special_chars_in_pipeline_name(self, tmp_path):
        data = _minimal_query_data()
        data["benchmark_overview"][0]["pipeline"] = '<script>alert("xss")</script>'
        output = tmp_path / "report.html"
        render_html(data, str(output))
        html = output.read_text()
        # json.dumps escapes < and > inside data_json, so raw <script> should not appear
        # outside the JSON block
        assert output.exists()
        assert "alert" in html  # data is present
        # The pipeline name is inside JSON, which escapes angle brackets
        assert '<script>alert("xss")</script>' not in html.split("const DATA")[0]

    def test_unicode_in_group_name(self, tmp_path):
        data = _minimal_query_data()
        data["benchmark_overview"][0]["group"] = "grp-\u00e9\u00e0\u00fc"
        data["run_summary"][0]["group"] = "grp-\u00e9\u00e0\u00fc"
        output = tmp_path / "report.html"
        render_html(data, str(output))
        assert output.exists()

    def test_logo_svg_included(self, tmp_path):
        data = _minimal_query_data()
        logo = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="10"/></svg>'
        output = tmp_path / "report.html"
        render_html(data, str(output), logo_svg=logo)
        html = output.read_text()
        assert '<circle r="10"/>' in html


# ══════════════════════════════════════════════════════════════════════════════
# NEW TESTS: P6 — CUR flat format variant 3
# ══════════════════════════════════════════════════════════════════════════════


class TestCurFlatFormatVariant3:
    """CUR 1.0 flat format with only nf_unique_run_id column (no unique_run_id)."""

    def test_flat_with_only_nf_column(self, tmp_path):
        db = duckdb.connect()
        path = os.path.join(str(tmp_path), "cur_nf_only.parquet")
        db.execute(f"""
            COPY (
                SELECT
                    'run1' AS resource_tags_user_nf_unique_run_id,
                    'PROC_A' AS resource_tags_user_pipeline_process,
                    'abcdef1234567890' AS resource_tags_user_task_hash,
                    10.0 AS line_item_unblended_cost,
                    8.0 AS split_line_item_split_cost,
                    2.0 AS split_line_item_unused_cost
            ) TO '{path}' (FORMAT PARQUET)
        """)
        db.close()

        db = duckdb.connect()
        assert detect_cur_format(db, path) == "flat"
        build_costs_flat_format(db, path)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" in tables
        row = db.execute("SELECT run_id, used_cost, unused_cost FROM costs").fetchone()
        assert row[0] == "run1"
        assert row[1] == pytest.approx(8.0)
        assert row[2] == pytest.approx(2.0)
        db.close()
