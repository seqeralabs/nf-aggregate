# Consolidate Benchmark Report Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the 4 separate Python scripts (`clean_json.py`, `clean_cur.py`, `build_tables.py`, `render_report.py`) into a single `benchmark_report.py` with 3 subcommands: `build-db`, `report`, and `fetch` (API calls → JSON). The DuckDB database file becomes the universal interchange format for both the HTML report and agent-driven ad-hoc queries.

**Architecture:** Single Typer CLI (`bin/benchmark_report.py`) with subcommands. `fetch` calls the Seqera Platform API and writes run JSON files. `build-db` reads JSON files (+ optional CUR parquet) and produces a `benchmark.duckdb` file with normalized tables. `report` takes a `.duckdb` file and renders the self-contained HTML report. The Nextflow pipeline calls `benchmark_report.py build-db` then `benchmark_report.py report`, collapsing 4 Nextflow processes into 1.

**Tech Stack:** Python 3.12, DuckDB 1.3, Typer 0.15, Jinja2 3.1, PyYAML 6, PyArrow 18 (for CUR), httpx (for API calls)

---

## File Structure

| Action | Path                                             | Responsibility                                                                          |
| ------ | ------------------------------------------------ | --------------------------------------------------------------------------------------- |
| Create | `bin/benchmark_report.py`                        | Single CLI with `fetch`, `build-db`, `report` subcommands                               |
| Create | `bin/test_benchmark_report.py`                   | Unified test suite for all subcommands                                                  |
| Delete | `bin/clean_json.py`                              | Replaced by `build-db` subcommand                                                       |
| Delete | `bin/clean_cur.py`                               | Replaced by `build-db` subcommand                                                       |
| Delete | `bin/build_tables.py`                            | Queries move into `report` subcommand                                                   |
| Delete | `bin/render_report.py`                           | Becomes `report` subcommand                                                             |
| Delete | `bin/test_clean_json.py`                         | Consolidated into `test_benchmark_report.py`                                            |
| Delete | `bin/test_clean_cur.py`                          | Consolidated into `test_benchmark_report.py`                                            |
| Delete | `bin/test_build_tables.py`                       | Consolidated into `test_benchmark_report.py`                                            |
| Delete | `bin/test_render_report.py`                      | Consolidated into `test_benchmark_report.py`                                            |
| Create | `modules/local/benchmark_report/main.nf`         | Single Nextflow process replacing CLEAN_JSON + CLEAN_CUR + BUILD_TABLES + RENDER_REPORT |
| Create | `modules/local/benchmark_report/nextflow.config` | publishDir config for the new process                                                   |
| Delete | `modules/local/clean_json/`                      | Replaced by benchmark_report module                                                     |
| Delete | `modules/local/clean_cur/`                       | Replaced by benchmark_report module                                                     |
| Delete | `modules/local/build_tables/`                    | Replaced by benchmark_report module                                                     |
| Delete | `modules/local/render_report/`                   | Replaced by benchmark_report module                                                     |
| Modify | `workflows/nf_aggregate/main.nf`                 | Replace 4-process pipeline with single BENCHMARK_REPORT call                            |
| Modify | `workflows/nf_aggregate/nextflow.config`         | Replace render_report config include with benchmark_report                              |
| Modify | `tests/default.nf.test`                          | Update snapshot expectations                                                            |
| Modify | `docs/DESIGN.md`                                 | Update architecture docs                                                                |
| Modify | `AGENTS.md`                                      | Update architecture docs                                                                |
| Modify | `bin/AGENTS.md`                                  | Update script docs                                                                      |

## Subcommand Design

### `benchmark_report.py fetch`

```
benchmark_report.py fetch \
    --run-id <id> \
    --workspace <org/workspace> \
    --api-endpoint https://api.cloud.seqera.io \
    --output-dir ./json_data
```

Calls 4 Seqera Platform API endpoints per run (workflow, metrics, tasks, progress). Writes one JSON file per run to `--output-dir`. Uses `TOWER_ACCESS_TOKEN` env var. This subcommand is for **agent standalone use** — the Nextflow pipeline uses `SeqeraApi.groovy` instead.

### `benchmark_report.py build-db`

