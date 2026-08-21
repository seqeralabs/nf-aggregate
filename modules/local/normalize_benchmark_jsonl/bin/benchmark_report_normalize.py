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
    # `user_workflow_id`/`user_session_id` are a shorter variant seen in real exports
    # alongside the two above; they carried real, otherwise-unattributed spend in the SciDev
    # Intelligent Compute export (76 rows, $1.07 split cost), so they are tried last.
    "run_id": ["user_seqera_io_platform_workflow_id", "user_unique_run_id", "user_workflow_id"],
    # Nextflow session id — STABLE ACROSS RESUMES, unlike every run-id label above.
    # `-resume` mints a new workflow id, so an attempt's spend is tagged with an id the
    # samplesheet never mentions; the session id is what stitches the attempts back into
    # one lineage. Same CUR key normalisation as above: Intelligent Compute's
    # `nextflow.io/sessionId` becomes `user_nextflow_io_session_id`, and the Batch label
    # from the cost-tracking blog template (`pipelineSessionId`) becomes
    # `user_pipeline_session_id`. Override either with the `session_id` field of
    # benchmark_aws_cur_label_map, exactly as for the other three fields.
    "session_id": ["user_nextflow_io_session_id", "user_pipeline_session_id", "user_session_id"],
    "process": ["user_pipeline_process"],
    "task_hash": ["user_task_hash"],
}


def _unreadable_input_message(label: str, path: Path, exc: Exception) -> str:
    """Actionable text for an input that is present but cannot be read from the task.

    Written for the two ways this actually happens on Fusion, because the bare OS error
    ("Permission denied: 'data'") names a staged symlink and tells the operator nothing.
    """
    # DuckDB errors carry the whole failing statement; only its first line is useful here.
    reason = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return (
        f"{label} '{path}' exists but could not be read from inside the task ({reason}). "
        "On AWS this is almost always the compute environment's role missing "
        "s3:ListBucket and s3:GetObject on that bucket/prefix — a directory input needs "
        "LIST, not just object read. Grant those, or point the parameter at a single "
        "*.parquet file instead of the export directory."
    )


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


def _path_status(path: Path) -> str:
    """``"present"`` | ``"absent"`` | ``"unreadable"`` — for a staged input path. Never raises.

    ``Path.exists()`` is NOT safe on the paths this stage is handed. Nextflow stages inputs as
    symlinks in the task directory, and with Fusion those resolve into the NFS mount, where a
    lookup can fail with EACCES — an S3 403, or a prefix the client will not stat — instead of
    ENOENT. Python 3.12's ``Path.exists()`` only swallows ENOENT/ENOTDIR/EBADF/ELOOP
    (``pathlib._IGNORED_ERRNOS``), so EACCES propagated and killed the whole report over an
    OPTIONAL input, after runs/tasks/metrics had already been written. Python 3.13+ swallows it
    and would instead produce a silently cost-free report. Neither is acceptable, so presence
    and readability are answered separately and the caller decides.
    """
    try:
        path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return "absent"
    except OSError:
        # EACCES/EIO/ESTALE... — something is there, we just cannot inspect it from here.
        return "unreadable"
    return "present"


def _require_readable(label: str, path: Path) -> bool:
    """``True`` if present, ``False`` if absent; raises when present-but-unreadable.

    The shape most callers want, built on :func:`_path_status`: an optional input that is
    genuinely missing is skipped, but one that exists and cannot be read is never quietly
    treated as missing — that is how a permission problem turns into a report that looks
    complete. Shared with the aggregate and render stages, which stage their inputs the same
    way and so carry the same exposure.
    """
    try:
        path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError as exc:
        raise RuntimeError(_unreadable_input_message(label, path, exc)) from exc
    return True


def load_run_data(data_dir: Path) -> list[dict[str, Any]]:
    runs = []
    try:
        run_files = sorted(data_dir.glob("*.json"))
    except OSError as exc:
        raise RuntimeError(_unreadable_input_message("run data directory", data_dir, exc)) from exc
    for run_file in run_files:
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
                # Session id is the run's identity ACROSS resumes; run_id identifies one
                # attempt. `resumed` is true when this attempt reused earlier work, so its
                # own workflow id cannot account for all the money the pipeline spent —
                # aggregation then pools cost by session. Cached tasks are the detector
                # (Platform reports `resume` only for API-launched resumes, and a resume
                # that cache-hits nothing has nothing to pool anyway).
                "session_id": wf.get("sessionId") or "",
                "resumed": bool(wf.get("resume")) or int(stats.get("cachedCount", 0) or 0) > 0,
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


