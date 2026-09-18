#!/usr/bin/env python3
"""Extract per-run costs from a Google Cloud Billing BigQuery export.

The AWS CUR path and this one converge on one file — ``costs.jsonl`` — which is why
nothing downstream of normalization knows which cloud a report's money came from. See
``docs/superpowers/specs/2026-09-18-gcp-cost-attribution-design.md``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DEFAULT_GCP_COST_LABEL_ALIASES: dict[str, list[str]] = {
    # Label keys AS THEY APPEAR IN A BILLING EXPORT. Unlike AWS there is no `user_` prefix,
    # and — the trap — the separator is a DASH. These labels are applied by the Seqera
    # scheduler, which sanitises with dashes; Nextflow's own ResourceLabelPolicy.GOOGLE
    # sanitises with underscores. Verified against a real export (2026-09-18): 53,046 rows
    # / $133.67 carried `seqera-io-platform-workflowid`, none carried an underscored form.
    #
    # `unique-run-id` is the AWS Batch cost-tracking blog template translated to GCP. It
    # appeared on 177 rows / $0.007 — configured once, essentially unused — so it is tried
    # after the scheduler label but kept, because it is the ONLY way a Google Batch row
    # carries a run id at all.
    "run_id": ["seqera-io-platform-workflowid", "unique-run-id", "workflow-id"],
    # Session id survives `-resume` where every run-id label names one attempt only.
    "session_id": ["nextflow-io-sessionid", "pipeline-session-id", "session-id"],
    # NOT a user label: Google Batch stamps `batch-job-id` on every VM, disk and GPU it
    # creates, and Nextflow's job id embeds the task hash
    # (GoogleBatchTaskHandler.groovy:136). So the task grain is free on GCP, with nothing
    # configured. There is no process-name equivalent, which is why `process` is always "".
    "task_hash": ["batch-job-id"],
}

# `nf-<hash>-<millis>`; the hash is Nextflow's short task hash with the `/` removed.
_BATCH_JOB_ID = re.compile(r"^nf-([0-9a-f]+)-\d+$")


def _task_hash_from_job_id(value: str | None) -> str:
    """The 8-char task hash inside a Google Batch job id, or '' if this is not one.

    Truncated to 8 characters to land on exactly the grain the AWS path uses
    (``substr(task_hash, 1, 8)``), so both clouds group cost the same way.
    """
    if not value:
        return ""
    match = _BATCH_JOB_ID.match(str(value).strip())
    if not match:
        return ""
    return match.group(1)[:8]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        alias = str(value).strip()
        if not alias or alias in seen:
            continue
        seen.add(alias)
        result.append(alias)
    return result


def _normalise_aliases(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _dedupe([value])
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise ValueError(f"gcp_billing_label_map field '{field}' must contain only strings")
        return _dedupe(value)
    raise ValueError(f"gcp_billing_label_map field '{field}' must be a string or list of strings")


def load_gcp_cost_label_aliases(cost_label_map: Path | None = None) -> dict[str, list[str]]:
    """Merge user-supplied label aliases ahead of the defaults, same shape as the AWS map."""
    aliases = {field: list(defaults) for field, defaults in DEFAULT_GCP_COST_LABEL_ALIASES.items()}
    if cost_label_map is None or cost_label_map.name in {"NO_FILE", "NO_FILE_CUR_LABEL_MAP"}:
        return aliases

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - only hit without pyyaml installed
        raise RuntimeError("pyyaml is required to read a GCP billing label map") from exc

    with cost_label_map.open() as handle:
        raw_config = yaml.safe_load(handle) or {}
    if not isinstance(raw_config, dict):
        raise ValueError("gcp_billing_label_map must contain a YAML mapping")

    unknown = set(raw_config) - set(DEFAULT_GCP_COST_LABEL_ALIASES)
    if unknown:
        raise ValueError(
            f"gcp_billing_label_map contains unsupported fields: {', '.join(sorted(unknown))}"
        )

    for field, defaults in DEFAULT_GCP_COST_LABEL_ALIASES.items():
        aliases[field] = _dedupe(_normalise_aliases(raw_config.get(field), field) + defaults)
    return aliases


# project.dataset.table, each part restricted to what BigQuery actually allows. This is the
# ONLY defence against injection, because a table name cannot be a query parameter — it is
# interpolated into the FROM clause.
_TABLE_REF = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_$]+$")


def parse_gcp_table_ref(value: str) -> str:
    """Normalise a billing-export table reference, rejecting anything that is not one.

    Accepts `bq://` prefixes and the `project:dataset.table` form the `bq` CLI prints, so
    an operator can paste whichever spelling is in front of them.
    """
    table = str(value or "").strip()
    if table.startswith("bq://"):
        table = table[len("bq://"):]
    # `bq` prints project:dataset.table; BigQuery SQL wants all dots.
    table = table.replace(":", ".", 1)
    if not _TABLE_REF.match(table):
        raise ValueError(
            f"'{value}' is not a BigQuery table reference. Expected "
            "'project.dataset.table' (a 'bq://' prefix is also accepted), for example "
            "'tower-cloud-testing.all_billing_data.gcp_billing_export_v1_01F197_9D74B5_BC674D'."
        )
    return table


def _label_expr(aliases: list[str]) -> str:
    """COALESCE over the label aliases, each read out of the repeated `labels` struct.

    Empty strings are treated as absent, matching the AWS extractor: a label present but
    blank carries no more information than a missing one.
    """
    if not aliases:
        return "CAST(NULL AS STRING)"
    lookups = [
        "NULLIF((SELECT l.value FROM UNNEST(labels) l "
        f"WHERE l.key = '{alias}' LIMIT 1), '')"
        for alias in aliases
    ]
    return f"COALESCE({', '.join(lookups)})" if len(lookups) > 1 else lookups[0]


def build_gcp_cost_query(table: str, aliases: dict[str, list[str]]) -> str:
    """One aggregating query: the export is never downloaded, only its GROUP BY result.

    GROSS COST, DELIBERATELY. `cost` excludes credits, and credits are not added back —
    a negotiated discount applying to one engine and not the other would taint a
    Batch-vs-SIC comparison (spec D2). The known cost of this choice is measured in the
    spec: sustained-use discount is ~4% of scheduler spend and ~0.2% of Batch spend.

    NO SERVICE FILTER. Any row carrying a run label is counted, exactly as on AWS, so
    storage or networking tagged to a run is not silently discarded.
    """
    run_id_expr = _label_expr(aliases["run_id"])
    session_expr = _label_expr(aliases["session_id"])
    hash_expr = _label_expr(aliases["task_hash"])

    # PURCHASE OPTION IS GATED TO MACHINE SKUs, for the same reason the AWS extractor gates
    # on line_item_usage_type: the disks and networking Google labels to the same run are
    # not machine rental. Measured in the real export, disks alone were ~$20 across both
    # engines. So spot + ondemand < unblended is expected, never a bug.
    is_machine = r"REGEXP_CONTAINS(sku.description, r'(?i)instance (core|ram)')"
    is_spot = r"REGEXP_CONTAINS(sku.description, r'(?i)spot|preemptible')"

    return f"""
        WITH labelled AS (
            SELECT
                cost,
                {run_id_expr}  AS run_id_raw,
                {session_expr} AS session_id_raw,
                REGEXP_EXTRACT({hash_expr}, r'^nf-([0-9a-f]+)-[0-9]+$') AS hash_raw,
                {is_machine} AS is_machine,
                {is_spot}    AS is_spot
            FROM `{table}`
        )
        SELECT
            IFNULL(run_id_raw, '')            AS run_id,
            IFNULL(session_id_raw, '')        AS session_id,
            IFNULL(SUBSTR(hash_raw, 1, 8), '') AS hash,
            SUM(cost)                          AS unblended_cost,
            SUM(IF(is_machine AND is_spot, cost, 0.0))     AS spot_cost,
            SUM(IF(is_machine AND NOT is_spot, cost, 0.0)) AS ondemand_cost,
            COUNT(*)                           AS n_rows
        FROM labelled
        WHERE run_id_raw IS NOT NULL OR hash_raw IS NOT NULL
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    """