```
benchmark_report.py build-db \
    --data-dir ./json_data \
    --costs cur.parquet \        # optional
    --output benchmark.duckdb
```

Reads JSON files from `--data-dir`, normalizes into DuckDB tables (`runs`, `tasks`, `metrics`, optionally `costs`), and persists to a `.duckdb` file. This is the agent interchange format — any tool can open and query this file.

### `benchmark_report.py report`

```
benchmark_report.py report \
    --db benchmark.duckdb \
    --brand brand.yml \          # optional
    --logo logo.svg \            # optional
    --output benchmark_report.html
```

Opens the DuckDB file, runs the 9 fixed queries, renders the HTML report. No intermediate JSON files.

### Nextflow shortcut

The Nextflow process will call:

```bash
benchmark_report.py build-db --data-dir $data_dir $cost_flag --output benchmark.duckdb
benchmark_report.py report --db benchmark.duckdb $brand_flag $logo_flag --output benchmark_report.html
```

---

## Task 1: Create `bin/benchmark_report.py` with `build-db` subcommand

**Files:**

- Create: `bin/benchmark_report.py`
- Create: `bin/test_benchmark_report.py`

This task creates the script skeleton and the `build-db` subcommand, which is the core data normalization step. All functions from `clean_json.py` and `clean_cur.py` are merged here.

- [ ] **Step 1: Write failing test for JSON loading and run extraction**

```python
"""Tests for benchmark_report.py — unified benchmark report CLI."""
import json
import os

import duckdb
import pytest


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
        "name": name, "hash": hash_val, "process": name.split(":")[0],
        "status": status, "cpus": 4, "memory": 8_000_000_000,
        "realtime": 60000, "peakRss": 4_000_000_000, "cost": cost,
        "executor": "awsbatch", "machineType": "m5.xlarge",
        "cloudZone": "us-east-1a", "duration": 65000,
    }


def _nested_task(**kwargs):
    return {"task": _flat_task(**kwargs)}


def _write_run_json(tmp_path, run_dict, filename="run1.json"):
    data_dir = tmp_path / "json_data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / filename).write_text(json.dumps(run_dict))
    return data_dir


# ── build-db: JSON normalization ──────────────────────────────────────────

from benchmark_report import build_db, load_run_data, extract_runs, extract_tasks, extract_metrics


class TestLoadRunData:
    def test_loads_json_files(self, tmp_path):
        data_dir = _write_run_json(tmp_path, _make_run())
        runs = load_run_data(data_dir)
        assert len(runs) == 1


class TestExtractRuns:
    def test_cached_count_extracted(self):
        rows = extract_runs([_make_run(cached_count=10, succeed_count=50)])
        assert rows[0]["cached"] == 10

    def test_zero_cached_defaults(self):
        run = _make_run()
        del run["workflow"]["stats"]["cachedCount"]
        rows = extract_runs([run])
        assert rows[0]["cached"] == 0


class TestExtractTasks:
    def test_nested_tasks_unwrapped(self):
        run = _make_run(tasks=[_nested_task(cost=2.50)])
        rows = extract_tasks([run])
        assert rows[0]["cost"] == pytest.approx(2.50)

    def test_flat_tasks_work(self):
        run = _make_run(tasks=[_flat_task(cost=1.00)])
        rows = extract_tasks([run])
        assert rows[0]["cost"] == pytest.approx(1.00)


class TestBuildDb:
    def test_creates_duckdb_file(self, tmp_path):
        data_dir = _write_run_json(tmp_path, _make_run(tasks=[_flat_task()]))
        db_path = tmp_path / "benchmark.duckdb"
        build_db(data_dir, db_path)
        assert db_path.exists()
        db = duckdb.connect(str(db_path), read_only=True)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "runs" in tables
        assert "tasks" in tables

    def test_failed_tasks_filtered(self, tmp_path):
        run = _make_run(tasks=[
            _flat_task(status="COMPLETED"),
            _flat_task(status="FAILED"),
            _flat_task(status="CACHED"),
        ])
        data_dir = _write_run_json(tmp_path, run)
        db_path = tmp_path / "benchmark.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        assert count == 2  # COMPLETED + CACHED

    def test_process_short_derived(self, tmp_path):
        task = _flat_task(name="NF:PIPELINE:PROC_A")
        task["process"] = "NF:PIPELINE:PROC_A"
        run = _make_run(tasks=[task])
        data_dir = _write_run_json(tmp_path, run)
        db_path = tmp_path / "benchmark.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        val = db.execute("SELECT process_short FROM tasks LIMIT 1").fetchone()[0]
        assert val == "PROC_A"

    def test_metrics_table_when_present(self, tmp_path):
        run = _make_run()
        run["metrics"] = [{"process": "P", "cpu": {"mean": 50, "min": 10, "q1": 30, "q2": 50, "q3": 70, "max": 90}}]
        data_dir = _write_run_json(tmp_path, run)
        db_path = tmp_path / "benchmark.duckdb"
        build_db(data_dir, db_path)
        db = duckdb.connect(str(db_path), read_only=True)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "metrics" in tables
```

