#!/usr/bin/env python3
"""Aggregate the JSONL bundle into an Intelligent Compute report_data_ic.json."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from benchmark_report_aggregate import _build_workspace_run_url, _iter_jsonl
from benchmark_report_normalize import _duration_ms


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


# Facet/table ordering: Intelligent Compute before AWS Batch, mirroring the chart facets.
_ENGINE_RANK = {"intelligent_compute": 0, "batch": 1}


def _engine_rank(compute_type: str) -> int:
    return _ENGINE_RANK.get(compute_type, 2)


def _task_occupancy_hours(task: dict[str, Any]) -> float:
    """CPU-hours a task occupied its instance = cpus * (complete - start).

    Uses instance occupancy (slot-held time), NOT task.realtime (tool execution
    only). This is the single basis shared by BOTH the per-run 'compute hours'
    and the per-machine cpu-hours so the machine breakdown sums to the run total.
    TODO: this occupancy basis approximates the Platform's requestedCpuTime; the
    exact match to the Platform UI's compute-hours figure is still open.
    """
    cpus = task.get("cpus") or 0
    occupancy_ms = cpus * _duration_ms(task.get("start"), task.get("complete"))
    return occupancy_ms / 3.6e6


def _run_resource_usage(jsonl_dir: Path) -> dict[str, dict[str, float]]:
    """Per run: time-weighted average requested vs actually-used CPU (cores) and memory (GB).

    Each task contributes weighted by its realtime (long tasks count more):
      req cores  = Σ(cpus × realtime) / Σ realtime
      used cores = Σ((pcpu/100) × realtime) / Σ realtime      # pcpu/100 = cores actually used
      req GB / used GB likewise from task memory / peak RSS.
    Reported in cores and GB (NOT cpu-hours, NOT %) so the figures read like the Platform's
    per-task resource numbers (e.g. "1.2 cores"). Efficiency is deliberately NOT derived: a
    faithful used/allocated ratio needs the scheduler-*allocated* size, which the Platform
    payload does not carry (only requested + provisioned), so a logs-only efficiency would
    mislead for both engines.
    """
    gib = 1024**3
    per_run: dict[str, dict[str, float]] = defaultdict(
        lambda: {"cpu_req": 0.0, "cpu_used": 0.0, "mem_req": 0.0, "mem_used": 0.0, "rt": 0.0}
    )
    for t in _iter_jsonl(Path(jsonl_dir) / "tasks.jsonl"):
        rt = float(t.get("realtime_ms") or 0)
        if rt <= 0:
            continue
        acc = per_run[str(t.get("run_id", ""))]
        acc["rt"] += rt
        acc["cpu_req"] += (t.get("cpus") or 0) * rt
        acc["cpu_used"] += (float(t.get("pcpu") or 0) / 100.0) * rt
        mem_used = t.get("peak_rss") or t.get("rss") or 0
        acc["mem_req"] += (float(t.get("memory_bytes") or 0) / gib) * rt
        acc["mem_used"] += (float(mem_used) / gib) * rt
    means: dict[str, dict[str, float]] = {}
    for run_id, a in per_run.items():
        rt = a["rt"] or 1.0
        means[run_id] = {
            "cpu_req": a["cpu_req"] / rt,
            "cpu_used": a["cpu_used"] / rt,
            "mem_req": a["mem_req"] / rt,
            "mem_used": a["mem_used"] / rt,
        }
    return means


def _machine_breakdown(jsonl_dir: Path) -> dict[str, dict[str, dict[str, float]]]:
    """Per run, per machine type: task_count and occupancy cpu_hours."""
    per_run: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"task_count": 0, "cpu_hours": 0.0})
    )
    for task in _iter_jsonl(Path(jsonl_dir) / "tasks.jsonl"):
        run_id = str(task.get("run_id", ""))
        machine_type = task.get("machine_type") or "unknown"
        acc = per_run[run_id][machine_type]
        acc["task_count"] += 1
        acc["cpu_hours"] += _task_occupancy_hours(task)
    return per_run


def _build_machine_usage(
    per_run: dict[str, dict[str, dict[str, float]]], run_order: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Distribution of machine (instance) types per run.

    Each machine type gets a stable global color_idx (assigned over the sorted set
    of distinct types across all runs) so the same instance type is coloured
    consistently in every run's bar.
    """
    distinct = sorted({mt for machines in per_run.values() for mt in machines})
    color_idx = {mt: i for i, mt in enumerate(distinct)}

    usage: list[dict[str, Any]] = []
    for run in run_order:
        machines_raw = per_run.get(run["run_id"], {})
        total_tasks = sum(int(m["task_count"]) for m in machines_raw.values())
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
        # Sum the ALREADY-ROUNDED per-machine values so the report is internally
        # consistent: the displayed run total == the sum of the displayed bars.
        total_cpu_hours = round(sum(m["cpu_hours"] for m in machines), 2)
        usage.append({
            "run_id": run["run_id"],
            "run_name": run["run_name"],
            "run_url": run["run_url"],
            "pipeline": run.get("pipeline", ""),
            "compute_type": run["compute_type"],
            "started_at": run.get("started_at", ""),
            "date_short": run.get("date_short", ""),
            "total_tasks": total_tasks,
            "total_cpu_hours": total_cpu_hours,
            "machines": machines,
        })
    return usage


