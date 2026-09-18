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