def _duckdb_glob(costs_parquet: Path) -> list[str]:
    """The scan pattern to hand DuckDB when Python cannot inspect the path itself.

    Used when ``stat``/``rglob`` fail on a staged path (see :func:`_path_status`): DuckDB does
    its own globbing and opening, so it may succeed where our directory walk could not, and
    when it cannot it reports the failure with the real path in the message.
    """
    if costs_parquet.suffix == ".parquet":
        return [str(costs_parquet)]
    return [str(costs_parquet / "**" / "*.parquet")]


def _parquet_sources(costs_parquet: Path) -> list[str]:
    """Resolve a file or directory into the parquet files DuckDB should scan.

    A directory is expanded to every ``*.parquet`` beneath it so a whole CUR
    export folder can be processed in one pass.

    Every filesystem probe here is fallible on a Nextflow-staged path — on Fusion the symlink
    resolves into the NFS mount, where ``is_dir()``/``rglob()`` can raise EACCES rather than
    answering. A probe that cannot answer defers to DuckDB instead of aborting, so a path we
    merely cannot *walk* is still given a chance to be *read*.
    """
    try:
        is_dir = costs_parquet.is_dir()
    except OSError:
        return _duckdb_glob(costs_parquet)

    if is_dir:
        try:
            sources = sorted(str(path) for path in costs_parquet.rglob("*.parquet"))
        except OSError:
            return _duckdb_glob(costs_parquet)
        if not sources:
            raise ValueError(f"benchmark_aws_cur_report directory '{costs_parquet}' contains no *.parquet files")
        return sources
    if costs_parquet.suffix != ".parquet":
        raise ValueError(
            f"benchmark_aws_cur_report '{costs_parquet}' is not a .parquet file or a directory of them. "
            "Pass the CUR export location itself (e.g. s3://bucket/prefix/), not an AWS console URL."
        )
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
        # element_at(map, key) returns a LIST of matching values on EVERY DuckDB
        # version; take [1] for the scalar. `map['key']` is NOT portable: it
        # returns a list on DuckDB <=1.1 (so [1] picks the element) but a scalar
        # on >=1.2 (so [1] picks the first CHARACTER), silently corrupting ids.
        return f"element_at(resource_tags, '{escaped}')[1]"
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


