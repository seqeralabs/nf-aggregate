#!/usr/bin/env python3
"""Aggregate benchmark JSONL datasets into report_data.json."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from typing import Any, Iterator

from benchmark_report_normalize import _require_readable

_HIGHLIGHT_KEYWORDS = ("qc", "qualimap", "multiqc", "rseqc", "dupradar")

# AWS Cost and Usage Report data can lag pipeline completion by roughly a day.
# A run that finished inside this window and still lacks cost rows is treated as
# "likely not propagated yet" rather than "genuinely missing".
_COST_PROPAGATION_WINDOW_HOURS = 24


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    # The JSONL bundle is a STAGED input, so its files carry the same exposure as any other:
    # under Fusion a stat can fail with EACCES rather than ENOENT. Absent means "this dataset
    # was not produced" and is skipped; unreadable raises, because silently skipping it would
    # turn a permission problem into a report that looks complete.
    if not _require_readable("JSONL bundle file", path):
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
    session_index: dict[tuple[str, str, str], dict[str, Any]] | None = None,
    session_id: str = "",
) -> dict[str, Any] | None:
    for process_key in (process, process_short, ""):
        row = costs_index.get(_cost_key(run_id, process_key, hash_short))
        if row:
            return row
    if session_index and session_id:
        # A CACHED task was billed under an EARLIER attempt's workflow id, so no row exists
        # under this run's id. Nextflow task hashes are content-addressed and identical
        # across resumes, so the hash finds the attempt that actually paid for the task.
        for process_key in (process, process_short, ""):
            row = session_index.get(_cost_key(session_id, process_key, hash_short))
            if row:
                return row
    return None


# Every cost field ``normalize`` emits per row. Pooling sums all of them so one pass over
# costs.jsonl serves both reports (the benchmark report reads cost/used_cost/unused_cost,
# the IC report the unblended/split/spot bases).
_COST_FIELDS = (
    "cost",
    "used_cost",
    "unused_cost",
    "unblended_cost",
    "split_cost",
    "spot_cost",
    "ondemand_cost",
)


def _empty_cost_sums() -> dict[str, Any]:
    sums: dict[str, Any] = {name: 0.0 for name in _COST_FIELDS}
    sums["split_cost_present"] = False
    return sums


def _add_cost_row(target: dict[str, Any], row: dict[str, Any]) -> None:
    for name in _COST_FIELDS:
        target[name] += float(row.get(name) or 0.0)
    if row.get("split_cost_present"):
        target["split_cost_present"] = True


def _load_run_lineage(jsonl_dir: Path) -> dict[str, dict[str, Any]]:
    """Per run: the resume facts needed to pool cost across attempts.

    ``session_id`` is stable across resumes while ``run_id`` names one attempt, so a
    resumed run's earlier spend sits under workflow ids the samplesheet never mentions.
    """
    lineage: dict[str, dict[str, Any]] = {}
    for row in _iter_jsonl(jsonl_dir / "runs.jsonl"):
        run_id = str(row.get("run_id", ""))
        if not run_id:
            continue
        lineage[run_id] = {
            "session_id": str(row.get("session_id") or ""),
            "resumed": bool(row.get("resumed")),
            "cached": int(row.get("cached") or 0),
            "succeeded": int(row.get("succeeded") or 0),
            "failed": int(row.get("failed") or 0),
            "reference_ts": row.get("complete") or row.get("start") or "",
        }
    return lineage


def _session_owners(lineage: dict[str, dict[str, Any]]) -> dict[str, str]:
    """session_id -> the ONE run_id allowed to claim that session's pooled cost.

    Only resumed runs get an entry; a run that reused no earlier work has nothing to pool
    and keeps exactly the behaviour it had before sessions existed.

    The single-owner rule is what stops double counting. If a samplesheet lists two
    attempts of the same session, both would otherwise claim the whole lineage and every
    total that sums runs would be inflated. The newest attempt owns the pool (it is the one
    whose cached tasks reach back through the lineage); the others keep their own
    attempt-scoped cost.
    """
    owners: dict[str, str] = {}
    for run_id, info in sorted(lineage.items()):
        session_id = info["session_id"]
        if not session_id or not info["resumed"]:
            continue
        current = owners.get(session_id)
        if current is None or lineage[current]["reference_ts"] <= info["reference_ts"]:
            owners[session_id] = run_id
    return owners


def _load_cost_pools(jsonl_dir: Path, lineage: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Index costs.jsonl by task, by run and — for resumed runs — by session.

    The session pools are built ONLY for sessions that a resumed run owns, so a report with
    no resumed runs allocates nothing extra and produces byte-identical output.

    A row joins its session pool when its own ``session_id`` label matches OR it belongs to
    an attempt already known to be in the lineage. Set semantics, not two sums: each row is
    counted at most once, which matters because Intelligent Compute's ECS split rows carry
    no process/task labels and would otherwise be easy to add twice.
    """
    owners = _session_owners(lineage)
    owned_sessions = set(owners)
    session_of_run = {
        run_id: info["session_id"]
        for run_id, info in lineage.items()
        if info["session_id"] in owned_sessions
    }

    pools: dict[str, Any] = {
        "by_task": {},
        "by_run": {},
        "by_session_task": {},
        "by_session": {},
        "session_attempts": defaultdict(set),
        "session_hashes": defaultdict(set),
        "owners": owners,
        "has_rows": False,
    }

    for row in _iter_jsonl(jsonl_dir / "costs.jsonl"):
        pools["has_rows"] = True
        run_id = str(row.get("run_id", ""))
        process = str(row.get("process", ""))
        hash_short = str(row.get("hash", ""))

        task_key = _cost_key(run_id, process, hash_short)
        _add_cost_row(pools["by_task"].setdefault(task_key, _empty_cost_sums()), row)
        _add_cost_row(pools["by_run"].setdefault(run_id, _empty_cost_sums()), row)

        session_id = str(row.get("session_id") or "") or session_of_run.get(run_id, "")
        if session_id not in owned_sessions:
            continue
        session_key = _cost_key(session_id, process, hash_short)
        _add_cost_row(pools["by_session_task"].setdefault(session_key, _empty_cost_sums()), row)
        _add_cost_row(pools["by_session"].setdefault(session_id, _empty_cost_sums()), row)
        if run_id:
            pools["session_attempts"][session_id].add(run_id)
        if hash_short:
            pools["session_hashes"][session_id].add(hash_short)

    return pools


