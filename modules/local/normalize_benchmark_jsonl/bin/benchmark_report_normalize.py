#!/usr/bin/env python3
"""Normalize raw benchmark run JSON files into JSONL datasets."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import typer


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
                    "cost": task.get("cost"),
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


def _to_tags_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        tags = {}
        for item in value:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                tags[str(item[0])] = item[1]
        return tags
    return {}


def _iter_parquet_rows(costs_parquet: Path):
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required to normalize CUR parquet") from exc

    parquet_file = pq.ParquetFile(costs_parquet)
    cols = set(parquet_file.schema_arrow.names)

    for batch in parquet_file.iter_batches():
        for row in batch.to_pylist():
            yield cols, row


def _normalize_cost_rows(costs_parquet: Path) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, float | str]] = {}
    is_map: bool | None = None

    for cols, row in _iter_parquet_rows(costs_parquet):
        if is_map is None:
            is_map = "resource_tags" in cols and "resource_tags_user_unique_run_id" not in cols
        if is_map:
            tags = _to_tags_dict(row.get("resource_tags"))
            run_id = tags.get("user_unique_run_id") or tags.get("user_nf_unique_run_id")
            process = tags.get("user_pipeline_process")
            hash_val = tags.get("user_task_hash")
        else:
            run_id = row.get("resource_tags_user_unique_run_id") or row.get("resource_tags_user_nf_unique_run_id")
            process = row.get("resource_tags_user_pipeline_process")
            hash_val = row.get("resource_tags_user_task_hash")

        if not run_id:
            continue

        used = row.get("split_line_item_split_cost")
        if used is None:
            used = row.get("line_item_unblended_cost")
        used = float(used or 0.0)
        unused = float(row.get("split_line_item_unused_cost") or 0.0)
        total = used + unused

        hash_short = str(hash_val or "")[:8]
        key = (str(run_id), str(process or ""), hash_short)

        if key not in grouped:
            grouped[key] = {
                "run_id": key[0],
                "process": key[1],
                "hash": key[2],
                "cost": 0.0,
                "used_cost": 0.0,
                "unused_cost": 0.0,
            }

        grouped[key]["cost"] = float(grouped[key]["cost"]) + total
        grouped[key]["used_cost"] = float(grouped[key]["used_cost"]) + used
        grouped[key]["unused_cost"] = float(grouped[key]["unused_cost"]) + unused

    return list(grouped.values())


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


def normalize_jsonl(data_dir: Path, output_dir: Path, costs_parquet: Path | None = None, machines_dir: Path | None = None) -> None:
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
        cost_rows = _normalize_cost_rows(costs_parquet)
        _write_jsonl(output_dir / "costs.jsonl", cost_rows)

    if machines_dir and machines_dir.exists() and any(machines_dir.glob("*.csv")):
        machine_rows = _summarise_machines(machines_dir)
        if machine_rows:
            _write_jsonl(output_dir / "machines.jsonl", machine_rows)

    typer.echo(f"JSONL bundle written to {output_dir}")