def _market_option_expr(columns: dict[str, str]) -> str:
    """``'Spot'`` / ``'OnDemand'`` for an EC2 instance-hour row, NULL for anything else.

    Gated on ``line_item_usage_type`` in BOTH branches, and deliberately so — the gate is
    what makes the classification trustworthy, not a nicety:

      - Only the instance-hour rows (``SpotUsage:<type>`` / ``BoxUsage:<type>``) describe
        machine rental. The EBS volumes and data transfer AWS also tags to the run carry no
        purchase option at all, so forcing them into a bucket would invent one.
      - ``product_marketoption`` is wrong on the EBSOptimized surcharge row: a Spot instance's
        surcharge is labelled ``OnDemand``. Ungated, that made 56,894 instance ids in a real
        export look like they had two purchase options at once.

    ``product_marketoption`` is the authoritative field but only legacy CUR flattens it (CUR
    2.0 nests it inside the ``product`` map), so the usage type — present in every CUR
    version, and the very string the market option is derived from — is the fallback.
    """
    if "line_item_usage_type" not in columns:
        return "NULL"
    usage_type = 'CAST("line_item_usage_type" AS VARCHAR)'
    is_spot = f"{usage_type} LIKE '%SpotUsage%'"
    instance_hour = f"({is_spot} OR {usage_type} LIKE '%BoxUsage%')"
    if "product_marketoption" in columns:
        market = "NULLIF(CAST(\"product_marketoption\" AS VARCHAR), '')"
    else:
        market = f"CASE WHEN {is_spot} THEN 'Spot' ELSE 'OnDemand' END"
    return f"CASE WHEN {instance_hour} THEN {market} END"


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

    Each output row carries both cost bases separately — ``unblended_cost`` (instance)
    and ``split_cost``/``unused_cost`` (ECS split cost allocation) — because they can
    describe the *same* compute and must never be added together. See the comment on the
    query below for why. ``cost``/``used_cost`` are single-basis conveniences.

    ``spot_cost``/``ondemand_cost`` decompose the machine share of ``unblended_cost`` by EC2
    purchase option. They are a subset of that one basis, never a third one.

    Rows are grained by ``(run_id, session_id, process, hash)``. ``session_id`` is what makes
    a resumed run's earlier attempts findable: each attempt carries its own workflow id but
    they all share one session id.
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
    session_id_expr = _label_expr(label_aliases["session_id"], columns)
    process_expr = _label_expr(label_aliases["process"], columns)
    task_hash_expr = _label_expr(label_aliases["task_hash"], columns)

    # TWO DISTINCT COST BASES, NEVER SUMMED.
    #
    # AWS adds split cost allocation rows *in addition to* the parent EC2 instance rows they
    # were derived from — "two new usage records are added for each ECS task ... per hour"
    # (https://docs.aws.amazon.com/cur/latest/userguide/split-cost-allocation-data.html).
    # The parent charge is not zeroed; it is the quantity being split, so Σ(split + unused)
    # over an instance's tasks reproduces that instance's own cost. Adding both therefore
    # counts the same compute twice.
    #
    # This bit Intelligent Compute specifically: the scheduler tags the EC2 instances, so
    # both the instance rows AND the ECS split rows for tasks on them carry the run-id tag
    # and both used to land in one total. AWS Batch tags only the ECS task, so its instance
    # rows carry no run tag and never matched.
    #
    # So the bases are kept apart:
    #   unblended_cost  instance-basis charge (what was actually billed, incl. idle/boot)
    #   split_cost      consumed capacity, from ECS split line items (amortized)
    #   unused_cost     provisioned-but-idle capacity, from ECS split line items
    # ``cost``/``used_cost`` remain the single-basis figures the benchmark report consumes:
    # the billed instance charge when this group has one, else the split basis. Intelligent
    # Compute needs both bases side by side, so it reads the three raw fields instead.
    #
    # A single group CAN hold both bases. Intelligent Compute's split rows carry no
    # ``pipeline_process``/``task_hash`` labels (verified across a real export: 0 of 49,106),
    # so they collapse into the same ``(run_id, '', '')`` key as the instance rows. That is
    # exactly why the bases are summed independently rather than deduplicated by row class —
    # by the time rows are grouped, the classes are no longer separable. AWS Batch is
    # unaffected either way: its instance rows carry no run tag, so its groups are split-only.
    split_cost = _numeric_expr("split_line_item_split_cost", columns)
    unused_cost = _numeric_expr("split_line_item_unused_cost", columns)
    unblended_cost = _numeric_expr("line_item_unblended_cost", columns)
    is_split_row = f"CASE WHEN {split_cost} <> 0 OR {unused_cost} <> 0 THEN 1 ELSE 0 END"

    # SPOT vs ON-DEMAND: a decomposition of the machine share of ``unblended_cost``, on that
    # one basis always — never the split basis, which carries no purchase option of its own
    # (AWS emits the ECS split rows under product code AmazonECS with the market option blank).
    # Reaching it through the split rows' ``split_line_item_parent_resource_id`` back to the
    # parent instance row is possible but would make the figure available on one architecture
    # and not the other; the unblended rows carry the option directly and exist for every
    # Intelligent Compute run, ECS or VM. Only IC labels its instances, so only IC gets a
    # non-zero split here — see _run_cost_details, which is where the IC-only rule is applied.
    #
    # These are a PART of unblended_cost, never an addition to it, and they do not sum back to
    # it: the EBS volumes and data transfer AWS tags to the same run are not machine rental and
    # belong to neither bucket. spot + ondemand <= unblended is the expected relationship.
    market_option = _market_option_expr(columns)
    spot_cost = f"CASE WHEN {market_option} = 'Spot' THEN {unblended_cost} ELSE 0.0 END"
    ondemand_cost = f"CASE WHEN {market_option} = 'OnDemand' THEN {unblended_cost} ELSE 0.0 END"

    # SESSION ID is carried alongside the run id, never instead of it. Grouping by both keeps
    # every row attributable to the attempt that incurred it while still letting aggregation
    # pool a resumed run's attempts by session (see ``_session_cost_pool``). It is NOT a
    # replacement join key: the label is absent from plenty of exports, and swapping to it
    # would turn "this export has no session label" into a silent $0.
    query = f"""
        WITH classified AS (
            SELECT
                {run_id_expr}                                 AS run_id,
                COALESCE({session_id_expr}, '')               AS session_id,
                COALESCE({process_expr}, '')                  AS process,
                substr(COALESCE({task_hash_expr}, ''), 1, 8)  AS hash,
                {unblended_cost}                              AS unblended_cost,
                {split_cost}                                  AS split_cost,
                {unused_cost}                                 AS unused_cost,
                {spot_cost}                                   AS spot_cost,
                {ondemand_cost}                               AS ondemand_cost,
                {is_split_row}                                AS is_split_row
            FROM {scan}
            WHERE {run_id_expr} IS NOT NULL AND {run_id_expr} <> ''
        )
        SELECT
            run_id,
            session_id,
            process,
            hash,
            SUM(unblended_cost)  AS unblended_cost,
            SUM(split_cost)      AS split_cost,
            SUM(unused_cost)     AS unused_cost,
            SUM(spot_cost)       AS spot_cost,
            SUM(ondemand_cost)   AS ondemand_cost,
            MAX(is_split_row)    AS split_cost_present,
            CASE WHEN SUM(unblended_cost) <> 0
                 THEN SUM(unblended_cost)
                 ELSE SUM(split_cost) + SUM(unused_cost) END AS cost,
            CASE WHEN SUM(unblended_cost) <> 0
                 THEN SUM(unblended_cost)
                 ELSE SUM(split_cost) END AS used_cost
        FROM classified
        GROUP BY 1, 2, 3, 4
        ORDER BY 1, 2, 3, 4
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
    try:
        csv_paths = sorted(machines_dir.glob("*.csv"))
    except OSError as exc:
        # Matches the caller's policy: machine telemetry degrades, it never fails the report.
        typer.echo(_unreadable_input_message("machines directory", machines_dir, exc), err=True)
        return []
    for csv_path in csv_paths:
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

    # COST DATA. `NO_FILE` is checked before touching the filesystem: it is a placeholder, and
    # stat'ing a staged path is the fallible step (see _path_status), so the cheap certain test
    # goes first. An unreadable path is still handed to DuckDB — the stat can fail on a Fusion
    # prefix while the parquet files underneath open fine — and only a DuckDB failure is fatal.
    # Fatal, not skipped: cost analysis was explicitly requested, and quietly emitting a report
    # with no costs.jsonl is indistinguishable from "no CUR was supplied".
    if costs_parquet and costs_parquet.name != "NO_FILE":
        cost_status = _path_status(costs_parquet)
        if cost_status != "absent":
            try:
                cost_rows = _normalize_cost_rows(costs_parquet, cost_label_map=cost_label_map)
            except Exception as exc:
                if cost_status == "unreadable":
                    raise RuntimeError(
                        _unreadable_input_message("benchmark_aws_cur_report", costs_parquet, exc)
                    ) from exc
                raise
            _write_jsonl(output_dir / "costs.jsonl", cost_rows)

    # MACHINE TELEMETRY is supplementary per-run detail, not money, so an unreadable directory
    # warns and moves on rather than failing the report.
    if machines_dir and _path_status(machines_dir) != "absent":
        try:
            machine_csvs = any(machines_dir.glob("*.csv"))
        except OSError as exc:
            typer.echo(_unreadable_input_message("machines directory", machines_dir, exc), err=True)
            machine_csvs = False
        if machine_csvs:
            machine_rows = _summarise_machines(machines_dir)
            if machine_rows:
                _write_jsonl(output_dir / "machines.jsonl", machine_rows)

    typer.echo(f"JSONL bundle written to {output_dir}")