Run: `cd bin && uv run --with duckdb --with typer --with pyyaml --with jinja2 --with pyarrow --with pytest pytest test_benchmark_report.py -v`
Expected: FAIL (module not found)

- [ ] **Step 2: Write `benchmark_report.py` with `build-db` subcommand**

Create `bin/benchmark_report.py` with:

- `load_run_data()`, `extract_runs()`, `extract_tasks()`, `extract_metrics()` — ported verbatim from `clean_json.py`
- CUR functions `detect_format()`, `build_costs_map_format()`, `build_costs_flat_format()` — ported from `clean_cur.py`
- `build_db()` function that creates a persistent DuckDB file with all tables
- Typer app with `build-db` subcommand

The `build_db()` function should:

1. Load run JSON files from `--data-dir`
2. Extract runs, tasks, metrics into DuckDB tables
3. Optionally load CUR parquet into `costs` table
4. Persist to `--output` DuckDB file

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd bin && uv run --with duckdb --with typer --with pyyaml --with jinja2 --with pyarrow --with pytest pytest test_benchmark_report.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add bin/benchmark_report.py bin/test_benchmark_report.py
git commit -m "✨ feat(benchmark): add benchmark_report.py with build-db subcommand"
```

---

## Task 2: Add CUR cost support to `build-db`

**Files:**

- Modify: `bin/benchmark_report.py`
- Modify: `bin/test_benchmark_report.py`

- [ ] **Step 1: Write failing CUR tests**

Add to `test_benchmark_report.py`:

```python
from benchmark_report import detect_cur_format, build_costs_map_format, build_costs_flat_format


class TestCurFlatFormat:
    def _write_flat_cur(self, tmp_path, run_id="run1"):
        db = duckdb.connect()
        path = str(tmp_path / "cur.parquet")
        db.execute(f"""
            COPY (
                SELECT
                    '{run_id}' AS resource_tags_user_unique_run_id,
                    'PROC_A' AS resource_tags_user_pipeline_process,
                    'abcdef1234567890' AS resource_tags_user_task_hash,
                    10.0 AS line_item_unblended_cost,
                    8.0 AS split_line_item_split_cost,
                    2.0 AS split_line_item_unused_cost
            ) TO '{path}' (FORMAT PARQUET)
        """)
        db.close()
        return path

    def test_detects_flat(self, tmp_path):
        cur = self._write_flat_cur(tmp_path)
        db = duckdb.connect()
        assert detect_cur_format(db, cur) == "flat"

    def test_extracts_costs(self, tmp_path):
        cur = self._write_flat_cur(tmp_path)
        db = duckdb.connect()
        build_costs_flat_format(db, cur)
        row = db.execute("SELECT used_cost, unused_cost FROM costs").fetchone()
        assert row[0] == pytest.approx(8.0)
        assert row[1] == pytest.approx(2.0)


class TestCurMapFormat:
    def _write_map_cur(self, tmp_path, run_id="run1"):
        db = duckdb.connect()
        path = str(tmp_path / "cur_new.parquet")
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

    def test_detects_map(self, tmp_path):
        cur = self._write_map_cur(tmp_path)
        db = duckdb.connect()
        assert detect_cur_format(db, cur) == "map"

    def test_extracts_run_id(self, tmp_path):
        cur = self._write_map_cur(tmp_path)
        db = duckdb.connect()
        build_costs_map_format(db, cur)
        assert db.execute("SELECT run_id FROM costs").fetchone()[0] == "run1"


