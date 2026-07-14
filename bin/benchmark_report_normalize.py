#!/usr/bin/env python3
"""Normalize raw benchmark run JSON files into JSONL datasets."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

DEFAULT_COST_LABEL_ALIASES: dict[str, list[str]] = {
    # Workflow-identifying CUR resource labels, tried in order (first present wins).
    # These are the Seqera/Nextflow run tags `uniqueRunId` and `seqera.io/platform/workflowId`
    # AS THEY APPEAR IN A CUR EXPORT — AWS normalises user tag keys (prefix `user_`, non-alnum
    # -> `_`). Both hold the Seqera workflow id and are mutually exclusive per run (IC runs
    # carry the workflow-id tag, Batch runs the unique-run-id tag), so either resolves the
    # id that joins to run_summary.run_id. Shared by the Fusion and Intelligent Compute reports.
    "run_id": ["user_seqera_io_platform_workflow_id", "user_unique_run_id"],
    "process": ["user_pipeline_process"],
    "task_hash": ["user_task_hash"],
}


def _run_group(run: dict[str, Any]) -> str:
    return run["meta"]["group"]


def _run_workflow(run: dict[str, Any]) -> dict[str, Any]:
    return run["workflow"]


def _task_payload(task_raw: dict[str, Any]) -> dict[str, Any]:
    if isinstance(task_raw, dict) and "task" in task_raw:
        return task_raw["task"]
    return task_raw


def _val(d: dict[str, Any], key: str, default: int | float = 0) -> int | float:
    v = d.get(key)
    return v if v is not None else default


def _parse_timestamp(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _duration_ms(start: str | None, end: str | None) -> int:
    start_dt = _parse_timestamp(start)
    end_dt = _parse_timestamp(end)
    if not start_dt or not end_dt:
        return 0
    return max(0, int((end_dt - start_dt).total_seconds() * 1000))


def _compute_progress_from_tasks(run: dict[str, Any]) -> dict[str, Any]:
    tasks = [_task_payload(t) for t in run.get("tasks") or []]
    completed = [t for t in tasks if t.get("status") == "COMPLETED"]
    if not completed:
        return {}

    cpu_time = sum(_val(t, "cpus") * _val(t, "realtime") for t in completed)
    cpu_load = sum(_val(t, "pcpu") / 100.0 * _val(t, "realtime") for t in completed)
    mem_rss = sum(_val(t, "peakRss") if t.get("peakRss") is not None else _val(t, "rss") for t in completed)
    mem_req = sum(_val(t, "memory") for t in completed)

    return {
        "cpuTime": int(cpu_time),
        "cpuLoad": int(cpu_load),
        "cpuEfficiency": round(cpu_load / cpu_time * 100, 2) if cpu_time else None,
        "memoryRss": mem_rss,
        "memoryReq": mem_req,
        "memoryEfficiency": round(mem_rss / mem_req * 100, 2) if mem_req else None,
        "readBytes": sum(_val(t, "readBytes") for t in completed),
        "writeBytes": sum(_val(t, "writeBytes") for t in completed),
    }


def load_run_data(data_dir: Path) -> list[dict[str, Any]]:
    runs = []
    for run_file in sorted(data_dir.glob("*.json")):
        with run_file.open() as f:
            runs.append(json.load(f))
    return runs


def extract_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        wf = _run_workflow(run)
        prog = run.get("progress", {}).get("workflowProgress", {})
        if not prog:
            prog = _compute_progress_from_tasks(run)
        stats = wf.get("stats", {})
        launch = run.get("launch", {}) or {}
        ce = run.get("computeEnv", {}) or {}

        fusion_enabled = bool(wf.get("fusion", {}).get("enabled", False)) if wf.get("fusion") else False

        rows.append(
            {
                "run_id": wf["id"],
                "group": _run_group(run),
                "pipeline": wf.get("projectName") or wf.get("repository", "").split("/")[-1] or "unknown",
                "run_name": wf.get("runName", ""),
                "username": wf.get("userName", ""),
                "status": wf.get("status", ""),
                "start": wf.get("start"),
                "complete": wf.get("complete"),
                "duration_ms": wf.get("duration", 0),
                "succeeded": stats.get("succeedCount", 0),
                "failed": stats.get("failedCount", 0),
                "cached": stats.get("cachedCount", 0),
                "cpu_efficiency": prog.get("cpuEfficiency"),
                "memory_efficiency": prog.get("memoryEfficiency"),
                "cpu_time_ms": prog.get("cpuTime", 0),
                "read_bytes": prog.get("readBytes", 0),
                "write_bytes": prog.get("writeBytes", 0),
                "fusion_enabled": fusion_enabled,
                "wave_enabled": bool(wf.get("wave", {}).get("enabled", False)) if wf.get("wave") else False,
                "command_line": wf.get("commandLine", ""),
                "revision": wf.get("revision", ""),
                "container_engine": wf.get("containerEngine", ""),
                "nextflow_version": wf.get("nextflow", {}).get("version", "") if wf.get("nextflow") else "",
                "executor": ce.get("executor", wf.get("executor", "")),
                "region": ce.get("region", ""),
                "pipeline_version": wf.get("revision", ""),
                "platform_version": launch.get("platformVersion", ""),
                "workspace": run.get("meta", {}).get("workspace", ""),
                "platform": run.get("meta", {}).get("platform", ""),
                "run_url": wf.get("runUrl") or wf.get("url") or "",
                "memory_rss_bytes": prog.get("memoryRss", 0),
                "peak_memory_bytes": prog.get("peakMemory", 0),
                "run_cost": prog.get("cost"),
                "sched_enabled": bool(run.get("schedEnabled", False)),
                "platform_id": (run.get("platform") or {}).get("id", ""),
            }
        )
    return rows


def extract_tasks(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        run_id = _run_workflow(run)["id"]
        group = _run_group(run)
        for raw in run.get("tasks", []):
            task = _task_payload(raw)
            status = task.get("status", "")
            if status not in {"COMPLETED", "CACHED"}:
                continue

            process = task.get("process", "")
            process_short = process.split(":")[-1] if process else ""
            realtime_ms = task.get("realtime", 0) or 0
            wait_ms = _duration_ms(task.get("submit"), task.get("start"))
            staging_ms = max(0, _duration_ms(task.get("start"), task.get("complete")) - int(realtime_ms))

            rows.append(
                {
                    "run_id": run_id,
                    "group": group,
                    "hash": task.get("hash", ""),
                    "name": task.get("name", ""),
                    "process": process,
                    "process_short": process_short,
                    "tag": task.get("tag"),
                    "status": status,
                    "submit": task.get("submit"),
                    "start": task.get("start"),
                    "complete": task.get("complete"),
                    "duration_ms": task.get("duration", 0),
                    "realtime_ms": realtime_ms,
                    "wait_ms": wait_ms,
                    "staging_ms": staging_ms,
                    "cpus": task.get("cpus", 0),
                    "memory_bytes": task.get("memory", 0),
                    "pcpu": task.get("pcpu", 0),
                    "pmem": task.get("pmem", 0),
                    "rss": task.get("rss", 0),
                    "peak_rss": task.get("peakRss", 0),
                    "read_bytes": task.get("readBytes", 0),
                    "write_bytes": task.get("writeBytes", 0),
                    "cost": None,
                    "executor": task.get("executor", ""),
                    "machine_type": task.get("machineType", ""),
                    "cloud_zone": task.get("cloudZone", ""),
                    "exit_status": task.get("exitStatus"),
                    "vol_ctxt": task.get("volCtxt", 0),
                    "inv_ctxt": task.get("invCtxt", 0),
                }
            )
    return rows


def extract_metrics(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        run_id = _run_workflow(run)["id"]
        group = _run_group(run)
        for metric in run.get("metrics", []):
            row: dict[str, Any] = {
                "run_id": run_id,
                "group": group,
                "process": metric.get("process", ""),
            }
            for field in ["cpu", "mem", "vmem", "time", "reads", "writes", "cpuUsage", "memUsage", "timeUsage"]:
                data = metric.get(field, {}) or {}
                for stat in ["mean", "min", "q1", "q2", "q3", "max"]:
                    row[f"{field}_{stat}"] = data.get(stat)
            rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, default=str))
            f.write("\n")


def _duckdb_connect():
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - only hit without duckdb installed
        raise RuntimeError("duckdb is required to normalize CUR parquet") from exc
    return duckdb.connect()


def _parquet_sources(costs_parquet: Path) -> list[str]:
    """Resolve a file or directory into the parquet files DuckDB should scan.

    A directory is expanded to every ``*.parquet`` beneath it so a whole CUR
    export folder can be processed in one pass.
    """
    if costs_parquet.is_dir():
        return sorted(str(path) for path in costs_parquet.rglob("*.parquet"))
    return [str(costs_parquet)]


def _sql_string_array(values: list[str]) -> str:
    return "[" + ", ".join("'" + value.replace("'", "''") + "'" for value in values) + "]"


def _tag_extract_expr(resource_tags_type: str, alias: str) -> str | None:
    """SQL that reads tag ``alias`` out of a ``resource_tags`` column.

    CUR data stores labels in one of three shapes, distinguished by the column's
    DuckDB type: a ``MAP``, a v2 list of ``{key, value}`` structs
    (``STRUCT(...)[]``) or a list of ``[key, value]`` string lists
    (``VARCHAR[][]``). Returns ``None`` for any other shape so the caller falls
    back to the flattened ``resource_tags_<alias>`` columns only.
    """
    escaped = alias.replace("'", "''")
    normalized = resource_tags_type.upper().strip()
    if normalized.startswith("MAP"):
        return f"resource_tags['{escaped}']"
    if "STRUCT" in normalized and normalized.endswith("[]"):
        return f"list_filter(resource_tags, x -> x.key = '{escaped}')[1].value"
    if normalized.endswith("[][]"):
        return f"list_filter(resource_tags, x -> x[1] = '{escaped}')[1][2]"
    return None


def _label_expr(aliases: list[str], columns: dict[str, str]) -> str:
    """COALESCE expression resolving a label across its aliases.

    Each alias is tried as a flattened ``resource_tags_<alias>`` column first and
    then inside the ``resource_tags`` map/struct column, matching the original
    per-alias (flat, then map) resolution order. Empty strings are treated as
    missing so precedence falls through to the next candidate.
    """
    parts: list[str] = []
    resource_tags_type = columns.get("resource_tags")
    for alias in aliases:
        flat_column = f"resource_tags_{alias}"
        if flat_column in columns:
            parts.append(f"NULLIF(CAST(\"{flat_column}\" AS VARCHAR), '')")
        if resource_tags_type is not None:
            expr = _tag_extract_expr(resource_tags_type, alias)
            if expr is not None:
                parts.append(f"NULLIF(CAST({expr} AS VARCHAR), '')")
    if not parts:
        return "NULL"
    if len(parts) == 1:
        return parts[0]
    return "COALESCE(" + ", ".join(parts) + ")"


def _numeric_expr(column: str, columns: dict[str, str]) -> str:
    if column in columns:
        return f"COALESCE(CAST(\"{column}\" AS DOUBLE), 0.0)"
    return "0.0"


def _dedupe_aliases(values: list[str]) -> list[str]:
    seen: set[str] = set()
    aliases: list[str] = []
    for value in values:
        alias = str(value).strip()
        if not alias or alias in seen:
            continue
        seen.add(alias)
        aliases.append(alias)
    return aliases


def _normalise_label_aliases(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _dedupe_aliases([value])
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise ValueError(f"benchmark_aws_cur_label_map field '{field}' must contain only strings")
        return _dedupe_aliases(value)
    raise ValueError(f"benchmark_aws_cur_label_map field '{field}' must be a string or list of strings")


def _load_cost_label_aliases(cost_label_map: Path | None = None) -> dict[str, list[str]]:
    aliases = {field: list(defaults) for field, defaults in DEFAULT_COST_LABEL_ALIASES.items()}
    if cost_label_map is None or cost_label_map.name in {"NO_FILE", "NO_FILE_CUR_LABEL_MAP"}:
        return aliases

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("pyyaml is required to read benchmark_aws_cur_label_map") from exc

    with cost_label_map.open() as handle:
        raw_config = yaml.safe_load(handle) or {}

    if not isinstance(raw_config, dict):
        raise ValueError("benchmark_aws_cur_label_map must contain a YAML mapping")

    unknown_fields = set(raw_config) - set(DEFAULT_COST_LABEL_ALIASES)
    if unknown_fields:
        unknown_fields_csv = ", ".join(sorted(unknown_fields))
        raise ValueError(f"benchmark_aws_cur_label_map contains unsupported fields: {unknown_fields_csv}")

    for field, defaults in DEFAULT_COST_LABEL_ALIASES.items():
        user_aliases = _normalise_label_aliases(raw_config.get(field), field)
        aliases[field] = _dedupe_aliases(user_aliases + defaults)

    return aliases


def _normalize_cost_rows(costs_parquet: Path, cost_label_map: Path | None = None) -> list[dict[str, Any]]:
    """Aggregate per run/process/task costs from one or more CUR parquet files.

    DuckDB does the heavy lifting: it prunes to the handful of columns we need,
    reads an entire folder of parquet files in one scan (``union_by_name``
    reconciles differing CUR schemas), keeps only rows carrying a run-id resource
    label and sums the costs with a single vectorized GROUP BY. Far faster than
    iterating a multi-GB, hundreds-of-columns export row by row in Python.
    """
    label_aliases = _load_cost_label_aliases(cost_label_map)
    sources = _parquet_sources(costs_parquet)
    if not sources:
        return []

    connection = _duckdb_connect()
    scan = f"read_parquet({_sql_string_array(sources)}, union_by_name=true)"

    columns = {
        name: column_type
        for name, column_type, *_ in connection.execute(f"DESCRIBE SELECT * FROM {scan}").fetchall()
    }

    run_id_expr = _label_expr(label_aliases["run_id"], columns)
    process_expr = _label_expr(label_aliases["process"], columns)
    task_hash_expr = _label_expr(label_aliases["task_hash"], columns)

    # Split line items (shared instances, e.g. Fusion / Intelligent Compute) carry
    # cost in split_line_item_split_cost with line_item_unblended_cost zeroed; normal
    # usage rows (e.g. dedicated Batch instances) are the reverse. A split cost of 0
    # therefore means "fall back to unblended".
    split_cost = _numeric_expr("split_line_item_split_cost", columns)
    unblended_cost = _numeric_expr("line_item_unblended_cost", columns)
    used_cost = f"CASE WHEN {split_cost} <> 0 THEN {split_cost} ELSE {unblended_cost} END"
    unused_cost = _numeric_expr("split_line_item_unused_cost", columns)

    query = f"""
        SELECT
            {run_id_expr}                                 AS run_id,
            COALESCE({process_expr}, '')                  AS process,
            substr(COALESCE({task_hash_expr}, ''), 1, 8)  AS hash,
            SUM(({used_cost}) + ({unused_cost}))          AS cost,
            SUM({used_cost})                              AS used_cost,
            SUM({unused_cost})                            AS unused_cost
        FROM {scan}
        WHERE {run_id_expr} IS NOT NULL AND {run_id_expr} <> ''
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    """
    rows = connection.execute(query).fetchall()
    names = [description[0] for description in connection.description]
    return [dict(zip(names, row)) for row in rows]


def _safe_float(val: Any) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _parse_machine_percent(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().rstrip("%")
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _summarise_machines(machines_dir: Path) -> list[dict[str, Any]]:
    """Parse machine CSVs and produce per-run VM metrics summaries."""
    import csv

    all_rows: list[dict[str, str]] = []
    for csv_path in sorted(machines_dir.glob("*.csv")):
        with csv_path.open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                all_rows.append(row)

    if not all_rows:
        return []

    has_scheduler = any(
        r.get("instance_id") and str(r["instance_id"]).strip()
        for r in all_rows
    )
    has_batch = any(
        r.get("ecs_instance_id") and str(r["ecs_instance_id"]).strip()
        for r in all_rows
    )

    run_acc: dict[str, dict[str, Any]] = {}

    if has_scheduler:
        for r in all_rows:
            iid = (r.get("instance_id") or "").strip()
            if not iid:
                continue
            run_id = str(r.get("run_id", "")).strip()
            if not run_id:
                continue
            vcpus = _safe_float(r.get("vcpus"))
            mem_gib = _safe_float(r.get("memory_gib"))
            hours = _safe_float(r.get("machine_hours"))
            cpu_util = _parse_machine_percent(r.get("avg_cpu_utilization"))
            mem_util = _parse_machine_percent(r.get("avg_memory_utilization"))

            if run_id not in run_acc:
                run_acc[run_id] = {
                    "n_machines": 0,
                    "vm_cpu_h": 0.0,
                    "vm_mem_gib_h": 0.0,
                    "weighted_cpu_util": 0.0,
                    "weighted_mem_util": 0.0,
                    "cpu_weight": 0.0,
                    "mem_weight": 0.0,
                }

            acc = run_acc[run_id]
            acc["n_machines"] += 1
            cpu_h = vcpus * hours
            mem_gib_h = mem_gib * hours
            acc["vm_cpu_h"] += cpu_h
            acc["vm_mem_gib_h"] += mem_gib_h
            acc["weighted_cpu_util"] += cpu_util * cpu_h
            acc["cpu_weight"] += cpu_h
            acc["weighted_mem_util"] += mem_util * mem_gib_h
            acc["mem_weight"] += mem_gib_h

    if has_batch:
        for r in all_rows:
            eid = (r.get("ecs_instance_id") or "").strip()
            if not eid:
                continue
            run_id = str(r.get("run_id", "")).strip()
            if not run_id:
                continue

            vm_cpu_h = _safe_float(r.get("total_vcpu_hours"))
            vm_mem_gib_h = _safe_float(r.get("total_memory_gib_hours"))
            req_cpu_h = _safe_float(r.get("total_requested_vcpu_hours")) or _safe_float(r.get("requested_vcpu_hours"))
            req_mem_gib_h = _safe_float(r.get("total_requested_memory_gib_hours")) or _safe_float(r.get("requested_memory_gib_hours"))

            if run_id not in run_acc:
                run_acc[run_id] = {
                    "n_machines": 0,
                    "vm_cpu_h": 0.0,
                    "vm_mem_gib_h": 0.0,
                    "weighted_cpu_util": 0.0,
                    "weighted_mem_util": 0.0,
                    "cpu_weight": 0.0,
                    "mem_weight": 0.0,
                    "batch_req_cpu_h": 0.0,
                    "batch_req_mem_gib_h": 0.0,
                }

            acc = run_acc[run_id]
            acc["n_machines"] += 1
            acc["vm_cpu_h"] += vm_cpu_h
            acc["vm_mem_gib_h"] += vm_mem_gib_h
            acc.setdefault("batch_req_cpu_h", 0.0)
            acc.setdefault("batch_req_mem_gib_h", 0.0)
            acc["batch_req_cpu_h"] += req_cpu_h
            acc["batch_req_mem_gib_h"] += req_mem_gib_h

    results = []
    for run_id, acc in run_acc.items():
        vm_cpu_h = acc["vm_cpu_h"]
        vm_mem_gib_h = acc["vm_mem_gib_h"]
        cpu_weight = acc.get("cpu_weight", 0.0)
        mem_weight = acc.get("mem_weight", 0.0)

        sched_cpu_eff = (acc["weighted_cpu_util"] / cpu_weight) if cpu_weight > 0 else None
        sched_mem_eff = (acc["weighted_mem_util"] / mem_weight) if mem_weight > 0 else None

        # For batch runs, compute efficiency from requested/vm
        if "batch_req_cpu_h" in acc:
            batch_req_cpu = acc["batch_req_cpu_h"]
            batch_req_mem = acc["batch_req_mem_gib_h"]
            if sched_cpu_eff is None and vm_cpu_h > 0:
                sched_cpu_eff = (batch_req_cpu / vm_cpu_h) * 100
            if sched_mem_eff is None and vm_mem_gib_h > 0:
                sched_mem_eff = (batch_req_mem / vm_mem_gib_h) * 100

        results.append({
            "run_id": run_id,
            "n_machines": acc["n_machines"],
            "vm_cpu_h": round(vm_cpu_h, 4),
            "vm_mem_gib_h": round(vm_mem_gib_h, 4),
            "sched_alloc_cpu_efficiency": round(sched_cpu_eff, 2) if sched_cpu_eff is not None else None,
            "sched_alloc_mem_efficiency": round(sched_mem_eff, 2) if sched_mem_eff is not None else None,
        })
    return results


def normalize_jsonl(
    data_dir: Path,
    output_dir: Path,
    costs_parquet: Path | None = None,
    machines_dir: Path | None = None,
    cost_label_map: Path | None = None,
) -> None:
    runs = load_run_data(data_dir)
    if not runs:
        typer.echo("No run data found", err=True)
        raise typer.Exit(code=1)

    output_dir.mkdir(parents=True, exist_ok=True)

    run_rows = extract_runs(runs)
    task_rows = extract_tasks(runs)
    metric_rows = extract_metrics(runs)

    _write_jsonl(output_dir / "runs.jsonl", run_rows)
    _write_jsonl(output_dir / "tasks.jsonl", task_rows)
    _write_jsonl(output_dir / "metrics.jsonl", metric_rows)

    if costs_parquet and costs_parquet.exists() and costs_parquet.name != "NO_FILE":
        cost_rows = _normalize_cost_rows(costs_parquet, cost_label_map=cost_label_map)
        _write_jsonl(output_dir / "costs.jsonl", cost_rows)

    if machines_dir and machines_dir.exists() and any(machines_dir.glob("*.csv")):
        machine_rows = _summarise_machines(machines_dir)
        if machine_rows:
            _write_jsonl(output_dir / "machines.jsonl", machine_rows)

    typer.echo(f"JSONL bundle written to {output_dir}")
