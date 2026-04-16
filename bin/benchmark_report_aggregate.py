#!/usr/bin/env python3
"""Aggregate benchmark JSONL datasets into report_data.json."""

from __future__ import annotations

import json
from collections import defaultdict
from math import sqrt
from pathlib import Path
from typing import Any, Iterator

_HIGHLIGHT_KEYWORDS = ("qc", "qualimap", "multiqc", "rseqc", "dupradar")


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return

    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _sample_stddev(n: int, total: float, total_sq: float) -> float | None:
    if n < 2:
        return None

    variance = (total_sq - (total * total) / n) / (n - 1)
    if variance < 0:
        variance = 0
    return sqrt(variance)


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _norm_hash(task_hash: str | None) -> str:
    return (task_hash or "").replace("/", "")[:8]


def _cost_key(run_id: str, process: str, hash_short: str) -> tuple[str, str, str]:
    return (run_id, process, hash_short)


def _lookup_cost(
    costs_index: dict[tuple[str, str, str], dict[str, Any]],
    run_id: str,
    process: str,
    process_short: str,
    hash_short: str,
) -> dict[str, Any] | None:
    for process_key in (process, process_short, ""):
        row = costs_index.get(_cost_key(run_id, process_key, hash_short))
        if row:
            return row
    return None


def _cost_or_task(cost_row: dict[str, Any] | None, key: str, task_cost: float, default: float = 0.0) -> float:
    if not cost_row:
        return task_cost if key in {"cost", "used_cost"} else default

    value = cost_row.get(key)
    if value is None:
        return task_cost if key in {"cost", "used_cost"} else default

    return float(value)


def _is_highlight_process(process: str) -> bool:
    process_lc = process.lower()
    return any(keyword in process_lc for keyword in _HIGHLIGHT_KEYWORDS)


def _classify_workflow_status(status: str | None) -> tuple[str, str, bool]:
    normalized = (status or "").strip().upper()
    if normalized in {"FAILED", "ERROR", "FAILING"}:
        return ("Failed", "failed", False)
    if normalized in {"CANCELLED", "CANCELED", "ABORTED", "ABORT", "STOPPED"}:
        return ("Cancelled", "cancelled", False)
    if normalized in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
        return ("Succeeded", "success", True)
    if not normalized:
        return ("Unknown", "unknown", True)
    return (normalized.title(), "other", True)