class TestBuildDbWithCosts:
    def test_costs_table_from_cur(self, tmp_path):
        # Write run JSON
        data_dir = _write_run_json(tmp_path, _make_run(tasks=[_flat_task()]))
        # Write CUR parquet
        db = duckdb.connect()
        cur_path = str(tmp_path / "cur.parquet")
        db.execute(f"""
            COPY (SELECT 'run1' AS resource_tags_user_unique_run_id,
                  'PROC_A' AS resource_tags_user_pipeline_process,
                  'abcdef12' AS resource_tags_user_task_hash,
                  10.0 AS line_item_unblended_cost,
                  8.0 AS split_line_item_split_cost,
                  2.0 AS split_line_item_unused_cost
            ) TO '{cur_path}' (FORMAT PARQUET)
        """)
        db.close()
        # Build DB with costs
        from pathlib import Path
        db_path = tmp_path / "benchmark.duckdb"
        build_db(data_dir, db_path, costs_parquet=Path(cur_path))
        db = duckdb.connect(str(db_path), read_only=True)
        tables = {r[0] for r in db.execute("SHOW TABLES").fetchall()}
        assert "costs" in tables
```

Run: `cd bin && uv run --with duckdb --with typer --with pyyaml --with jinja2 --with pyarrow --with pytest pytest test_benchmark_report.py::TestCurFlatFormat -v`
Expected: FAIL (import errors)

- [ ] **Step 2: Add CUR functions and `--costs` flag to `build-db`**

Port `detect_format()` → `detect_cur_format()`, `build_costs_map_format()`, `build_costs_flat_format()` from `clean_cur.py`. Add `--costs` optional parameter to the `build-db` subcommand.

- [ ] **Step 3: Run all tests**

Run: `cd bin && uv run --with duckdb --with typer --with pyyaml --with jinja2 --with pyarrow --with pytest pytest test_benchmark_report.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add bin/benchmark_report.py bin/test_benchmark_report.py
git commit -m "✨ feat(benchmark): add CUR cost support to build-db subcommand"
```

---

## Task 3: Add `report` subcommand

**Files:**

- Modify: `bin/benchmark_report.py`
- Modify: `bin/test_benchmark_report.py`

The `report` subcommand opens a DuckDB file, runs the 9 fixed queries, and renders the HTML report. The queries move from `build_tables.py` and the template + rendering from `render_report.py`.

- [ ] **Step 1: Write failing tests for report subcommand**

Add to `test_benchmark_report.py`:

```python
from benchmark_report import render_report, load_brand


class TestRenderReport:
    def _build_test_db(self, tmp_path):
        """Build a DuckDB file from test data for rendering."""
        data_dir = _write_run_json(tmp_path, _make_run(
            tasks=[_flat_task()], cached_count=5, succeed_count=10,
        ))
        db_path = tmp_path / "benchmark.duckdb"
        build_db(data_dir, db_path)
        return db_path

    def test_renders_html(self, tmp_path):
        db_path = self._build_test_db(tmp_path)
        output = tmp_path / "report.html"
        render_report(db_path, output)
        html = output.read_text()
        assert "Pipeline benchmarking report" in html
        assert "echarts" in html

    def test_contains_run_data(self, tmp_path):
        db_path = self._build_test_db(tmp_path)
        output = tmp_path / "report.html"
        render_report(db_path, output)
        html = output.read_text()
        assert "run1" in html

    def test_cached_column_present(self, tmp_path):
        db_path = self._build_test_db(tmp_path)
        output = tmp_path / "report.html"
        render_report(db_path, output)
        html = output.read_text()
        assert "Tasks cached" in html
        assert "'Cached'" in html  # JS series name


class TestBrandLoading:
    def test_defaults_without_file(self):
        brand = load_brand(None)
        assert brand["accent"] == "#087F68"
        assert len(brand["palette"]) == 10

    def test_loads_brand_file(self, tmp_path):
        brand_yml = tmp_path / "brand.yml"
        brand_yml.write_text("colors:\n  green_palette:\n    deep_green:\n      hex: '#112233'\n")
        brand = load_brand(brand_yml)
        assert brand["accent"] == "#112233"
