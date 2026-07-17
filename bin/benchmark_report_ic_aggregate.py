#!/usr/bin/env python3
"""Aggregate the JSONL bundle into an Intelligent Compute report_data_ic.json."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark_report_aggregate import _build_workspace_run_url, _classify_workflow_status, _iter_jsonl
from benchmark_report_normalize import _duration_ms

# AWS Cost and Usage Report data can lag pipeline completion by roughly a day.
# A run that finished inside this window and still lacks cost rows is treated as
# "likely not propagated yet" rather than "genuinely missing". Mirrors the
# benchmark report's cost-availability vocabulary so the two reports read alike.
_COST_PROPAGATION_WINDOW_HOURS = 24


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
    """Per run: requested vs effective CPU (vCPU-hours) and memory (GiB).

    Reproduces the Seqera Intelligent Compute "Metrics" panel *exactly* (verified to the decimal
    against the Platform UI on real mcmicro runs). CPU and memory are aggregated DIFFERENTLY —
    which is why the scheduler labels CPU "vCPU-h" but memory plain "GiB":

      CPU  — time-integrated over instance occupancy (start→complete, the slot-held window):
        req vCPU-h = Σ(cpus       × occupancy_h)     # what tasks asked for
        eff vCPU-h = Σ((pcpu/100) × occupancy_h)     # measured utilisation (pcpu/100 = cores used)

      Memory — a plain SUM of per-task memory, NOT time-weighted:
        req GiB = Σ(task memory  / GiB)              # requested memory summed over tasks
        eff GiB = Σ(peak RSS     / GiB)              # peak-resident memory summed over tasks

    Occupancy (not task ``realtime``) is the CPU basis: the scheduler bills the slot-held time.
    Platform timestamps are whole-second, so sub-second tasks contribute ~0 CPU-h — a data limit
    shared with the scheduler (it aggregates the same task records), not an error here.

    The scheduler's third figure — *Allocated* (provisioned instance size) — is NOT derivable
    from the Platform payload (only requested + provisioned per task, not the scheduler-chosen
    allocation), so it is deliberately omitted.
    """
    gib = 1024**3
    per_run: dict[str, dict[str, float]] = defaultdict(
        lambda: {"cpu_req": 0.0, "cpu_used": 0.0, "mem_req": 0.0, "mem_used": 0.0}
    )
    for t in _iter_jsonl(Path(jsonl_dir) / "tasks.jsonl"):
        acc = per_run[str(t.get("run_id", ""))]
        # CPU: integrate over occupancy (slot-held time); 0 for whole-second-collapsed tasks.
        occ_h = _duration_ms(t.get("start"), t.get("complete")) / 3.6e6
        acc["cpu_req"] += (t.get("cpus") or 0) * occ_h
        acc["cpu_used"] += (float(t.get("pcpu") or 0) / 100.0) * occ_h
        # Memory: plain per-task sum (no time weighting), in GiB.
        mem_used = t.get("peak_rss") or t.get("rss") or 0
        acc["mem_req"] += float(t.get("memory_bytes") or 0) / gib
        acc["mem_used"] += float(mem_used) / gib
    return dict(per_run)


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


def _parse_timestamp(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _classify_missing_cost(reference_ts: Any, now: datetime) -> str:
    """Explain why a run that a CUR export was supplied for still has no cost rows.

    A run that finished inside the CUR propagation window is ``propagating`` (cost
    data likely just hasn't landed yet); anything older — or with no usable
    timestamp — is ``not_found`` (we looked and there was nothing to match).
    """
    ts = _parse_timestamp(reference_ts)
    if ts is not None:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_hours = (now - ts).total_seconds() / 3600.0
        if age_hours < _COST_PROPAGATION_WINDOW_HOURS:
            return "propagating"
    return "not_found"


def _run_cost_details(jsonl_dir: Path) -> dict[str, dict[str, Any]]:
    """Per-run CUR cost breakdown from ``costs.jsonl``, keyed by run_id.

    ``costs.jsonl`` is only written when a CUR parquet is supplied to the normalize
    step, so an absent file leaves run costs unset — we never fall back to Seqera's
    unreliable cost estimate. CUR rows are task-grained (run_id, process, task_hash);
    they are summed here into one entry per run carrying:
      - ``cost``               blended total (used + unused) — the amount actually billed
      - ``used_cost``          cost of compute that was consumed (ECS split cost allocation)
      - ``unused_cost``        cost of provisioned-but-idle capacity
      - ``split_cost_present`` whether any row carried genuine split cost allocation

    We want split cost allocation for every run (Intelligent Compute and Batch). In
    practice Batch runs reliably carry it; IC runs sometimes don't yet — we're still
    investigating why. A run with no split cost keeps ``split_cost_present`` False, and
    its ``used_cost`` falls back to the unblended line-item cost (see ``normalize``); in
    practice that fallback only affects IC runs.
    """
    details: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"cost": 0.0, "used_cost": 0.0, "unused_cost": 0.0, "split_cost_present": False}
    )
    for row in _iter_jsonl(jsonl_dir / "costs.jsonl"):
        run_id = str(row.get("run_id") or "")
        if not run_id:
            continue
        entry = details[run_id]
        entry["cost"] += float(row.get("cost") or 0.0)
        entry["used_cost"] += float(row.get("used_cost") or 0.0)
        entry["unused_cost"] += float(row.get("unused_cost") or 0.0)
        if row.get("split_cost_present"):
            entry["split_cost_present"] = True
    return dict(details)


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


def build_ic_report_data(
    jsonl_dir: Path, web_base: str = "https://cloud.seqera.io", include_failed_runs: bool = False
) -> dict[str, Any]:
    jsonl_dir = Path(jsonl_dir)

    # Real per-run costs from an AWS CUR export, if one was supplied. Empty otherwise.
    # ``costs.jsonl`` exists iff a CUR parquet was passed to normalize, so its presence
    # is how we tell "cost analysis is off" (no file) from "on, but this run has no rows".
    cur_supplied = (jsonl_dir / "costs.jsonl").exists()
    cost_details = _run_cost_details(jsonl_dir)
    now = datetime.now(timezone.utc)

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
        # Drop failed runs from the report entirely (and never surface their CUR costs)
        # unless include_failed_runs is set; cancelled/aborted are always dropped. Same
        # rule as the benchmark report — see _classify_workflow_status.
        _, _, report_included = _classify_workflow_status(
            run.get("status"), include_failed_runs=include_failed_runs
        )
        if not report_included:
            continue

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
        req_cpu_vcpu_h = round(res.get("cpu_req", 0.0), 2)
        eff_cpu_vcpu_h = round(res.get("cpu_used", 0.0), 2)
        req_mem_gib = round(res.get("mem_req", 0.0), 1)
        eff_mem_gib = round(res.get("mem_used", 0.0), 1)

        # Cost, preferring ECS split cost allocation (used vs idle) when the CUR export
        # carries it for this run, else the unblended total. We want split cost for every
        # run (Intelligent Compute and Batch); in practice Batch reliably has it while IC
        # sometimes doesn't yet (under investigation), so the blended fallback here in
        # practice only affects IC runs. When a CUR file was supplied but no row matched
        # this run, cost_status explains why (propagating vs not_found); with no CUR at all
        # the whole cost story is off and every field stays None.
        detail = cost_details.get(run_id)
        if detail is not None:
            split_present = bool(detail["split_cost_present"])
            cost = round(detail["cost"], 4)
            used_cost = round(detail["used_cost"], 4) if split_present else None
            unused_cost = round(detail["unused_cost"], 4) if split_present else None
            cost_basis = "split" if split_present else "blended"
            cost_status = "available"
        else:
            cost = used_cost = unused_cost = None
            cost_basis = None
            cost_status = None if not cur_supplied else _classify_missing_cost(
                run.get("complete") or started_at, now
            )

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
            # Requested vs effective CPU (vCPU-h, occupancy-integrated) and memory (GiB, summed) —
            # reproduces the IC scheduler Metrics panel exactly. See _run_resource_usage. Shown in
            # the Performance "Resource usage" table/chart.
            "req_cpu_vcpu_h": req_cpu_vcpu_h,
            "eff_cpu_vcpu_h": eff_cpu_vcpu_h,
            "req_mem_gib": req_mem_gib,
            "eff_mem_gib": eff_mem_gib,
            "run_cost_platform": run.get("run_cost"),
            # Real cost from the AWS CUR export; None when no CUR row matched this run
            # (renders as an em-dash). The Seqera estimate above is never used here.
            "cost": cost,
            # Split cost allocation (used vs idle) when present, else None -> em-dash.
            "used_cost": used_cost,
            "unused_cost": unused_cost,
            # "split" | "blended" | None (no cost row): how this run's cost was derived.
            "cost_basis": cost_basis,
            # "available" | "propagating" | "not_found" | None (no CUR at all).
            "cost_status": cost_status,
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

    runs_with_cost = [r for r in run_summary if r["cost_status"] == "available"]
    return {
        "ic_overview": {
            "n_runs": len(run_summary),
            "n_intelligent_compute": n_ic,
            "n_batch": n_batch,
            # "aws_cur" when real CUR costs were joined onto at least one run, else None.
            "cost_source": "aws_cur" if cost_details else None,
            # Whether a CUR export was supplied at all (distinguishes "no cost analysis"
            # from "analysis on, but nothing matched this set of runs").
            "cur_supplied": cur_supplied,
            # Cost-coverage tallies driving the report's cost-availability note.
            "n_runs_with_cost": len(runs_with_cost),
            "n_runs_split_cost": sum(1 for r in runs_with_cost if r["cost_basis"] == "split"),
            "n_runs_blended_cost": sum(1 for r in runs_with_cost if r["cost_basis"] == "blended"),
            "n_runs_missing_cost": sum(
                1 for r in run_summary if r["cost_status"] in ("propagating", "not_found")
            ),
        },
        "run_summary": run_summary,
        "machine_usage": machine_usage,
    }


def aggregate_ic_report_data(
    jsonl_dir: Path,
    output: Path,
    web_base: str = "https://cloud.seqera.io",
    include_failed_runs: bool = False,
) -> None:
    data = build_ic_report_data(jsonl_dir, web_base=web_base, include_failed_runs=include_failed_runs)
    Path(output).write_text(json.dumps(data, indent=2, default=str))
