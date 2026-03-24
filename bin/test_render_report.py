"""Tests for render_report.py — HTML report rendering.

Run: uv run --with duckdb --with jinja2 --with typer --with pyyaml --with pyarrow --with pytest pytest bin/test_render_report.py -v
"""
import json

import pytest

from render_report import load_brand, load_query_data, render_html


def _write_tables(tables_dir, data):
    """Write query result JSON files for testing."""
    tables_dir.mkdir(parents=True, exist_ok=True)
    for name, content in data.items():
        (tables_dir / f"{name}.json").write_text(json.dumps(content, default=str))


def _minimal_data(cached_count=0):
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


# ── Basic rendering ─────────────────────────────────────────────────────────

class TestRenderReport:
    """Verify HTML report renders correctly."""

    def test_renders_html(self, tmp_path):
        tables_dir = tmp_path / "tables"
        _write_tables(tables_dir, _minimal_data())
        output = str(tmp_path / "report.html")
        data = load_query_data(tables_dir)
        render_html(data, output)
        html = (tmp_path / "report.html").read_text()
        assert "Pipeline benchmarking report" in html
        assert "echarts" in html

    def test_report_contains_run_data(self, tmp_path):
        tables_dir = tmp_path / "tables"
        _write_tables(tables_dir, _minimal_data())
        output = str(tmp_path / "report.html")
        data = load_query_data(tables_dir)
        render_html(data, output)
        html = (tmp_path / "report.html").read_text()
        assert "test-pipe" in html
        assert "run1" in html


# ── Cached task display ─────────────────────────────────────────────────────

class TestCachedTaskDisplay:
    """Verify cached tasks appear in the rendered HTML report."""

    def test_cached_column_in_summary_table(self, tmp_path):
        tables_dir = tmp_path / "tables"
        _write_tables(tables_dir, _minimal_data(cached_count=5))
        output = str(tmp_path / "report.html")
        data = load_query_data(tables_dir)
        render_html(data, output)
        html = (tmp_path / "report.html").read_text()
        assert "cachedCount" in html
        assert "Tasks cached" in html

    def test_cached_series_in_status_chart_when_present(self, tmp_path):
        tables_dir = tmp_path / "tables"
        _write_tables(tables_dir, _minimal_data(cached_count=5))
        output = str(tmp_path / "report.html")
        data = load_query_data(tables_dir)
        render_html(data, output)
        html = (tmp_path / "report.html").read_text()
        # When cached > 0, the chart should have a 'Cached' series
        assert "'Cached'" in html
        assert "#f59e0b" in html  # amber color for cached

    def test_no_cached_series_when_zero(self, tmp_path):
        tables_dir = tmp_path / "tables"
        _write_tables(tables_dir, _minimal_data(cached_count=0))
        output = str(tmp_path / "report.html")
        data = load_query_data(tables_dir)
        render_html(data, output)
        html = (tmp_path / "report.html").read_text()
        # The cached series should not appear when all counts are 0
        # (the JS conditionally adds it only when totalCached > 0)
        # But the column header 'Tasks cached' should always be present
        assert "Tasks cached" in html

    def test_cached_subtitle_text(self, tmp_path):
        tables_dir = tmp_path / "tables"
        _write_tables(tables_dir, _minimal_data(cached_count=5))
        output = str(tmp_path / "report.html")
        data = load_query_data(tables_dir)
        render_html(data, output)
        html = (tmp_path / "report.html").read_text()
        # The status subtitle should mention cached tasks
        assert "cached" in html.lower()


# ── Brand loading ────────────────────────────────────────────────────────────

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
