"""Tests for clean_cur.py — CUR parquet to CSV normalization.

Run: uv run --with duckdb --with jinja2 --with typer --with pyyaml --with pyarrow --with pytest pytest bin/test_clean_cur.py -v
"""
import os

import duckdb
import pytest

from clean_cur import (
    build_costs_flat_format,
    build_costs_map_format,
    detect_format,
)


# ── CUR 1.0 (flattened columns) ─────────────────────────────────────────────

class TestCurOldFormatColumnDetection:
    """Old CUR parquet may have resource_tags_user_unique_run_id but NOT
    resource_tags_user_nf_unique_run_id."""

    def _write_old_cur(self, tmp_path, run_id="run1", include_nf_col=False):
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
        cur = self._write_old_cur(tmp_path)
        db = duckdb.connect()
        assert detect_format(db, cur) == "flat"
        db.close()

    def test_old_format_without_nf_column(self, tmp_path):
        cur = self._write_old_cur(tmp_path, run_id="run1")
        db = duckdb.connect()
        build_costs_flat_format(db, cur)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" in tables
        db.close()

    def test_old_format_with_both_columns(self, tmp_path):
        cur = self._write_old_cur(tmp_path, run_id="run1", include_nf_col=True)
        db = duckdb.connect()
        build_costs_flat_format(db, cur)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" in tables
        db.close()

    def test_old_format_extracts_costs(self, tmp_path):
        cur = self._write_old_cur(tmp_path)
        db = duckdb.connect()
        build_costs_flat_format(db, cur)
        row = db.execute("SELECT used_cost, unused_cost FROM costs").fetchone()
        assert row[0] == pytest.approx(8.0)
        assert row[1] == pytest.approx(2.0)
        db.close()


# ── CUR 2.0 (MAP format) ────────────────────────────────────────────────────

class TestCurNewMapFormat:
    """New AWS CUR exports use MAP(VARCHAR,VARCHAR) resource_tags column."""

    def _write_new_cur(self, tmp_path, run_id="run1"):
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
        cur = self._write_new_cur(tmp_path)
        db = duckdb.connect()
        assert detect_format(db, cur) == "map"
        db.close()

    def test_map_format_creates_costs_table(self, tmp_path):
        cur = self._write_new_cur(tmp_path, run_id="run1")
        db = duckdb.connect()
        build_costs_map_format(db, cur)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" in tables
        db.close()

    def test_map_format_extracts_run_id(self, tmp_path):
        cur = self._write_new_cur(tmp_path, run_id="run1")
        db = duckdb.connect()
        build_costs_map_format(db, cur)
        rid = db.execute("SELECT run_id FROM costs").fetchone()[0]
        assert rid == "run1"
        db.close()

    def test_map_format_extracts_costs(self, tmp_path):
        cur = self._write_new_cur(tmp_path, run_id="run1")
        db = duckdb.connect()
        build_costs_map_format(db, cur)
        row = db.execute("SELECT used_cost, unused_cost FROM costs").fetchone()
        assert row[0] == pytest.approx(8.0)
        assert row[1] == pytest.approx(2.0)
        db.close()