```

Run tests, expected: FAIL

- [ ] **Step 2: Add query functions and `render_report()` to `benchmark_report.py`**

Port from `build_tables.py`:

- `fetch_dicts()`, `table_exists()`
- All 9 `query_*()` functions

Port from `render_report.py`:

- `load_brand()`, `_load_echarts_theme()`
- `render_html()` (rename to `_render_html()` — internal)
- `REPORT_TEMPLATE` constant
- `render_report()` — new public function that opens DB, runs queries, renders HTML

The key change: `render_report()` takes a `db_path` (Path to .duckdb), not a `tables_dir`. It opens the DB, runs the 9 queries to get dicts, and passes them to `_render_html()`.

- [ ] **Step 3: Add `report` Typer subcommand**

```python
@app.command()
def report(
    db: Path = typer.Option(..., exists=True, help="DuckDB database file"),
    output: Path = typer.Option(Path("benchmark_report.html"), help="Output HTML file"),
    brand: Path = typer.Option(None, help="Brand YAML file"),
    logo: Path = typer.Option(None, help="SVG logo file"),
) -> None:
    """Render benchmark HTML report from a DuckDB database."""
    render_report(db, output, brand, logo)
    typer.echo(f"Report written to {output}")
```

- [ ] **Step 4: Run all tests**

Run: `cd bin && uv run --with duckdb --with typer --with pyyaml --with jinja2 --with pyarrow --with pytest pytest test_benchmark_report.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add bin/benchmark_report.py bin/test_benchmark_report.py
git commit -m "✨ feat(benchmark): add report subcommand with DuckDB-backed queries"
```

---

## Task 4: Add `fetch` subcommand for standalone API access

**Files:**

- Modify: `bin/benchmark_report.py`
- Modify: `bin/test_benchmark_report.py`

This is the Python equivalent of `SeqeraApi.groovy` for agent/standalone use. The Nextflow pipeline does NOT use this — it uses the Groovy API client. This subcommand enables agents to fetch data without Nextflow.

- [ ] **Step 1: Write tests for fetch helpers**

```python
from unittest.mock import patch, MagicMock
from benchmark_report import fetch_run_data


class TestFetchRunData:
    @patch("benchmark_report.httpx")
    def test_fetches_4_endpoints(self, mock_httpx, tmp_path):
        mock_response = MagicMock()
        mock_response.json.return_value = {"workflow": {"id": "abc"}}
        mock_response.raise_for_status = MagicMock()
        mock_httpx.get.return_value = mock_response

        result = fetch_run_data("abc", "org/ws", "https://api.cloud.seqera.io", "fake-token")
        assert mock_httpx.get.call_count >= 4  # workflow, metrics, tasks, progress
        assert "workflow" in result
```

- [ ] **Step 2: Implement `fetch` subcommand**

```python
import httpx

def resolve_workspace_id(workspace: str, api_endpoint: str, headers: dict) -> int:
    org_name, ws_name = workspace.split("/")
    resp = httpx.get(f"{api_endpoint}/orgs", headers=headers)
    resp.raise_for_status()
    org_id = next(o["orgId"] for o in resp.json()["organizations"] if o["name"] == org_name)
    resp = httpx.get(f"{api_endpoint}/orgs/{org_id}/workspaces", headers=headers)
    resp.raise_for_status()
    return next(w["id"] for w in resp.json()["workspaces"] if w["name"] == ws_name)

def fetch_all_tasks(base_url: str, headers: dict) -> list[dict]:
    tasks, offset, page_size = [], 0, 100
    while True:
        sep = "&" if "?" in base_url else "?"
        resp = httpx.get(f"{base_url}{sep}max={page_size}&offset={offset}", headers=headers)
        resp.raise_for_status()
        page = resp.json().get("tasks", [])
        tasks.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return tasks