def _run_costs_from_cur(jsonl_dir: Path) -> dict[str, float]:
    """Per-run cost totals from a real AWS CUR export (``costs.jsonl``), keyed by run_id.

    ``costs.jsonl`` is only written when a CUR parquet is supplied to the normalize step,
    so an absent/empty file leaves run costs unset — we never fall back to Seqera's
    unreliable cost estimate. CUR rows are task-grained (run_id, process, task_hash);
    they are summed here into one cost per run. The run_id here is whatever the CUR
    resource-label map resolves to; the label that ties a CUR row to a Seqera run is
    finalised in a follow-up step.
    """
    totals: dict[str, float] = defaultdict(float)
    for row in _iter_jsonl(jsonl_dir / "costs.jsonl"):
        run_id = str(row.get("run_id") or "")
        if not run_id:
            continue
        totals[run_id] += float(row.get("cost") or 0.0)
    # 4 decimal places: CUR run costs are often sub-cent, so 2 dp collapses them to 0.00.
    return {run_id: round(total, 4) for run_id, total in totals.items()}


def _run_task_timing(jsonl_dir: Path) -> dict[str, dict[str, float]]:
    """Per run, summed from tasks: active run time and staging time (milliseconds).

    Definitions agreed in Slack (Florian/Paolo, per Nextflow ``duration`` semantics):
      - task runtime  = start -> complete  (includes staging, EXCLUDES machine-wait,
        since submit->start waiting is random instance-availability time we don't bill)
      - task staging  = runtime - realtime
    So per run:
      - total_run_time_ms     = sum of task runtimes  (time machines were actually working)
      - total_staging_time_ms = sum of task staging   (runtime not spent executing the tool)
    Wall time is NOT summed here — it's the run-level ``duration`` (submit -> complete of
    the whole workflow, same as the Platform), taken straight from runs.jsonl.
    """
    agg: dict[str, dict[str, float]] = defaultdict(lambda: {"run_time_ms": 0.0, "staging_ms": 0.0})
    for task in _iter_jsonl(Path(jsonl_dir) / "tasks.jsonl"):
        run_id = str(task.get("run_id", ""))
        runtime = _duration_ms(task.get("start"), task.get("complete"))
        realtime = float(task.get("realtime_ms") or 0)
        agg[run_id]["run_time_ms"] += runtime
        # clamp: second-resolution timestamps can make a very short task's runtime dip
        # just under its realtime, which would otherwise yield a tiny negative staging.
        agg[run_id]["staging_ms"] += max(0.0, runtime - realtime)
    return agg


