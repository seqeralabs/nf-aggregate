#!/usr/bin/env python3
"""Aggregate the JSONL bundle into an Intelligent Compute report_data_ic.json."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from benchmark_report_aggregate import _build_workspace_run_url, _iter_jsonl


def _compute_type(run: dict[str, Any]) -> str:
    """Intelligent Compute if the scheduler was enabled, else batch.

    schedEnabled is the primary signal; platform_id 'aws-cloud' corroborates.
    Do NOT key off Fusion — both IC and Batch runs can have Fusion enabled.
    """
    if run.get("sched_enabled"):
        return "intelligent_compute"
    if (run.get("platform_id") or "").lower() == "aws-cloud":
        return "intelligent_compute"
    return "batch"


def _build_machine_usage(
    jsonl_dir: Path, run_order: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Distribution of machine (instance) types per run, from tasks.jsonl.

    For each run, count tasks and sum cpu-hours (cpus * realtime_ms / 3.6e6) per
    machine type. Tasks with no reported machineType are bucketed as 'unknown'.
    Each machine type gets a stable global color_idx (assigned over the sorted set
    of distinct types across all runs) so the same instance type is coloured
    consistently in every run's bar.
    """
    per_run: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"task_count": 0, "cpu_hours": 0.0})
    )
    for task in _iter_jsonl(Path(jsonl_dir) / "tasks.jsonl"):
        run_id = str(task.get("run_id", ""))
        machine_type = task.get("machine_type") or "unknown"
        cpus = task.get("cpus") or 0
        realtime_ms = task.get("realtime_ms") or 0
        acc = per_run[run_id][machine_type]
        acc["task_count"] += 1
        acc["cpu_hours"] += (cpus * realtime_ms) / 3.6e6

    distinct = sorted({mt for machines in per_run.values() for mt in machines})
    color_idx = {mt: i for i, mt in enumerate(distinct)}

    usage: list[dict[str, Any]] = []
    for run in run_order:
        machines_raw = per_run.get(run["run_id"], {})
        total_tasks = sum(int(m["task_count"]) for m in machines_raw.values())
        total_cpu_hours = round(sum(m["cpu_hours"] for m in machines_raw.values()), 2)
        machines = [
            {
                "machine_type": mt,
                "task_count": int(m["task_count"]),
                "task_pct": round(m["task_count"] / total_tasks * 100, 1) if total_tasks else 0.0,
                "cpu_hours": round(m["cpu_hours"], 2),
                "color_idx": color_idx[mt],
            }
            for mt, m in sorted(
                machines_raw.items(), key=lambda kv: (-kv[1]["task_count"], kv[0])
            )
        ]
        usage.append({
            "run_id": run["run_id"],
            "run_name": run["run_name"],
            "run_url": run["run_url"],
            "compute_type": run["compute_type"],
            "total_tasks": total_tasks,
            "total_cpu_hours": total_cpu_hours,
            "machines": machines,
        })
    return usage


def build_ic_report_data(jsonl_dir: Path, web_base: str = "https://cloud.seqera.io") -> dict[str, Any]:
    jsonl_dir = Path(jsonl_dir)
    run_summary: list[dict[str, Any]] = []
    run_order: list[dict[str, Any]] = []
    n_ic = 0
    n_batch = 0

    for run in _iter_jsonl(jsonl_dir / "runs.jsonl"):
        compute_type = _compute_type(run)
        if compute_type == "intelligent_compute":
            n_ic += 1
        else:
            n_batch += 1

        cpu_time_ms = run.get("cpu_time_ms") or 0
        # TODO: verify cpuTime unit against the Platform UI (cpuTime vs stats.computeTimeFmt disagree in scale)
        compute_hours = round(cpu_time_ms / 3.6e6, 2)
        mem_bytes = run.get("memory_rss_bytes") or 0
        run_id = run.get("run_id", "")
        run_url = _build_workspace_run_url(
            run_id, run.get("workspace"), web_base, existing_url=run.get("run_url")
        )

        run_summary.append({
            "run_id": run_id,
            "run_url": run_url,
            "run_name": run.get("run_name", ""),
            "pipeline": run.get("pipeline", ""),
            "group": run.get("group", ""),
            "compute_type": compute_type,
            "status": run.get("status", ""),
            "compute_hours": compute_hours,
            "memory_used_bytes": mem_bytes,
            "memory_used_gb": round(mem_bytes / 1024**3, 2),
            "run_cost_platform": run.get("run_cost"),
            "cost": None,  # core-report cost — not wired yet
        })
        run_order.append({
            "run_id": run_id,
            "run_name": run.get("run_name", ""),
            "run_url": run_url,
            "compute_type": compute_type,
        })

    return {
        "ic_overview": {
            "n_runs": len(run_summary),
            "n_intelligent_compute": n_ic,
            "n_batch": n_batch,
            "cost_source": None,
        },
        "run_summary": run_summary,
        "machine_usage": _build_machine_usage(jsonl_dir, run_order),
    }


def aggregate_ic_report_data(
    jsonl_dir: Path, output: Path, web_base: str = "https://cloud.seqera.io"
) -> None:
    data = build_ic_report_data(jsonl_dir, web_base=web_base)
    Path(output).write_text(json.dumps(data, indent=2, default=str))
