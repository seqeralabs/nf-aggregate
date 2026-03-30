"""Tests for benchmark_report.py — unified benchmark CLI.

Run: uv run --with duckdb --with typer --with pyyaml --with jinja2 --with pyarrow --with httpx --with pytest pytest bin/test_benchmark_report.py -v
"""

import json
import os
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from benchmark_report import (
    REPORT_TEMPLATE,
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


# ── Brand loading ───────────────────────────────────────────────────────────


class TestBrandLoading:
    """Verify brand.yml loading."""

    def test_defaults_without_brand_file(self):
        brand = load_brand(None)
        assert brand["accent"] == "#087F68"
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


def _mock_response(json_data, status_code=200):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


class TestResolveWorkspaceId:
    """Verify workspace resolution from org/workspace string."""

    @patch("benchmark_report.httpx.get")
    def test_resolves_workspace(self, mock_get):
        mock_get.side_effect = [
            _mock_response({
                "organizations": [{"name": "myorg", "orgId": 42}]
            }),
            _mock_response({
                "workspaces": [{"name": "myws", "id": 99}]
            }),
        ]
        ws_id = resolve_workspace_id(
            "myorg/myws", "https://api.example.com", {"Authorization": "Bearer tok"}
        )
        assert ws_id == 99
        assert mock_get.call_count == 2

    @patch("benchmark_report.httpx.get")
    def test_raises_on_missing_org(self, mock_get):
        mock_get.return_value = _mock_response({"organizations": []})
        with pytest.raises(RuntimeError, match="Organization.*not found"):
            resolve_workspace_id(
                "badorg/ws", "https://api.example.com", {}
            )

    @patch("benchmark_report.httpx.get")
    def test_raises_on_missing_workspace(self, mock_get):
        mock_get.side_effect = [
            _mock_response({"organizations": [{"name": "org", "orgId": 1}]}),
            _mock_response({"workspaces": []}),
        ]
        with pytest.raises(RuntimeError, match="Workspace.*not found"):
            resolve_workspace_id(
                "org/badws", "https://api.example.com", {}
            )


class TestFetchAllTasks:
    """Verify task pagination."""

    @patch("benchmark_report.httpx.get")
    def test_single_page(self, mock_get):
        mock_get.return_value = _mock_response({
            "tasks": [{"task": {"id": i}} for i in range(50)]
        })
        tasks = fetch_all_tasks("https://api.example.com/workflow/1/tasks?workspaceId=1", {})
        assert len(tasks) == 50
        assert mock_get.call_count == 1

    @patch("benchmark_report.httpx.get")
    def test_multi_page(self, mock_get):
        full_page = [{"task": {"id": i}} for i in range(100)]
        partial_page = [{"task": {"id": i}} for i in range(30)]
        mock_get.side_effect = [
            _mock_response({"tasks": full_page}),
            _mock_response({"tasks": partial_page}),
        ]
        tasks = fetch_all_tasks("https://api.example.com/workflow/1/tasks?workspaceId=1", {})
        assert len(tasks) == 130
        assert mock_get.call_count == 2


class TestFetchRunData:
    """Verify fetch_run_data calls all required API endpoints."""

    @patch("benchmark_report.httpx.get")
    def test_calls_four_endpoints(self, mock_get):
        # Setup responses for: orgs, workspaces, workflow, metrics, tasks, progress
        mock_get.side_effect = [
            # resolve_workspace_id: GET /orgs
            _mock_response({"organizations": [{"name": "org", "orgId": 1}]}),
            # resolve_workspace_id: GET /orgs/1/workspaces
            _mock_response({"workspaces": [{"name": "ws", "id": 10}]}),
            # GET /workflow/{id}
            _mock_response({"workflow": {"id": "abc123", "status": "SUCCEEDED"}}),
            # GET /workflow/{id}/metrics
            _mock_response({"metrics": [{"process": "PROC_A"}]}),
            # GET /workflow/{id}/tasks (single page)
            _mock_response({"tasks": [{"task": {"name": "t1"}}]}),
            # GET /workflow/{id}/progress
            _mock_response({"progress": {"workflowProgress": {}}}),
        ]
        result = fetch_run_data("abc123", "org/ws", "https://api.example.com", "tok123")

        assert result["workflow"]["id"] == "abc123"
        assert len(result["metrics"]) == 1
        assert len(result["tasks"]) == 1
        assert result["progress"] is not None
        # 2 calls for workspace resolution + 4 data endpoints = 6 total
        assert mock_get.call_count == 6

    @patch("benchmark_report.httpx.get")
    def test_returns_expected_keys(self, mock_get):
        mock_get.side_effect = [
            _mock_response({"organizations": [{"name": "o", "orgId": 1}]}),
            _mock_response({"workspaces": [{"name": "w", "id": 5}]}),
            _mock_response({"workflow": {"id": "r1"}}),
            _mock_response({"metrics": []}),
            _mock_response({"tasks": []}),
            _mock_response({"progress": {"workflowProgress": {}}}),
        ]
        result = fetch_run_data("r1", "o/w", "https://api.example.com", "tok")
        assert set(result.keys()) == {"workflow", "metrics", "tasks", "progress"}