def fetch_run_data(run_id: str, workspace: str, api_endpoint: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    ws_id = resolve_workspace_id(workspace, api_endpoint, headers)
    base = f"{api_endpoint}/workflow/{run_id}?workspaceId={ws_id}"
    workflow = httpx.get(base, headers=headers).json()
    metrics = httpx.get(f"{api_endpoint}/workflow/{run_id}/metrics?workspaceId={ws_id}", headers=headers).json()
    tasks = fetch_all_tasks(f"{api_endpoint}/workflow/{run_id}/tasks?workspaceId={ws_id}", headers)
    progress = httpx.get(f"{api_endpoint}/workflow/{run_id}/progress?workspaceId={ws_id}", headers=headers).json()
    return {
        "workflow": workflow.get("workflow", workflow),
        "metrics": metrics.get("metrics", []),
        "tasks": tasks,
        "progress": progress.get("progress", {}),
    }

@app.command()
def fetch(
    run_ids: list[str] = typer.Option(..., help="Seqera Platform run IDs"),
    workspace: str = typer.Option(..., help="Workspace as org/name"),
    group: str = typer.Option("default", help="Group label for these runs"),
    api_endpoint: str = typer.Option("https://api.cloud.seqera.io", help="Seqera API endpoint"),
    output_dir: Path = typer.Option(Path("json_data"), help="Output directory for JSON files"),
) -> None:
    """Fetch run data from Seqera Platform API."""
    token = os.environ.get("TOWER_ACCESS_TOKEN", "")
    if not token:
        typer.echo("TOWER_ACCESS_TOKEN not set", err=True)
        raise typer.Exit(code=1)
    output_dir.mkdir(parents=True, exist_ok=True)
    for rid in run_ids:
        data = fetch_run_data(rid, workspace, api_endpoint, token)
        data["meta"] = {"id": rid, "workspace": workspace, "group": group}
        (output_dir / f"{rid}.json").write_text(json.dumps(data, default=str))
        typer.echo(f"Fetched {rid}")
```

- [ ] **Step 3: Run tests**

Run: `cd bin && uv run --with duckdb --with typer --with pyyaml --with jinja2 --with pyarrow --with httpx --with pytest pytest test_benchmark_report.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add bin/benchmark_report.py bin/test_benchmark_report.py
git commit -m "✨ feat(benchmark): add fetch subcommand for standalone API access"
```

---

## Task 5: Create Nextflow module and update workflow

**Files:**

- Create: `modules/local/benchmark_report/main.nf`
- Create: `modules/local/benchmark_report/nextflow.config`
- Modify: `workflows/nf_aggregate/main.nf`
- Modify: `workflows/nf_aggregate/nextflow.config`

- [ ] **Step 1: Create single Nextflow process module**

Create `modules/local/benchmark_report/main.nf`:

```nextflow
process BENCHMARK_REPORT {

    conda 'python=3.12 duckdb=1.3 jinja2=3.1 typer=0.15 pyarrow=18 pyyaml=6'
    container 'community.wave.seqera.io/library/python_duckdb_jinja2_typer_pruned:2d95e1e826bbe38f'

    input:
    path data_dir
    path benchmark_aws_cur_report
    path brand_yml
    path logo_svg

    output:
    path "benchmark_report.html", emit: html
    path "benchmark.duckdb",      emit: database
    path "versions.yml",          emit: versions

    script:
    def cost_flag = benchmark_aws_cur_report.name != 'NO_FILE' ? "--costs ${benchmark_aws_cur_report}" : ""
    def brand_flag = brand_yml.name != 'NO_FILE' ? "--brand ${brand_yml}" : ""
    def logo_flag = logo_svg.name != 'NO_FILE' ? "--logo ${logo_svg}" : ""
    """
    benchmark_report.py build-db \\
        --data-dir ${data_dir} \\
        ${cost_flag} \\
        --output benchmark.duckdb

    benchmark_report.py report \\
        --db benchmark.duckdb \\
        ${brand_flag} \\
        ${logo_flag} \\
        --output benchmark_report.html

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        duckdb: \$(python -c "import duckdb; print(duckdb.__version__)")
    END_VERSIONS
    """
}
```

- [ ] **Step 2: Create publishDir config**

Create `modules/local/benchmark_report/nextflow.config`:

```nextflow
process {
    withName: 'BENCHMARK_REPORT' {
        publishDir = [
            path: { "${params.outdir}/benchmark_report" },
            mode: 'copy',
            saveAs: { filename -> filename.equals('versions.yml') ? null : filename }
        ]
    }
}
```

- [ ] **Step 3: Update workflow to use single process**

Modify `workflows/nf_aggregate/main.nf`:

- Remove includes for `CLEAN_JSON`, `CLEAN_CUR`, `BUILD_TABLES`, `RENDER_REPORT`
- Add include for `BENCHMARK_REPORT`
- Replace the 4-step benchmark pipeline block (lines 82-142) with a single `BENCHMARK_REPORT` call:

```nextflow
if (params.generate_benchmark_report) {

    // Path A: Fetch run data via API for non-external runs
    ch_api_jsons = ch_split.api.map { meta ->
        def data = SeqeraApi.fetchRunData(meta, seqera_api_endpoint)
        data.meta = [id: meta.id, workspace: meta.workspace, group: meta.group ?: 'default']
        def json_file = file("${workDir}/run_data/${meta.id}.json")
        json_file.parent.mkdirs()
        json_file.text = toJson(data)
        return json_file
    }

    // Path B: Collect JSON files from extracted tarballs
    ch_tarball_jsons = EXTRACT_TARBALL.out.extracted.flatMap { meta, dir ->
        def jsons = []
        dir.eachFileMatch(~/.*\.json/) { jsons << it }
        return jsons
    }

    // Merge both paths into a single data directory
    ch_data_dir = ch_api_jsons
        .mix(ch_tarball_jsons)
        .collect()
        .map { files ->
            def dir = file("${workDir}/benchmark_data")
            dir.mkdirs()
            files.each { f -> f.copyTo(dir.resolve(f.name)) }
            return dir
        }

    ch_cur = params.benchmark_aws_cur_report
        ? Channel.fromPath(params.benchmark_aws_cur_report)
        : Channel.fromPath("${projectDir}/assets/NO_FILE", checkIfExists: false).ifEmpty(file("${projectDir}/assets/NO_FILE"))

    BENCHMARK_REPORT(
        ch_data_dir,
        ch_cur.ifEmpty(file("${projectDir}/assets/NO_FILE")),
        file("${projectDir}/assets/brand.yml", checkIfExists: true),
        file("${projectDir}/assets/seqera_logo_color.svg", checkIfExists: true),
    )
    ch_versions = ch_versions.mix(BENCHMARK_REPORT.out.versions)
}
```

- [ ] **Step 4: Update workflow nextflow.config**

Replace `render_report` include with `benchmark_report`:

```nextflow
includeConfig '../../modules/local/seqera_runs_dump/nextflow.config'
includeConfig '../../modules/local/plot_run_gantt/nextflow.config'
includeConfig '../../modules/local/benchmark_report/nextflow.config'
includeConfig '../../modules/nf-core/multiqc/nextflow.config'
```

- [ ] **Step 5: Commit**

```bash
git add modules/local/benchmark_report/ workflows/nf_aggregate/
git commit -m "♻️ refactor(pipeline): replace 4-process benchmark pipeline with single BENCHMARK_REPORT"
```

---

## Task 6: Delete old scripts and modules

**Files:**

- Delete: `bin/clean_json.py`, `bin/clean_cur.py`, `bin/build_tables.py`, `bin/render_report.py`
- Delete: `bin/test_clean_json.py`, `bin/test_clean_cur.py`, `bin/test_build_tables.py`, `bin/test_render_report.py`
- Delete: `modules/local/clean_json/` (entire directory)
- Delete: `modules/local/clean_cur/` (entire directory)
- Delete: `modules/local/build_tables/` (entire directory)
- Delete: `modules/local/render_report/` (entire directory)

- [ ] **Step 1: Run new tests to confirm everything works before deleting**

Run: `cd bin && uv run --with duckdb --with typer --with pyyaml --with jinja2 --with pyarrow --with httpx --with pytest pytest test_benchmark_report.py -v`
Expected: All PASS

- [ ] **Step 2: Delete old Python scripts**

```bash
rm bin/clean_json.py bin/clean_cur.py bin/build_tables.py bin/render_report.py
rm bin/test_clean_json.py bin/test_clean_cur.py bin/test_build_tables.py bin/test_render_report.py
```

- [ ] **Step 3: Delete old Nextflow modules**

```bash
rm -rf modules/local/clean_json modules/local/clean_cur modules/local/build_tables modules/local/render_report
```

- [ ] **Step 4: Verify no broken references**

```bash
grep -r "clean_json\|clean_cur\|build_tables\|render_report" --include="*.nf" --include="*.py" --include="*.config"
```

Expected: No matches (except possibly in docs/comments, which are handled in Task 7)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "🔥 remove(benchmark): delete old 4-script pipeline and modules"
```

---

## Task 7: Update documentation

**Files:**

- Modify: `docs/DESIGN.md`
- Modify: `AGENTS.md`
- Modify: `bin/AGENTS.md`

- [ ] **Step 1: Update `docs/DESIGN.md` architecture and CLI sections**

Replace the 4-step architecture diagram with:

```
API JSON files ──→ benchmark_report.py build-db ──→ benchmark.duckdb
                                                          │
                              ┌────────────────────────────┤
                              ▼                            ▼
              benchmark_report.py report        Agent queries DB
                              │                  (arbitrary SQL)
                              ▼
                  benchmark_report.html
```

Update CLI examples to use the new subcommands. Remove references to `clean_json.py`, `build_tables.py`, `render_report.py`. Update project structure tree.

- [ ] **Step 2: Update `AGENTS.md` architecture and rebuild commands**

Update architecture diagram and rebuild command to:

```bash
# Build DuckDB database from JSON data
uv run --with duckdb --with typer --with pyyaml --with pyarrow \
  python bin/benchmark_report.py build-db \
  --data-dir /path/to/json_data --output /tmp/benchmark.duckdb

# Render HTML report from database
uv run --with duckdb --with jinja2 --with typer --with pyyaml \
  python bin/benchmark_report.py report \
  --db /tmp/benchmark.duckdb --brand assets/brand.yml --output /tmp/report.html
```

- [ ] **Step 3: Update `bin/AGENTS.md` with new script documentation**

Replace the old per-script docs with documentation for `benchmark_report.py` subcommands.

- [ ] **Step 4: Commit**

```bash
git add docs/DESIGN.md AGENTS.md bin/AGENTS.md
git commit -m "📝 docs(benchmark): update architecture for unified benchmark_report.py"
```

---

## Task 8: Update nf-test snapshots

**Files:**

- Modify: `tests/default.nf.test`
- Modify: `tests/default.nf.test.snap`

- [ ] **Step 1: Run nf-test to regenerate snapshots**

The benchmark test profile should now produce `benchmark_report.html` and `benchmark.duckdb` instead of the old intermediate files. The snapshot needs updating.

```bash
nf-test test tests/default.nf.test --tag benchmark --update-snapshot
```

- [ ] **Step 2: Verify the snapshot contains expected outputs**

Check that the new snapshot includes:

- `benchmark_report/benchmark_report.html`
- `benchmark_report/benchmark.duckdb`
- No references to `cleaned/`, `tables/`, or intermediate CSVs

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "✅ test(benchmark): update nf-test snapshots for unified benchmark_report"
```

---

## Verification

After all tasks are complete:

1. **Unit tests pass:** `cd bin && uv run --with duckdb --with typer --with pyyaml --with jinja2 --with pyarrow --with httpx --with pytest pytest test_benchmark_report.py -v`
2. **No broken references:** `grep -r "clean_json\|clean_cur\|build_tables\|render_report" --include="*.nf" --include="*.py" --include="*.config"` returns nothing
3. **Nextflow lint passes:** `nextflow lint -harshil-alignment -format` on modified `.nf` files
4. **Standalone CLI works:**

   ```bash
   # Build DB from test fixtures
   uv run --with duckdb --with typer --with pyyaml --with pyarrow \
     python bin/benchmark_report.py build-db \
     --data-dir workflows/nf_aggregate/assets/logs/ --output /tmp/benchmark.duckdb

   # Render report
   uv run --with duckdb --with jinja2 --with typer --with pyyaml \
     python bin/benchmark_report.py report \
     --db /tmp/benchmark.duckdb --brand assets/brand.yml --output /tmp/report.html
   ```

5. **DuckDB queryable by agent:** `duckdb /tmp/benchmark.duckdb "SELECT * FROM runs"`