def build_report_data(jsonl_dir: Path) -> dict[str, Any]:
    benchmark_overview: list[dict[str, Any]] = []
    run_summary: list[dict[str, Any]] = []
    run_metrics: list[dict[str, Any]] = []

    run_cost_acc: dict[tuple[str, str], dict[str, Any]] = {}
    run_pipeline: dict[str, str] = {}
    included_run_ids: set[str] = set()

    for r in _iter_jsonl(jsonl_dir / "runs.jsonl"):
        run_id = str(r.get("run_id", ""))
        group = str(r.get("group", ""))
        run_pipeline[run_id] = str(r.get("pipeline") or "unknown")
        status_label, status_category, report_included = _classify_workflow_status(r.get("status"))

        benchmark_overview.append(
            {
                "pipeline": r.get("pipeline"),
                "group": group,
                "run_id": run_id,
                "status": r.get("status"),
                "status_label": status_label,
                "status_category": status_category,
                "report_included": report_included,
            }
        )

        if not report_included:
            continue

        included_run_ids.add(run_id)

        run_summary.append(
            {
                "pipeline": r.get("pipeline"),
                "group": group,
                "run_id": run_id,
                "username": r.get("username"),
                "status": r.get("status"),
                "status_label": status_label,
                "status_category": status_category,
                "report_included": report_included,
                "Version": r.get("pipeline_version"),
                "Nextflow_version": r.get("nextflow_version"),
                "platform_version": r.get("platform_version"),
                "succeedCount": r.get("succeeded", 0),
                "failedCount": r.get("failed", 0),
                "cachedCount": r.get("cached", 0),
                "executor": r.get("executor"),
                "region": r.get("region"),
                "fusion_enabled": r.get("fusion_enabled", False),
                "wave_enabled": r.get("wave_enabled", False),
                "container_engine": r.get("container_engine"),
            }
        )

        run_metrics.append(
            {
                "pipeline": r.get("pipeline"),
                "group": group,
                "run_id": run_id,
                "duration": int(r.get("duration_ms") or 0),
                "cpuTime": _round((float(r.get("cpu_time_ms") or 0) / 1000.0) / 3600.0, 1),
                "pipeline_runtime": int(r.get("cpu_time_ms") or 0),
                "cpuEfficiency": _round(float(r.get("cpu_efficiency")) if r.get("cpu_efficiency") is not None else None, 0),
                "memoryEfficiency": _round(float(r.get("memory_efficiency")) if r.get("memory_efficiency") is not None else None, 2),
                "readBytes": _round(float(r.get("read_bytes") or 0) / 1e9, 0),
                "writeBytes": _round(float(r.get("write_bytes") or 0) / 1e9, 0),
            }
        )

        key = (run_id, group)
        run_cost_acc[key] = {
            "run_id": key[0],
            "group": key[1],
            "cost": 0.0,
            "used_cost": 0.0,
            "unused_cost": 0.0,
        }

    costs_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    has_cost_rows = False
    for c in _iter_jsonl(jsonl_dir / "costs.jsonl"):
        has_cost_rows = True
        run_id = str(c.get("run_id", ""))
        process = str(c.get("process", ""))
        hash_short = str(c.get("hash", ""))

        key = _cost_key(run_id, process, hash_short)
        if key not in costs_index:
            costs_index[key] = {
                "cost": 0.0,
                "used_cost": 0.0,
                "unused_cost": 0.0,
            }

        costs_index[key]["cost"] += float(c.get("cost") or 0.0)
        costs_index[key]["used_cost"] += float(c.get("used_cost") or 0.0)
        costs_index[key]["unused_cost"] += float(c.get("unused_cost") or 0.0)

    process_acc: dict[tuple[str, str, str], dict[str, float | int | str]] = defaultdict(
        lambda: {
            "n_tasks": 0,
            "staging_sum": 0.0,
            "staging_sum_sq": 0.0,
            "realtime_sum": 0.0,
            "realtime_sum_sq": 0.0,
            "runtime_sum": 0.0,
            "runtime_sum_sq": 0.0,
            "cost_sum": 0.0,
            "cost_sum_sq": 0.0,
        }
    )

    instance_groups: dict[tuple[str, str], int] = defaultdict(int)
    task_table: list[dict[str, Any]] = []
    task_scatter: list[dict[str, Any]] = []

    cost_group_acc: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"total_cost": 0.0, "used_cost": 0.0, "unused_cost": 0.0, "n_tasks": 0}
    )
    combined_runtime_acc: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"process_runtime_ms": defaultdict(int), "total_tasks": 0, "scheduling_runtime_ms": 0}
    )

    for t in _iter_jsonl(jsonl_dir / "tasks.jsonl"):
        run_id = str(t.get("run_id", ""))
        if run_id not in included_run_ids:
            continue

        group = str(t.get("group", ""))
        process = str(t.get("process", ""))
        process_short = str(t.get("process_short", ""))
        hash_short = _norm_hash(t.get("hash"))

        run_group_key = (run_id, group)
        if run_group_key not in run_cost_acc:
            run_cost_acc[run_group_key] = {
                "run_id": run_id,
                "group": group,
                "cost": 0.0,
                "used_cost": 0.0,
                "unused_cost": 0.0,
            }

        cost_row = _lookup_cost(costs_index, run_id=run_id, process=process, process_short=process_short, hash_short=hash_short)
        task_cost = float(t.get("cost") or 0.0)

        if cost_row:
            run_cost_acc[run_group_key]["cost"] += _cost_or_task(cost_row, "cost", task_cost)
            run_cost_acc[run_group_key]["used_cost"] += _cost_or_task(cost_row, "used_cost", task_cost)
            run_cost_acc[run_group_key]["unused_cost"] += _cost_or_task(cost_row, "unused_cost", task_cost, default=0.0)
        else:
            run_cost_acc[run_group_key]["cost"] += task_cost
            run_cost_acc[run_group_key]["used_cost"] += task_cost

        if has_cost_rows:
            overview_key = (group, process_short)
            cost_group_acc[overview_key]["total_cost"] += _cost_or_task(cost_row, "cost", task_cost)
            cost_group_acc[overview_key]["used_cost"] += _cost_or_task(cost_row, "used_cost", task_cost)
            cost_group_acc[overview_key]["unused_cost"] += _cost_or_task(cost_row, "unused_cost", task_cost, default=0.0)
            cost_group_acc[overview_key]["n_tasks"] += 1

        status = t.get("status")
        if status in {"COMPLETED", "CACHED"}:
            task_table.append(
                {
                    "Group": t.get("group"),
                    "Run ID": t.get("run_id"),
                    "Taskhash": str(t.get("hash") or "")[:9],
                    "Task name short": t.get("process_short"),
                    "Executor": t.get("executor"),
                    "Cloudzone": t.get("cloud_zone"),
                    "Instance type": t.get("machine_type"),
                    "Realtime_min": float(t.get("realtime_ms") or 0) / 60000.0,
                    "Realtime_ms": t.get("realtime_ms"),
                    "Duration_ms": t.get("duration_ms"),
                    "Cost": float(t.get("cost") or 0),
                    "CPUused": t.get("cpus"),
                    "Memoryused_GB": _round(float(t.get("memory_bytes") or 0) / 1e9, 0),
                    "Pcpu": t.get("pcpu"),
                    "Pmem": t.get("pmem"),
                    "Rss": t.get("rss"),
                    "Readbytes": t.get("read_bytes"),
                    "Writebytes": t.get("write_bytes"),
                    "VolCtxt": t.get("vol_ctxt"),
                    "InvCtxt": t.get("inv_ctxt"),
                    "Task name": t.get("name"),
                    "Status": status,
                }
            )

            task_scatter.append(
                {
                    "run_id": t.get("run_id"),
                    "group": t.get("group"),
                    "process_short": t.get("process_short"),
                    "name": t.get("name"),
                    "realtime_min": float(t.get("realtime_ms") or 0) / 60000.0,
                    "staging_min": float(t.get("staging_ms") or 0) / 60000.0,
                    "cost": float(t.get("cost") or 0),
                    "cpus": t.get("cpus"),
                    "memory_gb": float(t.get("memory_bytes") or 0) / 1e9,
                }
            )

        if status != "COMPLETED":
            continue

        pipeline = run_pipeline.get(run_id, "unknown")
        runtime_panel_key = (pipeline, group)
        panel_acc = combined_runtime_acc[runtime_panel_key]
        process_name = process or process_short or "unknown"
        panel_acc["process_runtime_ms"][process_name] += int(t.get("realtime_ms") or 0)
        panel_acc["scheduling_runtime_ms"] += int(t.get("wait_ms") or 0)
        panel_acc["total_tasks"] += 1

        process_key = (group, process, process_short)
        acc = process_acc[process_key]
        acc["n_tasks"] = int(acc["n_tasks"]) + 1

        staging = float(t.get("staging_ms") or 0) / 60000.0
        realtime = float(t.get("realtime_ms") or 0) / 60000.0
        runtime = float(t.get("duration_ms") or 0) / 60000.0
        cost_value = float(t.get("cost") or 0)

        acc["staging_sum"] = float(acc["staging_sum"]) + staging
        acc["staging_sum_sq"] = float(acc["staging_sum_sq"]) + staging * staging
        acc["realtime_sum"] = float(acc["realtime_sum"]) + realtime
        acc["realtime_sum_sq"] = float(acc["realtime_sum_sq"]) + realtime * realtime
        acc["runtime_sum"] = float(acc["runtime_sum"]) + runtime
        acc["runtime_sum_sq"] = float(acc["runtime_sum_sq"]) + runtime * runtime
        acc["cost_sum"] = float(acc["cost_sum"]) + cost_value
        acc["cost_sum_sq"] = float(acc["cost_sum_sq"]) + cost_value * cost_value

        machine_type = t.get("machine_type")
        if machine_type:
            instance_groups[(group, str(machine_type))] += 1

    benchmark_overview.sort(key=lambda x: (str(x.get("pipeline", "")), str(x.get("group", ""))))
    run_summary.sort(key=lambda x: str(x.get("group", "")))
    run_metrics.sort(key=lambda x: str(x.get("group", "")))

    run_costs = sorted(
        [
            {
                "run_id": row["run_id"],
                "group": row["group"],
                "cost": _round(row["cost"], 2),
                "used_cost": _round(row["used_cost"], 2) if has_cost_rows else None,
                "unused_cost": _round(row["unused_cost"], 2) if has_cost_rows else None,
            }
            for row in run_cost_acc.values()
        ],
        key=lambda x: str(x.get("group", "")),
    )

    process_stats = []
    for (group, process, process_short), acc in process_acc.items():
        n = int(acc["n_tasks"])
        staging_sum = float(acc["staging_sum"])
        realtime_sum = float(acc["realtime_sum"])
        runtime_sum = float(acc["runtime_sum"])
        cost_sum = float(acc["cost_sum"])

        process_stats.append(
            {
                "group": group,
                "process_name": process,
                "process_short": process_short,
                "n_tasks": n,
                "avg_staging_min": staging_sum / n,
                "sd_staging_min": _sample_stddev(n, staging_sum, float(acc["staging_sum_sq"])),
                "avg_realtime_min": realtime_sum / n,
                "sd_realtime_min": _sample_stddev(n, realtime_sum, float(acc["realtime_sum_sq"])),
                "avg_runtime_min": runtime_sum / n,
                "sd_runtime_min": _sample_stddev(n, runtime_sum, float(acc["runtime_sum_sq"])),
                "avg_cost": cost_sum / n,
                "sd_cost": _sample_stddev(n, cost_sum, float(acc["cost_sum_sq"])),
                "total_cost": cost_sum,
            }
        )
    process_stats.sort(key=lambda x: float(x.get("avg_runtime_min") or 0), reverse=True)

    task_instance_usage = [
        {"group": g, "machine_type": mt, "count": c}
        for (g, mt), c in sorted(instance_groups.items(), key=lambda x: (x[0][0], -x[1]))
    ]

    task_table.sort(key=lambda x: (str(x.get("Group", "")), str(x.get("Task name short", "")), str(x.get("Task name", ""))))
    task_scatter.sort(key=lambda x: str(x.get("process_short", "")))

    cost_overview = None
    if has_cost_rows:
        cost_overview = [
            {
                "group": group,
                "process_short": process_short,
                "total_cost": vals["total_cost"],
                "used_cost": vals["used_cost"],
                "unused_cost": vals["unused_cost"],
                "n_tasks": vals["n_tasks"],
            }
            for (group, process_short), vals in cost_group_acc.items()
        ]
        cost_overview.sort(key=lambda x: float(x.get("total_cost") or 0), reverse=True)

    combined_task_runtime = []
    for (pipeline, group), panel_acc in sorted(combined_runtime_acc.items(), key=lambda x: (x[0][0], x[0][1])):
        process_runtime_ms = panel_acc["process_runtime_ms"]
        sorted_processes = sorted(process_runtime_ms.items(), key=lambda x: (-x[1], x[0]))
        total_runtime_ms = sum(runtime for _, runtime in sorted_processes)
        if total_runtime_ms <= 0:
            continue
        scheduling_runtime_ms = int(panel_acc.get("scheduling_runtime_ms") or 0)
        total_duration_ms = total_runtime_ms + scheduling_runtime_ms

        segments = []
        for process_name, runtime_ms in sorted_processes:
            pct = (runtime_ms / total_runtime_ms) * 100.0 if total_runtime_ms else 0.0
            segments.append(
                {
                    "process": process_name,
                    "runtime_ms": runtime_ms,
                    "pct": _round(pct, 2),
                    "highlight": _is_highlight_process(process_name),
                }
            )

        legend = list(segments[:20])
        if len(segments) > 20:
            other_segments = segments[20:]
            other_runtime = sum(int(seg.get("runtime_ms") or 0) for seg in other_segments)
            other_pct = (other_runtime / total_runtime_ms) * 100.0 if total_runtime_ms else 0.0
            legend.append(
                {
                    "process": f"Other ({len(other_segments)} small processes)",
                    "runtime_ms": other_runtime,
                    "pct": _round(other_pct, 2),
                    "highlight": False,
                }
            )

        qc_runtime_ms = sum(int(seg.get("runtime_ms") or 0) for seg in segments if seg.get("highlight"))
        other_runtime_ms = total_runtime_ms - qc_runtime_ms

        combined_task_runtime.append(
            {
                "pipeline": pipeline,
                "group": group,
                "panel_id": f"{pipeline}::{group}",
                "total_runtime_ms": total_runtime_ms,
                "scheduling_runtime_ms": scheduling_runtime_ms,
                "total_duration_ms": total_duration_ms,
                "total_tasks": int(panel_acc["total_tasks"]),
                "unique_processes": len(segments),
                "segments": segments,
                "legend": legend,
                "highlight_totals": {
                    "qc_runtime_ms": qc_runtime_ms,
                    "other_runtime_ms": other_runtime_ms,
                },
            }
        )

    return {
        "benchmark_overview": benchmark_overview,
        "run_summary": run_summary,
        "run_metrics": run_metrics,
        "run_costs": run_costs,
        "process_stats": process_stats,
        "combined_task_runtime": combined_task_runtime,
        "task_instance_usage": task_instance_usage,
        "task_table": task_table,
        "task_scatter": task_scatter,
        "cost_overview": cost_overview,
    }


def aggregate_report_data(jsonl_dir: Path, output: Path) -> None:
    data = build_report_data(jsonl_dir)
    output.write_text(json.dumps(data, default=str))