def _cost_or_task(cost_row: dict[str, Any] | None, key: str, default: float = 0.0) -> float:
    if not cost_row:
        return default

    value = cost_row.get(key)
    if value is None:
        return default

    return float(value)


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
    """Explain why a run has no cost rows.

    A run that finished inside the CUR propagation window is flagged
    ``propagating`` (cost data likely just hasn't landed yet); anything older —
    or with no usable timestamp — is ``not_found`` (we looked and there was
    nothing to match).
    """
    ts = _parse_timestamp(reference_ts)
    if ts is not None:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_hours = (now - ts).total_seconds() / 3600.0
        if age_hours < _COST_PROPAGATION_WINDOW_HOURS:
            return "propagating"
    return "not_found"


def _summarize_missing_processes(
    missing_process_counts: dict[str, int], preview_limit: int = 3
) -> tuple[list[dict[str, Any]], str]:
    ordered = sorted(missing_process_counts.items(), key=lambda item: (-item[1], item[0]))
    preview = [
        {"process_short": process_short, "missing_tasks": missing_tasks}
        for process_short, missing_tasks in ordered[:preview_limit]
    ]
    parts = [
        f"{item['process_short']} ({item['missing_tasks']})"
        if item["missing_tasks"] != 1
        else item["process_short"]
        for item in preview
    ]
    hidden_count = max(len(ordered) - preview_limit, 0)
    if hidden_count:
        parts.append(f"+{hidden_count} more")
    return preview, ", ".join(parts)


def _is_highlight_process(process: str) -> bool:
    process_lc = process.lower()
    return any(keyword in process_lc for keyword in _HIGHLIGHT_KEYWORDS)