def build_ic_report_data(jsonl_dir: Path, web_base: str = "https://cloud.seqera.io") -> dict[str, Any]:
    jsonl_dir = Path(jsonl_dir)

    # Real per-run costs from an AWS CUR export, if one was supplied. Empty otherwise.
    cur_costs = _run_costs_from_cur(jsonl_dir)

    # Machine/instance breakdown defines the shared occupancy cpu-hours basis; the
    # run-level "compute hours" is then taken from each run's machine total, so the
    # two reconcile exactly (run compute_hours == displayed sum of that run's bars).
    per_run = _machine_breakdown(jsonl_dir)
    timing = _run_task_timing(jsonl_dir)
    resource = _run_resource_usage(jsonl_dir)

    run_summary: list[dict[str, Any]] = []
    n_ic = 0
    n_batch = 0

    for run in _iter_jsonl(jsonl_dir / "runs.jsonl"):
        compute_type = _compute_type(run)
        if compute_type == "intelligent_compute":
            n_ic += 1
        else:
            n_batch += 1

        mem_bytes = run.get("memory_rss_bytes") or 0
        run_id = run.get("run_id", "")
        run_url = _build_workspace_run_url(
            run_id, run.get("workspace"), web_base, existing_url=run.get("run_url")
        )
        started_at = run.get("start") or ""

        res = resource.get(run_id, {})
        req_cpu_cores = round(res.get("cpu_req", 0.0), 2)
        used_cpu_cores = round(res.get("cpu_used", 0.0), 2)
        req_mem_gb = round(res.get("mem_req", 0.0), 2)
        used_mem_gb = round(res.get("mem_used", 0.0), 2)

        run_summary.append({
            "run_id": run_id,
            "run_url": run_url,
            "run_name": run.get("run_name", ""),
            "pipeline": run.get("pipeline", ""),
            "group": run.get("group", ""),
            "compute_type": compute_type,
            "status": run.get("status", ""),
            "started_at": started_at,          # full ISO-8601 timestamp (may be "")
            "date_short": started_at[:10],      # YYYY-MM-DD for compact chart labels
            "compute_hours": 0.0,  # backfilled from machine_usage below
            # Timing (ms). wall = run-level duration (submit -> complete, incl. waiting);
            # run/staging are summed from tasks (see _run_task_timing).
            "wall_time_ms": run.get("duration_ms"),
            "total_run_time_ms": round(timing[run_id]["run_time_ms"]),
            "total_staging_time_ms": round(timing[run_id]["staging_ms"]),
            "memory_used_bytes": mem_bytes,
            "memory_used_gb": round(mem_bytes / 1024**3, 2),
            # Time-weighted average requested vs used CPU (cores) and memory (GB) — see
            # _run_resource_usage. Shown in the Performance "Resource usage" table/chart.
            "req_cpu_cores": req_cpu_cores,
            "used_cpu_cores": used_cpu_cores,
            "req_mem_gb": req_mem_gb,
            "used_mem_gb": used_mem_gb,
            "run_cost_platform": run.get("run_cost"),
            # Real cost from the AWS CUR export; None when no CUR row matched this run
            # (renders as an em-dash). The Seqera estimate above is never used here.
            "cost": cur_costs.get(run_id),
        })

    # Default order: group by pipeline, then facet (IC before Batch), then newest run
    # first within each group. Two stable passes give the mixed asc/desc ordering; runs
    # with no start timestamp ("") sort last within their group.
    run_summary.sort(key=lambda r: r["started_at"], reverse=True)
    run_summary.sort(key=lambda r: (r["pipeline"] or "", _engine_rank(r["compute_type"])))

    run_order = [
        {
            "run_id": r["run_id"],
            "run_name": r["run_name"],
            "run_url": r["run_url"],
            "pipeline": r["pipeline"],
            "compute_type": r["compute_type"],
            "started_at": r["started_at"],
            "date_short": r["date_short"],
        }
        for r in run_summary
    ]

    machine_usage = _build_machine_usage(per_run, run_order)
    run_totals = {u["run_id"]: u["total_cpu_hours"] for u in machine_usage}
    for row in run_summary:
        row["compute_hours"] = run_totals.get(row["run_id"], 0.0)

    return {
        "ic_overview": {
            "n_runs": len(run_summary),
            "n_intelligent_compute": n_ic,
            "n_batch": n_batch,
            # "aws_cur" when real CUR costs were joined onto at least one run, else None.
            "cost_source": "aws_cur" if cur_costs else None,
        },
        "run_summary": run_summary,
        "machine_usage": machine_usage,
    }


def aggregate_ic_report_data(
    jsonl_dir: Path, output: Path, web_base: str = "https://cloud.seqera.io"
) -> None:
    data = build_ic_report_data(jsonl_dir, web_base=web_base)
    Path(output).write_text(json.dumps(data, indent=2, default=str))
