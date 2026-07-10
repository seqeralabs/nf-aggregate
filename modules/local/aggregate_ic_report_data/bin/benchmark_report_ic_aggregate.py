#!/usr/bin/env python3
"""Aggregate the JSONL bundle into an Intelligent Compute report_data_ic.json."""

from __future__ import annotations

import json
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


def build_ic_report_data(jsonl_dir: Path, web_base: str = "https://cloud.seqera.io") -> dict[str, Any]:
    run_summary: list[dict[str, Any]] = []
    n_ic = 0
    n_batch = 0

    for run in _iter_jsonl(Path(jsonl_dir) / "runs.jsonl"):
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

        run_summary.append({
            "run_id": run_id,
            "run_url": _build_workspace_run_url(
                run_id, run.get("workspace"), web_base, existing_url=run.get("run_url")
            ),
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

    return {
        "ic_overview": {
            "n_runs": len(run_summary),
            "n_intelligent_compute": n_ic,
            "n_batch": n_batch,
            "cost_source": None,
        },
        "run_summary": run_summary,
    }


def aggregate_ic_report_data(
    jsonl_dir: Path, output: Path, web_base: str = "https://cloud.seqera.io"
) -> None:
    data = build_ic_report_data(jsonl_dir, web_base=web_base)
    Path(output).write_text(json.dumps(data, indent=2, default=str))