def _classify_workflow_status(status: str | None, include_failed_runs: bool = False) -> tuple[str, str, bool]:
    normalized = (status or "").strip().upper()
    if normalized in {"FAILED", "ERROR", "FAILING"}:
        return ("Failed", "failed", include_failed_runs)
    if normalized in {"CANCELLED", "CANCELED", "ABORTED", "ABORT", "STOPPED"}:
        return ("Cancelled", "cancelled", False)
    if normalized in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
        return ("Succeeded", "success", True)
    if not normalized:
        return ("Unknown", "unknown", True)
    return (normalized.title(), "other", True)


def _positive_gap(upper: float | None, lower: float | None) -> float | None:
    if upper is None or lower is None:
        return None
    return max(upper - lower, 0.0)


def _compute_scheduler_booked(
    capacity: float | None, efficiency_pct: float | None, fallback: float | None = None
) -> float | None:
    if capacity is not None and efficiency_pct is not None:
        return min(capacity, max(0.0, capacity * efficiency_pct / 100.0))
    if fallback is not None:
        return max(fallback, 0.0)
    return None


def _build_workspace_run_url(
    run_id: str,
    workspace: str | None,
    platform: str | None,
    existing_url: str | None = None,
) -> str:
    existing = (existing_url or "").strip()
    if existing and "example.invalid" not in existing.lower():
        return existing

    workspace_value = (workspace or "").strip()
    platform_value = (platform or "").strip().rstrip("/")
    if not workspace_value or "/" not in workspace_value or not platform_value:
        return ""

    org_slug, workspace_slug = workspace_value.split("/", 1)
    return f"{platform_value}/orgs/{org_slug}/workspaces/{workspace_slug}/watch/{run_id}"


def _load_machines_index(jsonl_dir: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in _iter_jsonl(jsonl_dir / "machines.jsonl"):
        run_id = str(row.get("run_id", ""))
        if run_id:
            index[run_id] = row
    return index


def build_report_data(jsonl_dir: Path, include_failed_runs: bool = False) -> dict[str, Any]:
    benchmark_overview: list[dict[str, Any]] = []
    run_summary: list[dict[str, Any]] = []
    run_metrics: list[dict[str, Any]] = []

    run_cost_acc: dict[tuple[str, str], dict[str, Any]] = {}
    run_pipeline: dict[str, str] = {}
    run_end_ts: dict[str, Any] = {}
    included_run_ids: set[str] = set()
    machines_index = _load_machines_index(jsonl_dir)
    lineage = _load_run_lineage(jsonl_dir)

    for r in _iter_jsonl(jsonl_dir / "runs.jsonl"):
        run_id = str(r.get("run_id", ""))
        group = str(r.get("group", ""))
        run_pipeline[run_id] = str(r.get("pipeline") or "unknown")
        run_end_ts[run_id] = r.get("complete") or r.get("start")
        status_label, status_category, report_included = _classify_workflow_status(
            r.get("status"), include_failed_runs=include_failed_runs
        )

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

        run_summary.append(
            {
                "pipeline": r.get("pipeline"),
                "group": group,
                "run_id": run_id,
                "workspace": r.get("workspace"),
                "runUrl": _build_workspace_run_url(
                    run_id=run_id,
                    workspace=r.get("workspace"),
                    platform=r.get("platform"),
                    existing_url=r.get("run_url"),
                ),
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
                # Resume provenance. `attempts` is backfilled below from the number of
                # distinct workflow ids that spent money under this session, so it counts
                # attempts that were actually billed, not attempts that existed.
                "session_id": r.get("session_id") or "",
                "resumed": bool(r.get("resumed")),
                "attempts": 1,
                "earlier_attempts": 0,
                "executor": r.get("executor"),
                "region": r.get("region"),
                "fusion_enabled": r.get("fusion_enabled", False),
                "wave_enabled": r.get("wave_enabled", False),
                "container_engine": r.get("container_engine"),
            }
        )

        if not report_included:
            continue

        included_run_ids.add(run_id)

        metrics_row = {
            "pipeline": r.get("pipeline"),
            "group": group,
            "run_id": run_id,
            "workspace": r.get("workspace"),
            "runUrl": _build_workspace_run_url(
                run_id=run_id,
                workspace=r.get("workspace"),
                platform=r.get("platform"),
                existing_url=r.get("run_url"),
            ),
            "duration": int(r.get("duration_ms") or 0),
            "cpuTime": _round((float(r.get("cpu_time_ms") or 0) / 1000.0) / 3600.0, 1),
            "pipeline_runtime": int(r.get("cpu_time_ms") or 0),
            "cpuEfficiency": _round(float(r.get("cpu_efficiency")) if r.get("cpu_efficiency") is not None else None, 0),
            "memoryEfficiency": _round(float(r.get("memory_efficiency")) if r.get("memory_efficiency") is not None else None, 2),
            "readBytes": _round(float(r.get("read_bytes") or 0) / 1e9, 0),
            "writeBytes": _round(float(r.get("write_bytes") or 0) / 1e9, 0),
        }

        vm = machines_index.get(run_id)
        if vm:
            metrics_row["nMachines"] = vm.get("n_machines")
            metrics_row["vmCpuH"] = _round(vm.get("vm_cpu_h"), 2)
            metrics_row["vmMemGibH"] = _round(vm.get("vm_mem_gib_h"), 2)
            metrics_row["schedAllocCpuEfficiency"] = _round(vm.get("sched_alloc_cpu_efficiency"), 2)
            metrics_row["schedAllocMemEfficiency"] = _round(vm.get("sched_alloc_mem_efficiency"), 2)

        run_metrics.append(metrics_row)

        key = (run_id, group)
        run_cost_acc[key] = {
            "run_id": key[0],
            "group": key[1],
            "cost": 0.0,
            "used_cost": 0.0,
            "unused_cost": 0.0,
        }

    costs_jsonl_path = jsonl_dir / "costs.jsonl"
    # Presence of costs.jsonl is what distinguishes "cost analysis was off" from "on, but this
    # run matched nothing", so an unreadable file must NOT be read as absent — that would
    # relabel every run's cost_status as null and hide the failure.
    cur_supplied = _require_readable("costs.jsonl", costs_jsonl_path)
    pools = _load_cost_pools(jsonl_dir, lineage)
    costs_index = pools["by_task"]
    session_index = pools["by_session_task"]
    session_owners = pools["owners"]
    has_cost_rows = pools["has_rows"]

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

    # Task-derived CPU/memory resource accumulators per run
    task_run_acc: dict[str, dict[str, float]] = defaultdict(
        lambda: {"requested_cpu_h": 0.0, "requested_mem_gib_h": 0.0, "real_cpu_h": 0.0, "real_mem_gib_h": 0.0}
    )
    cost_coverage_runs: dict[tuple[str, str], dict[str, Any]] = {}
    total_cost_tasks = 0
    matched_cost_tasks = 0
    missing_cost_tasks = 0

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

        session_id = lineage.get(run_id, {}).get("session_id", "")
        cost_row = _lookup_cost(
            costs_index,
            run_id=run_id,
            process=process,
            process_short=process_short,
            hash_short=hash_short,
            session_index=session_index,
            session_id=session_id if session_owners.get(session_id) == run_id else "",
        )

        if cur_supplied:
            total_cost_tasks += 1
            coverage = cost_coverage_runs.setdefault(
                run_group_key,
                {
                    "run_id": run_id,
                    "group": group,
                    "total_tasks": 0,
                    "matched_tasks": 0,
                    "missing_tasks": 0,
                    "missing_process_counts": defaultdict(int),
                },
            )
            coverage["total_tasks"] += 1
            if cost_row:
                matched_cost_tasks += 1
                coverage["matched_tasks"] += 1
            else:
                missing_cost_tasks += 1
                coverage["missing_tasks"] += 1
                missing_process = process_short or process or "unknown"
                coverage["missing_process_counts"][missing_process] += 1

        if cost_row:
            run_cost_acc[run_group_key]["cost"] += _cost_or_task(cost_row, "cost")
            run_cost_acc[run_group_key]["used_cost"] += _cost_or_task(cost_row, "used_cost")
            run_cost_acc[run_group_key]["unused_cost"] += _cost_or_task(cost_row, "unused_cost")

        if has_cost_rows:
            overview_key = (group, process_short)
            cost_group_acc[overview_key]["total_cost"] += _cost_or_task(cost_row, "cost")
            cost_group_acc[overview_key]["used_cost"] += _cost_or_task(cost_row, "used_cost")
            cost_group_acc[overview_key]["unused_cost"] += _cost_or_task(cost_row, "unused_cost")
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

        if status in {"COMPLETED", "CACHED"}:
            # Accumulate task-derived CPU/memory resource hours
            cpus = float(t.get("cpus") or 0)
            realtime_h = float(t.get("realtime_ms") or 0) / 3600000.0
            pcpu = float(t.get("pcpu") or 0)
            mem_bytes = float(t.get("memory_bytes") or 0)
            peak_rss = float(t.get("peak_rss") or 0) or float(t.get("rss") or 0)
            task_run_acc[run_id]["requested_cpu_h"] += cpus * realtime_h
            task_run_acc[run_id]["requested_mem_gib_h"] += (mem_bytes / (1024**3)) * realtime_h
            task_run_acc[run_id]["real_cpu_h"] += (pcpu / 100.0) * realtime_h
            task_run_acc[run_id]["real_mem_gib_h"] += (peak_rss / (1024**3)) * realtime_h

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

    # Enrich run_metrics with scheduler-performance layer fields
    for row in run_metrics:
        rid = row.get("run_id", "")
        acc = task_run_acc.get(rid)
        if not acc:
            continue
        req_cpu = acc["requested_cpu_h"]
        req_mem = acc["requested_mem_gib_h"]
        real_cpu = acc["real_cpu_h"]
        real_mem = acc["real_mem_gib_h"]

        row["requestedCpuH"] = _round(req_cpu, 2)
        row["requestedMemGibH"] = _round(req_mem, 2)
        row["realCpuH"] = _round(real_cpu, 2)
        row["realMemGibH"] = _round(real_mem, 2)

        vm_cpu = row.get("vmCpuH")
        vm_mem = row.get("vmMemGibH")
        sched_cpu_eff = row.get("schedAllocCpuEfficiency")
        sched_mem_eff = row.get("schedAllocMemEfficiency")

        row["requestedVmCpuEfficiency"] = _round(
            (req_cpu / vm_cpu * 100.0) if vm_cpu and vm_cpu > 0 else None, 2
        )
        row["requestedVmMemEfficiency"] = _round(
            (req_mem / vm_mem * 100.0) if vm_mem and vm_mem > 0 else None, 2
        )

        booked_cpu = _compute_scheduler_booked(vm_cpu, sched_cpu_eff, req_cpu)
        booked_mem = _compute_scheduler_booked(vm_mem, sched_mem_eff, req_mem)
        row["schedulerBookedCpuH"] = _round(booked_cpu, 2)
        row["schedulerBookedMemGibH"] = _round(booked_mem, 2)

        row["schedulerRightsizedCpuH"] = _round(_positive_gap(req_cpu, booked_cpu), 2)
        row["schedulerRightsizedMemGibH"] = _round(_positive_gap(req_mem, booked_mem), 2)
        row["schedulerOverbookCpuH"] = _round(_positive_gap(booked_cpu, real_cpu), 2)
        row["schedulerOverbookMemGibH"] = _round(_positive_gap(booked_mem, real_mem), 2)
        row["vmPackingSlackCpuH"] = _round(_positive_gap(vm_cpu, booked_cpu), 2)
        row["vmPackingSlackMemGibH"] = _round(_positive_gap(vm_mem, booked_mem), 2)

        row["realVmCpuEfficiency"] = _round(
            (real_cpu / vm_cpu * 100.0) if vm_cpu and vm_cpu > 0 else None, 2
        )
        row["realVmMemEfficiency"] = _round(
            (real_mem / vm_mem * 100.0) if vm_mem and vm_mem > 0 else None, 2
        )

    benchmark_overview.sort(key=lambda x: (str(x.get("pipeline", "")), str(x.get("group", ""))))
    run_summary.sort(key=lambda x: str(x.get("group", "")))
    run_metrics.sort(key=lambda x: str(x.get("group", "")))

    now = datetime.now(timezone.utc)
    run_costs = []
    for row in run_cost_acc.values():
        run_id = row["run_id"]
        group = row["group"]
        session_id = lineage.get(run_id, {}).get("session_id", "")
        owns_session = bool(session_id) and session_owners.get(session_id) == run_id
        pool = pools["by_session"].get(session_id) if owns_session else None

        if not cur_supplied:
            # No CUR file at all — cost analysis is off, keep prior behaviour.
            cost_status = None
        else:
            coverage = cost_coverage_runs.get((run_id, group))
            matched = int(coverage["matched_tasks"]) if coverage else 0
            has_pool = bool(pool) and pool["cost"] != 0.0
            cost_status = (
                "available"
                if matched > 0 or has_pool
                else _classify_missing_cost(run_end_ts.get(run_id), now)
            )
        missing = cost_status in ("propagating", "not_found")

        # A RESUMED run is billed across its whole session, not just its own attempt.
        # `cost` is therefore the session pool — every attempt's spend — while
        # `cost_last_attempt` keeps this attempt alone, because any figure divided by a
        # duration or a machine-hour count must use the attempt those denominators
        # describe (run duration and the machines CSV both cover the last attempt only).
        #
        # The attempt figure comes from `by_run` (rows carrying THIS workflow id), not from
        # the per-task accumulation above: once cached tasks resolve through the session
        # index, that accumulation deliberately includes money an earlier attempt spent.
        # For a pooled run with no rows of its own — the shape of a resume whose own costs
        # have not landed yet — the attempt figure is unknown, NOT zero and not the pool.
        attempt_pool = pools["by_run"].get(run_id)
        if attempt_pool is not None:
            attempt_cost = _round(attempt_pool["cost"], 2)
        else:
            attempt_cost = None if owns_session else _round(row["cost"], 2)
        billed_attempts = pools["session_attempts"].get(session_id, set()) if owns_session else set()
        # Attempts OTHER than this one that the pooled cost came from. This is the figure the
        # reports show, because it is true whether or not this attempt has landed in the export
        # yet, while a bare attempt count is ambiguous about which attempts it includes.
        earlier_attempts = len(billed_attempts - {run_id})
        attempts = max(len(billed_attempts), 1)
        if pool is not None:
            cost = _round(pool["cost"], 2)
            used_cost = _round(pool["used_cost"], 2)
            unused_cost = _round(pool["unused_cost"], 2)
        else:
            cost = _round(row["cost"], 2)
            used_cost = _round(row["used_cost"], 2) if has_cost_rows else None
            unused_cost = _round(row["unused_cost"], 2) if has_cost_rows else None

        run_costs.append(
            {
                "run_id": run_id,
                "group": group,
                "cost": None if missing else cost,
                "used_cost": None if missing else used_cost,
                "unused_cost": None if missing else unused_cost,
                "cost_status": cost_status,
                # Resume provenance for the cost cell. `earlier_attempts` == 0 means nothing
                # was pooled in, so cost is this attempt's own charge and the report says
                # nothing extra. cost_last_attempt is None when this attempt has no rows of
                # its own yet, which is exactly when the whole figure came from earlier ones.
                "cost_last_attempt": None if missing else attempt_cost,
                "attempts": attempts,
                "earlier_attempts": earlier_attempts,
                "session_pooled": pool is not None,
            }
        )
    run_costs.sort(key=lambda x: str(x.get("group", "")))

    # Backfill the billed-attempt count onto the run summary so the resume badge and the
    # cost column agree on how many attempts the money came from.
    attempts_by_run = {row["run_id"]: row for row in run_costs}
    for row in run_summary:
        cost_row = attempts_by_run.get(row["run_id"])
        row["attempts"] = cost_row["attempts"] if cost_row else 1
        row["earlier_attempts"] = cost_row["earlier_attempts"] if cost_row else 0

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

    runs_with_missing_costs = []
    for row in cost_coverage_runs.values():
        if int(row["missing_tasks"]) <= 0:
            continue
        missing_processes, missing_process_summary = _summarize_missing_processes(row["missing_process_counts"])
        runs_with_missing_costs.append(
            {
                "run_id": row["run_id"],
                "group": row["group"],
                "total_tasks": int(row["total_tasks"]),
                "matched_tasks": int(row["matched_tasks"]),
                "missing_tasks": int(row["missing_tasks"]),
                "missing_processes": missing_processes,
                "missing_process_summary": missing_process_summary,
            }
        )
    runs_with_missing_costs.sort(key=lambda row: (-row["missing_tasks"], str(row["group"]), str(row["run_id"])))

    # Resume provenance, plus the "did we find every task's money?" check. A pooled run
    # reports how many tasks its final attempt has (cached + executed) and the session's CUR
    # rows cover some number of distinct task hashes. Fewer hashes than tasks means part of
    # the lineage never made it into this export — an attempt outside the CUR window, in
    # another account, or with the session label missing — so the pooled total is a floor,
    # not the full bill. That has to be said out loud rather than shown as a clean number.
    resumed_runs = []
    for row in run_costs:
        if not row["session_pooled"]:
            continue
        run_id = row["run_id"]
        session_id = lineage.get(run_id, {}).get("session_id", "")
        coverage = cost_coverage_runs.get((run_id, row["group"])) or {}
        total_tasks = int(coverage.get("total_tasks") or 0)
        pool_tasks = len(pools["session_hashes"].get(session_id, ()))
        incomplete = total_tasks > 0 and pool_tasks < total_tasks
        resumed_runs.append(
            {
                "run_id": run_id,
                "group": row["group"],
                "session_id": session_id,
                "attempts": row["attempts"],
                "earlier_attempts": row["earlier_attempts"],
                "cached_tasks": lineage.get(run_id, {}).get("cached", 0),
                "total_tasks": total_tasks,
                "pool_task_count": pool_tasks,
                "cost": row["cost"],
                "cost_last_attempt": row["cost_last_attempt"],
                "lineage_incomplete": incomplete,
            }
        )
        if incomplete:
            print(
                f"WARNING: run {run_id} resumed a session with {row['attempts']} billed "
                f"attempt(s), but its CUR rows cover only {pool_tasks} of {total_tasks} "
                f"tasks. Pooled cost {row['cost']} is a lower bound — part of session "
                f"{session_id} is missing from the export.",
                file=sys.stderr,
            )

    resumed_runs.sort(key=lambda item: (str(item["group"]), str(item["run_id"])))

    cost_coverage = {
        "cur_supplied": cur_supplied,
        "has_any_cost_rows": has_cost_rows,
        "total_included_tasks": total_cost_tasks,
        "matched_task_count": matched_cost_tasks,
        "missing_task_count": missing_cost_tasks,
        "coverage_pct": _round((matched_cost_tasks / total_cost_tasks) * 100.0, 1) if total_cost_tasks else None,
        "runs_with_missing_costs": runs_with_missing_costs,
        # Runs whose cost was pooled across resume attempts (empty when nothing was resumed).
        "resumed_runs": resumed_runs,
        "n_resumed_runs": len(resumed_runs),
        "n_incomplete_lineages": sum(1 for item in resumed_runs if item["lineage_incomplete"]),
    }

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
        "cost_coverage": cost_coverage,
    }


def aggregate_report_data(jsonl_dir: Path, output: Path, include_failed_runs: bool = False) -> None:
    data = build_report_data(jsonl_dir, include_failed_runs=include_failed_runs)
    output.write_text(json.dumps(data, default=str))
