# GCP Cost Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Intelligent Compute report read real per-run costs from a Google Cloud Billing BigQuery export, so Google Batch and Seqera scheduler (SIC) runs can be compared on money.

**Architecture:** A new extractor module turns one aggregating BigQuery query into the exact `costs.jsonl` row schema the AWS CUR path already emits. Because `costs.jsonl` is the seam that `_load_cost_pools` (`bin/benchmark_report_aggregate.py:160`) joins on, nothing downstream — aggregation, the IC aggregator, the template — changes at all. `normalize_jsonl` gains one more optional cost source and dispatches to it.

**Tech Stack:** Python 3.12, `google-cloud-bigquery`, typer, pytest, Nextflow DSL2.

**Spec:** `docs/superpowers/specs/2026-09-18-gcp-cost-attribution-design.md`

## Global Constraints

- **Never replace the AWS path.** `--costs` (CUR parquet) and `--gcp-billing-table` are independent sources. Supplying both is a user error and must fail with a clear message, not silently prefer one.
- **`bin/` is what the pipeline runs; `modules/local/*/bin/` is what the tests import.** After touching any `benchmark_report_*.py`, copy the module version over the `bin/` one and diff to confirm. `conftest.py` puts module bin dirs ahead of `bin/` on `sys.path`.
- **Gross cost only.** Never subtract `credits`. The one function that could is isolated so the decision can be revisited (spec D2).
- **Run id remains a required join key.** Rows with no run id are dropped, never attributed by task hash alone (spec D4).
- **`spot_cost + ondemand_cost <= unblended_cost`** is the expected relationship, because the purchase-option split covers machine SKUs only.
- Python target 3.12. Match surrounding comment density — this codebase explains *why*, at length, wherever a decision is non-obvious.
- Conventional commits + gitmoji, as in the existing history. `commit.gpgsign` is already true.
- Do not run `nextflow lint -format` on existing files — it is destructive.

---

## File Structure

**Create:**
- `modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py` — the whole GCP extractor. One responsibility: BigQuery billing export → `costs.jsonl` rows. Kept out of `benchmark_report_normalize.py`, which is already ~870 lines.
- `bin/benchmark_report_gcp_costs.py` — byte-identical copy (see Global Constraints).
- `modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py` — tests for the extractor. No network: the pure helpers are tested directly and the query path is tested against a fake client.

**Modify:**
- `bin/benchmark_report_normalize.py` + module copy — `normalize_jsonl` gains `gcp_billing_table`, dispatches, passes canonical run ids.
- `bin/benchmark_report.py` — new `--gcp-billing-table` CLI option.
- `modules/local/normalize_benchmark_jsonl/main.nf` — new value input + flag + conda dep.
- `workflows/nf_aggregate/main.nf` — param wiring.
- `nextflow.config`, `nextflow_schema.json` — new param.
- `AGENTS.md` — a Gotchas entry.
- `README.md` — usage.

---

### Task 1: GCP label aliases and task-hash extraction

The pure helpers, with no BigQuery involved. These encode the two findings that differ most from AWS: dash-separated label keys, and a task hash embedded in `batch-job-id`.

**Files:**
- Create: `modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py`
- Test: `modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DEFAULT_GCP_COST_LABEL_ALIASES: dict[str, list[str]]`, `_task_hash_from_job_id(value: str | None) -> str`, `load_gcp_cost_label_aliases(cost_label_map: Path | None) -> dict[str, list[str]]`.

- [ ] **Step 1: Write the failing tests**

```python
# modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py
import pytest

from benchmark_report_gcp_costs import (
    DEFAULT_GCP_COST_LABEL_ALIASES,
    _task_hash_from_job_id,
    load_gcp_cost_label_aliases,
)


def test_default_aliases_use_dash_separators():
    # The Seqera scheduler sanitises label keys with dashes, NOT the underscores
    # Nextflow's own ResourceLabelPolicy.GOOGLE would produce. Verified against a real
    # export: `seqera-io-platform-workflowid`, never `seqera_io_platform_workflowid`.
    assert DEFAULT_GCP_COST_LABEL_ALIASES["run_id"][0] == "seqera-io-platform-workflowid"
    assert DEFAULT_GCP_COST_LABEL_ALIASES["session_id"][0] == "nextflow-io-sessionid"
    assert DEFAULT_GCP_COST_LABEL_ALIASES["task_hash"] == ["batch-job-id"]
    assert not any(
        "_" in alias
        for aliases in DEFAULT_GCP_COST_LABEL_ALIASES.values()
        for alias in aliases
    )


@pytest.mark.parametrize(
    "job_id,expected",
    [
        ("nf-5dbefa9a-1789649298737", "5dbefa9a"),
        ("nf-f7d4a430-1789649478596", "f7d4a430"),
        ("nf-2690f9d0-1789649000571", "2690f9d0"),
        # Not a Nextflow job: a hand-submitted Batch job carries no task hash.
        ("my-own-batch-job", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_task_hash_extracted_from_batch_job_id(job_id, expected):
    assert _task_hash_from_job_id(job_id) == expected


def test_task_hash_truncated_to_eight_chars():
    # The AWS path keys on substr(task_hash, 1, 8); GCP must land on the same grain.
    assert _task_hash_from_job_id("nf-5dbefa9a0011-1789649298737") == "5dbefa9a"


def test_user_aliases_take_precedence_over_defaults(tmp_path):
    label_map = tmp_path / "labels.yml"
    label_map.write_text("run_id: my-own-run-label\n")
    aliases = load_gcp_cost_label_aliases(label_map)
    assert aliases["run_id"][0] == "my-own-run-label"
    assert "seqera-io-platform-workflowid" in aliases["run_id"]


def test_unknown_alias_field_rejected(tmp_path):
    label_map = tmp_path / "labels.yml"
    label_map.write_text("nonsense: whatever\n")
    with pytest.raises(ValueError, match="nonsense"):
        load_gcp_cost_label_aliases(label_map)


def test_no_label_map_returns_defaults():
    assert load_gcp_cost_label_aliases(None) == DEFAULT_GCP_COST_LABEL_ALIASES
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --with pytest --with pyyaml pytest modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'benchmark_report_gcp_costs'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --with pytest --with pyyaml pytest modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Copy to `bin/` and commit**

```bash
cd /Users/stefano.boriero/work/nf-aggregate
cp modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py bin/benchmark_report_gcp_costs.py
diff modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py bin/benchmark_report_gcp_costs.py
git add bin/benchmark_report_gcp_costs.py modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py
git commit -m "✨ feat(gcp): add billing-export label aliases and task-hash extraction"
```

---

### Task 2: The aggregating BigQuery query

One `GROUP BY` pushed into BigQuery, so the extractor never downloads the export.

**Files:**
- Modify: `modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py`
- Test: `modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py`

**Interfaces:**
- Consumes: `DEFAULT_GCP_COST_LABEL_ALIASES`, `load_gcp_cost_label_aliases` from Task 1.
- Produces: `parse_gcp_table_ref(value: str) -> str`, `build_gcp_cost_query(table: str, aliases: dict[str, list[str]]) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# append to modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py
from benchmark_report_gcp_costs import build_gcp_cost_query, parse_gcp_table_ref


@pytest.mark.parametrize(
    "value,expected",
    [
        ("proj.dataset.table", "proj.dataset.table"),
        ("bq://proj.dataset.table", "proj.dataset.table"),
        ("  proj.dataset.table  ", "proj.dataset.table"),
        ("proj:dataset.table", "proj.dataset.table"),
    ],
)
def test_table_ref_accepted_forms(value, expected):
    assert parse_gcp_table_ref(value) == expected


@pytest.mark.parametrize("value", ["", "notatable", "proj.dataset", "a.b.c.d", "proj.data set.table"])
def test_table_ref_rejects_malformed(value):
    with pytest.raises(ValueError, match="BigQuery table"):
        parse_gcp_table_ref(value)


def test_table_ref_rejects_sql_injection():
    with pytest.raises(ValueError, match="BigQuery table"):
        parse_gcp_table_ref("proj.dataset.table` UNION SELECT 1 --")


def test_query_groups_by_run_session_and_hash():
    sql = build_gcp_cost_query("p.d.t", DEFAULT_GCP_COST_LABEL_ALIASES)
    assert "GROUP BY 1, 2, 3" in sql
    assert "`p.d.t`" in sql


def test_query_reads_every_run_id_alias_in_order():
    sql = build_gcp_cost_query("p.d.t", DEFAULT_GCP_COST_LABEL_ALIASES)
    positions = [sql.index(alias) for alias in DEFAULT_GCP_COST_LABEL_ALIASES["run_id"]]
    assert positions == sorted(positions), "aliases must be tried in declared order"


def test_query_never_subtracts_credits():
    # Spec D2: gross cost. A credits join would silently change every figure.
    sql = build_gcp_cost_query("p.d.t", DEFAULT_GCP_COST_LABEL_ALIASES)
    assert "credits" not in sql.lower()


def test_query_gates_purchase_option_to_machine_skus():
    # Disks and networking are labelled to the same run but are not machine rental.
    sql = build_gcp_cost_query("p.d.t", DEFAULT_GCP_COST_LABEL_ALIASES)
    assert "instance (core|ram)" in sql
    assert "spot|preemptible" in sql


def test_query_keeps_rows_with_a_hash_but_no_run_id():
    # They are dropped later, but only after being counted for the diagnostic (spec D4).
    sql = build_gcp_cost_query("p.d.t", DEFAULT_GCP_COST_LABEL_ALIASES)
    assert "run_id_raw IS NOT NULL OR hash_raw IS NOT NULL" in sql
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --with pytest --with pyyaml pytest modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py -v -k "table_ref or query"`
Expected: FAIL — `ImportError: cannot import name 'build_gcp_cost_query'`

- [ ] **Step 3: Write the implementation**

Append to `benchmark_report_gcp_costs.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --with pytest --with pyyaml pytest modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py -v`
Expected: PASS (all tests from Tasks 1 and 2)

- [ ] **Step 5: Copy to `bin/` and commit**

```bash
cp modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py bin/benchmark_report_gcp_costs.py
diff modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py bin/benchmark_report_gcp_costs.py
git add -A && git commit -m "✨ feat(gcp): build the aggregating BigQuery cost query"
```

---

### Task 3: Map query results to `costs.jsonl` rows

Where the canonical-case remap (spec D3) and the unattributed-spend diagnostic (spec D4) live.

**Files:**
- Modify: `modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py`
- Test: `modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py`

**Interfaces:**
- Consumes: Task 2's query result shape — dicts with keys `run_id`, `session_id`, `hash`, `unblended_cost`, `spot_cost`, `ondemand_cost`, `n_rows`.
- Produces: `gcp_rows_to_cost_rows(raw_rows: list[dict], known_run_ids: list[str]) -> tuple[list[dict], dict[str, Any]]`.

- [ ] **Step 1: Write the failing tests**

```python
# append to modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py
from benchmark_report_gcp_costs import gcp_rows_to_cost_rows


def _raw(**overrides):
    row = {
        "run_id": "nnjl9fvczoruf",
        "session_id": "92096d14-b89e-40f2-bbc8-71168f972329",
        "hash": "",
        "unblended_cost": 10.0,
        "spot_cost": 6.0,
        "ondemand_cost": 2.0,
        "n_rows": 5,
    }
    row.update(overrides)
    return row


def test_emits_the_aws_cost_row_schema():
    rows, _ = gcp_rows_to_cost_rows([_raw()], ["nnjl9fvczoruf"])
    assert set(rows[0]) == {
        "run_id", "session_id", "process", "hash",
        "unblended_cost", "split_cost", "unused_cost",
        "spot_cost", "ondemand_cost", "split_cost_present",
        "cost", "used_cost",
    }


def test_single_basis_has_no_split_cost():
    # GCP has no ECS split-cost-allocation analogue, so the second basis is always absent.
    rows, _ = gcp_rows_to_cost_rows([_raw()], ["nnjl9fvczoruf"])
    row = rows[0]
    assert row["split_cost"] == 0.0
    assert row["unused_cost"] == 0.0
    assert row["split_cost_present"] == 0
    assert row["cost"] == row["used_cost"] == row["unblended_cost"] == 10.0


def test_run_id_remapped_to_canonical_case():
    # Billing lowercases label values; Platform run ids are mixed case, and _load_cost_pools
    # joins on an exact string.
    rows, _ = gcp_rows_to_cost_rows([_raw(run_id="4bi5xbk6e2nbhj")], ["4Bi5xBK6E2Nbhj"])
    assert rows[0]["run_id"] == "4Bi5xBK6E2Nbhj"


def test_unknown_run_id_passes_through_unchanged():
    rows, _ = gcp_rows_to_cost_rows([_raw(run_id="somebodyelse")], ["4Bi5xBK6E2Nbhj"])
    assert rows[0]["run_id"] == "somebodyelse"


def test_process_is_always_blank():
    # There is no process-name label on GCP; the field exists only for schema parity.
    rows, _ = gcp_rows_to_cost_rows([_raw()], ["nnjl9fvczoruf"])
    assert rows[0]["process"] == ""


def test_rows_without_a_run_id_are_dropped():
    rows, _ = gcp_rows_to_cost_rows([_raw(run_id="", hash="5dbefa9a")], ["nnjl9fvczoruf"])
    assert rows == []


def test_dropped_google_batch_spend_is_reported():
    # Spec D4: today this is ALL Google Batch spend, so silence would read as $0.
    raw = [
        _raw(run_id="", hash="5dbefa9a", unblended_cost=30.0, n_rows=100),
        _raw(run_id="", hash="f7d4a430", unblended_cost=19.78, n_rows=200),
        _raw(),
    ]
    rows, diagnostics = gcp_rows_to_cost_rows(raw, ["nnjl9fvczoruf"])
    assert len(rows) == 1
    assert diagnostics["unattributed_batch_cost"] == 49.78
    assert diagnostics["unattributed_batch_rows"] == 300


def test_rows_with_neither_run_id_nor_hash_are_not_counted_as_batch():
    _, diagnostics = gcp_rows_to_cost_rows([_raw(run_id="", hash="", unblended_cost=5.0)], [])
    assert diagnostics["unattributed_batch_cost"] == 0.0


def test_attributed_google_batch_row_keeps_its_hash():
    rows, diagnostics = gcp_rows_to_cost_rows(
        [_raw(run_id="nnjl9fvczoruf", hash="5dbefa9a")], ["nnjl9fvczoruf"]
    )
    assert rows[0]["hash"] == "5dbefa9a"
    assert diagnostics["unattributed_batch_cost"] == 0.0


def test_purchase_option_split_stays_below_total():
    rows, _ = gcp_rows_to_cost_rows([_raw()], ["nnjl9fvczoruf"])
    row = rows[0]
    assert row["spot_cost"] + row["ondemand_cost"] <= row["unblended_cost"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --with pytest --with pyyaml pytest modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py -v -k "schema or basis or canonical or unknown_run or process or dropped or rows_with or attributed or purchase"`
Expected: FAIL — `ImportError: cannot import name 'gcp_rows_to_cost_rows'`

- [ ] **Step 3: Write the implementation**

Append to `benchmark_report_gcp_costs.py`:

```python
def _float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def gcp_rows_to_cost_rows(
    raw_rows: list[dict[str, Any]],
    known_run_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Shape query results into the ``costs.jsonl`` contract, and count what was dropped.

    CANONICAL CASE. Google lowercases label VALUES as well as keys, so a run billed under
    `4bi5xbk6e2nbhj` has to find its way back to the Platform's `4Bi5xBK6E2Nbhj` before
    ``_load_cost_pools`` can join it — that join is an exact string match. Remapping here
    rather than making the shared join case-insensitive keeps a GCP-only problem out of the
    AWS code path. An id we do not recognise passes through untouched, so it stays visible
    as unattributed spend instead of being silently renamed to something plausible.

    THE DIAGNOSTIC. Rows carrying a task hash but no run id are Google Batch spend that
    nothing can attribute — Nextflow hashes are content-addressed, so attributing by hash
    alone would cross-attribute two runs of the same pipeline over the same inputs. They
    are dropped, as on AWS, but their total is returned so the caller can say "$49.78 of
    Google Batch spend carries no run label" rather than presenting a confident zero.
    """
    canonical = {str(run_id).lower(): str(run_id) for run_id in known_run_ids if run_id}

    cost_rows: list[dict[str, Any]] = []
    unattributed_cost = 0.0
    unattributed_rows = 0

    for row in raw_rows:
        run_id = str(row.get("run_id") or "")
        hash_short = str(row.get("hash") or "")
        total = _float(row.get("unblended_cost"))

        if not run_id:
            # Only rows that look like Nextflow-submitted Batch work are worth reporting;
            # an unlabelled dev VM is not a gap in attribution, it is someone else's VM.
            if hash_short:
                unattributed_cost += total
                unattributed_rows += int(row.get("n_rows") or 0)
            continue

        cost_rows.append({
            "run_id": canonical.get(run_id.lower(), run_id),
            "session_id": str(row.get("session_id") or ""),
            # No process label exists on GCP. The field is kept so the row schema is
            # identical to the AWS one and _load_cost_pools needs no branch.
            "process": "",
            "hash": hash_short,
            "unblended_cost": round(total, 10),
            # GCP has no ECS split-cost-allocation analogue, so there is no second basis
            # and nothing that could be double-counted by summing the two.
            "split_cost": 0.0,
            "unused_cost": 0.0,
            "spot_cost": round(_float(row.get("spot_cost")), 10),
            "ondemand_cost": round(_float(row.get("ondemand_cost")), 10),
            "split_cost_present": 0,
            "cost": round(total, 10),
            "used_cost": round(total, 10),
        })

    return cost_rows, {
        "unattributed_batch_cost": round(unattributed_cost, 4),
        "unattributed_batch_rows": unattributed_rows,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --with pytest --with pyyaml pytest modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py -v`
Expected: PASS

- [ ] **Step 5: Copy to `bin/` and commit**

```bash
cp modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py bin/benchmark_report_gcp_costs.py
diff modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py bin/benchmark_report_gcp_costs.py
git add -A && git commit -m "✨ feat(gcp): map billing rows to the shared cost-row schema"
```

---

### Task 4: Run the query against BigQuery

The only part that touches the network, kept behind an injectable client so tests never do.

**Files:**
- Modify: `modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py`
- Test: `modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py`

**Interfaces:**
- Consumes: `parse_gcp_table_ref`, `build_gcp_cost_query`, `gcp_rows_to_cost_rows`, `load_gcp_cost_label_aliases`.
- Produces: `normalize_gcp_cost_rows(billing_table: str, known_run_ids: list[str], cost_label_map: Path | None = None, client: Any = None) -> tuple[list[dict], dict]`.

- [ ] **Step 1: Write the failing tests**

```python
# append to modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py
from benchmark_report_gcp_costs import normalize_gcp_cost_rows


class _FakeJob:
    def __init__(self, rows):
        self._rows = rows

    def result(self):
        return iter(self._rows)


class _FakeClient:
    """Stands in for google.cloud.bigquery.Client — records the SQL it was handed."""

    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def query(self, sql):
        self.queries.append(sql)
        return _FakeJob(self._rows)


def test_query_is_issued_and_rows_shaped():
    client = _FakeClient([_raw()])
    rows, diagnostics = normalize_gcp_cost_rows(
        "p.d.t", known_run_ids=["nnjl9fvczoruf"], client=client
    )
    assert len(client.queries) == 1
    assert "`p.d.t`" in client.queries[0]
    assert rows[0]["run_id"] == "nnjl9fvczoruf"
    assert diagnostics["unattributed_batch_cost"] == 0.0


def test_bq_prefix_stripped_before_querying():
    client = _FakeClient([])
    normalize_gcp_cost_rows("bq://p.d.t", known_run_ids=[], client=client)
    assert "`p.d.t`" in client.queries[0]
    assert "bq://" not in client.queries[0]


def test_malformed_table_fails_before_any_query():
    client = _FakeClient([])
    with pytest.raises(ValueError, match="BigQuery table"):
        normalize_gcp_cost_rows("nonsense", known_run_ids=[], client=client)
    assert client.queries == []


def test_empty_result_is_not_an_error():
    client = _FakeClient([])
    rows, diagnostics = normalize_gcp_cost_rows("p.d.t", known_run_ids=[], client=client)
    assert rows == []
    assert diagnostics["unattributed_batch_cost"] == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --with pytest --with pyyaml pytest modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py -v -k "issued or bq_prefix or malformed or empty_result"`
Expected: FAIL — `ImportError: cannot import name 'normalize_gcp_cost_rows'`

- [ ] **Step 3: Write the implementation**

Append to `benchmark_report_gcp_costs.py`:

```python
def _bigquery_client(project: str | None = None) -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover - only hit without the client installed
        raise RuntimeError(
            "google-cloud-bigquery is required to read a GCP billing export. "
            "Install it, or run this stage with "
            "`uv run --with google-cloud-bigquery ...`."
        ) from exc
    return bigquery.Client(project=project) if project else bigquery.Client()


def normalize_gcp_cost_rows(
    billing_table: str,
    known_run_ids: list[str],
    cost_label_map: Path | None = None,
    client: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Aggregate a billing export into ``costs.jsonl`` rows.

    The table reference is validated BEFORE a client is built, so a typo fails instantly
    and offline rather than after an authentication round-trip.

    The billing project is taken from the table reference, so the query is billed to
    whoever owns the export rather than to an unrelated default project.
    """
    table = parse_gcp_table_ref(billing_table)
    aliases = load_gcp_cost_label_aliases(cost_label_map)
    sql = build_gcp_cost_query(table, aliases)

    if client is None:
        client = _bigquery_client(project=table.split(".")[0])

    raw_rows = [dict(row) for row in client.query(sql).result()]
    return gcp_rows_to_cost_rows(raw_rows, known_run_ids)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --with pytest --with pyyaml pytest modules/local/normalize_benchmark_jsonl/tests/test_gcp_costs.py -v`
Expected: PASS

- [ ] **Step 5: Copy to `bin/` and commit**

```bash
cp modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py bin/benchmark_report_gcp_costs.py
diff modules/local/normalize_benchmark_jsonl/bin/benchmark_report_gcp_costs.py bin/benchmark_report_gcp_costs.py
git add -A && git commit -m "✨ feat(gcp): query the billing export and return cost rows"
```

---

### Task 5: Wire the source into `normalize_jsonl` and the CLI

**Files:**
- Modify: `modules/local/normalize_benchmark_jsonl/bin/benchmark_report_normalize.py` (the `normalize_jsonl` function, currently at the end of the file)
- Modify: `bin/benchmark_report.py` (the `normalize-jsonl` command, ~line 27)
- Test: `modules/local/normalize_benchmark_jsonl/tests/test_normalize.py`

**Interfaces:**
- Consumes: `normalize_gcp_cost_rows` from Task 4.
- Produces: `normalize_jsonl(..., gcp_billing_table: str | None = None)`.

- [ ] **Step 1: Write the failing tests**

```python
# append to modules/local/normalize_benchmark_jsonl/tests/test_normalize.py
def _write_run(data_dir, run_id="4Bi5xBK6E2Nbhj"):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / f"{run_id}.json").write_text(json.dumps({
        "workflow": {
            "id": run_id, "status": "SUCCEEDED", "runName": "r", "projectName": "p/q",
            "sessionId": "92096d14-b89e-40f2-bbc8-71168f972329",
            "duration": 1000, "stats": {"succeedCount": 1, "failedCount": 0, "cachedCount": 0},
        },
        "platform": {"id": "google-cloud"},
        "tasks": [], "metrics": [],
        "meta": {"id": run_id, "workspace": "org/ws", "group": "g"},
    }))


def test_gcp_billing_table_writes_costs_jsonl(tmp_path, monkeypatch):
    import benchmark_report_normalize as mod

    data_dir = tmp_path / "data"
    _write_run(data_dir)
    captured = {}

    def fake_extract(billing_table, known_run_ids, cost_label_map=None, client=None):
        captured["table"] = billing_table
        captured["known"] = known_run_ids
        return ([{"run_id": "4Bi5xBK6E2Nbhj", "session_id": "", "process": "", "hash": "",
                  "unblended_cost": 7.0, "split_cost": 0.0, "unused_cost": 0.0,
                  "spot_cost": 7.0, "ondemand_cost": 0.0, "split_cost_present": 0,
                  "cost": 7.0, "used_cost": 7.0}],
                {"unattributed_batch_cost": 0.0, "unattributed_batch_rows": 0})

    monkeypatch.setattr(mod, "normalize_gcp_cost_rows", fake_extract)
    out = tmp_path / "bundle"
    mod.normalize_jsonl(data_dir=data_dir, output_dir=out, gcp_billing_table="p.d.t")

    costs = [json.loads(line) for line in (out / "costs.jsonl").read_text().splitlines()]
    assert costs[0]["cost"] == 7.0
    assert captured["table"] == "p.d.t"
    # The canonical run ids must reach the extractor, or the case remap cannot happen.
    assert captured["known"] == ["4Bi5xBK6E2Nbhj"]


def test_unattributed_batch_spend_is_warned_about(tmp_path, monkeypatch, capsys):
    import benchmark_report_normalize as mod

    data_dir = tmp_path / "data"
    _write_run(data_dir)
    monkeypatch.setattr(mod, "normalize_gcp_cost_rows", lambda *a, **k: (
        [], {"unattributed_batch_cost": 49.78, "unattributed_batch_rows": 303227}))

    mod.normalize_jsonl(data_dir=data_dir, output_dir=tmp_path / "bundle",
                        gcp_billing_table="p.d.t")
    stderr = capsys.readouterr().err
    assert "49.78" in stderr
    assert "resourceLabels" in stderr


def test_both_cost_sources_is_an_error(tmp_path):
    import benchmark_report_normalize as mod

    data_dir = tmp_path / "data"
    _write_run(data_dir)
    cur = tmp_path / "cur.parquet"
    cur.write_text("not really parquet")
    with pytest.raises(ValueError, match="one cost source"):
        mod.normalize_jsonl(data_dir=data_dir, output_dir=tmp_path / "bundle",
                            costs_parquet=cur, gcp_billing_table="p.d.t")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --with pytest --with pyyaml --with pyarrow --with duckdb pytest modules/local/normalize_benchmark_jsonl/tests/test_normalize.py -v -k "gcp or unattributed or both_cost"`
Expected: FAIL — `TypeError: normalize_jsonl() got an unexpected keyword argument 'gcp_billing_table'`

- [ ] **Step 3: Write the implementation**

At the top of `benchmark_report_normalize.py`, beside the other imports:

```python
from benchmark_report_gcp_costs import normalize_gcp_cost_rows
```

Change the `normalize_jsonl` signature to add `gcp_billing_table: str | None = None`, and insert this block immediately after `_write_jsonl(output_dir / "metrics.jsonl", metric_rows)` and before the existing CUR block:

```python
    # TWO COST SOURCES, NEVER BOTH. The AWS CUR export and a GCP billing export describe
    # different clouds, and a report mixing them would silently double-count nothing but
    # would silently compare runs priced on different bases. Refuse rather than guess.
    if costs_parquet and costs_parquet.name != "NO_FILE" and gcp_billing_table:
        raise ValueError(
            "Supply only one cost source: --costs (AWS CUR parquet) or "
            "--gcp-billing-table (GCP billing export), not both."
        )

    # GCP COST DATA. Unlike the CUR path there is no staged file to probe — the export is a
    # BigQuery table read over the API — so the failure modes are authentication and a bad
    # table reference, both of which raise with their own message. Fatal, like the CUR path:
    # cost analysis was explicitly requested, and a cost-free report is indistinguishable
    # from one where no export was supplied at all.
    if gcp_billing_table:
        known_run_ids = [row["run_id"] for row in run_rows]
        cost_rows, diagnostics = normalize_gcp_cost_rows(
            gcp_billing_table,
            known_run_ids=known_run_ids,
            cost_label_map=cost_label_map,
        )
        _write_jsonl(output_dir / "costs.jsonl", cost_rows)

        # Today this is ALL Google Batch spend, because Batch rows carry only a
        # `batch-job-id` and no run label. Saying so is the difference between "Batch cost
        # nothing" and "Batch cost is not measurable yet".
        if diagnostics["unattributed_batch_cost"] > 0:
            typer.echo(
                f"WARNING: ${diagnostics['unattributed_batch_cost']:.2f} of Google Batch "
                f"spend across {diagnostics['unattributed_batch_rows']} billing rows "
                "carries a task hash but no run label, so it cannot be attributed to a run "
                "and is NOT included in this report. Set a run-id resourceLabels entry on "
                "Google Batch runs (or a Platform dynamic resource label) to attribute it.",
                err=True,
            )
```

Then in `bin/benchmark_report.py`, add the option to `normalize_jsonl_cmd` and pass it through:

```python
    gcp_billing_table: str = typer.Option(
        None,
        help="Optional GCP billing export table, as project.dataset.table (a bq:// prefix is accepted)",
    ),
```

```python
    normalize_jsonl(
        data_dir=data_dir,
        output_dir=output_dir,
        costs_parquet=costs,
        cost_label_map=cost_label_map,
        machines_dir=machines_dir,
        gcp_billing_table=gcp_billing_table,
    )
```

- [ ] **Step 4: Run the full Python suite to verify nothing regressed**

Run: `uv run --with pytest --with pyyaml --with pyarrow --with duckdb --with jinja2 --with typer pytest -v`
Expected: PASS — all pre-existing tests plus the new ones. The AWS path must be untouched.

- [ ] **Step 5: Copy to `bin/` and commit**

```bash
cp modules/local/normalize_benchmark_jsonl/bin/benchmark_report_normalize.py bin/benchmark_report_normalize.py
diff modules/local/normalize_benchmark_jsonl/bin/benchmark_report_normalize.py bin/benchmark_report_normalize.py
git add -A && git commit -m "✨ feat(gcp): accept a billing export as a cost source in normalize"
```

---

### Task 6: Nextflow wiring

**Files:**
- Modify: `nextflow.config` (params block)
- Modify: `nextflow_schema.json`
- Modify: `modules/local/normalize_benchmark_jsonl/main.nf`
- Modify: `workflows/nf_aggregate/main.nf` (the cost-input block, ~lines 126-220)

**Interfaces:**
- Consumes: the `--gcp-billing-table` CLI option from Task 5.
- Produces: `params.gcp_billing_table`, threaded to `NORMALIZE_BENCHMARK_JSONL` as a value channel.

- [ ] **Step 1: Add the param**

In `nextflow.config`, beside `benchmark_aws_cur_report`:

```groovy
    gcp_billing_table          = null
```

In `nextflow_schema.json`, beside the `benchmark_aws_cur_report` property:

```json
"gcp_billing_table": {
    "type": "string",
    "description": "GCP Cloud Billing BigQuery export table for cost analysis, as project.dataset.table.",
    "help_text": "Mutually exclusive with benchmark_aws_cur_report. A 'bq://' prefix is accepted. The query is billed to the project owning the export. Note that billing-export partitions commonly expire after 30 days, so older runs may have no cost rows.",
    "fa_icon": "fab fa-google"
}
```

- [ ] **Step 2: Thread it through the module**

In `modules/local/normalize_benchmark_jsonl/main.nf`, add `val gcp_billing_table` as the last input, add the flag, and add the BigQuery client to the conda spec:

```groovy
    conda 'python=3.12 typer=0.15 pyyaml=6 duckdb=1.1 google-cloud-bigquery=3.27'
```

```groovy
    val gcp_billing_table
```

```groovy
    def gcp_flag = gcp_billing_table ? "--gcp-billing-table ${gcp_billing_table}" : ""
```

and add `${gcp_flag} \\` to the command.

- [ ] **Step 3: Wire the workflow**

In `workflows/nf_aggregate/main.nf`, after the existing `ch_cur_label_map` block, add:

```groovy
        // A BigQuery table needs no staging and no preflight glob — it is read over the API
        // from inside the task, so the failure modes (auth, a bad table reference) surface
        // there with their own messages. Refusing both sources here rather than in the task
        // means the run stops before anything is provisioned.
        if (params.gcp_billing_table && params.benchmark_aws_cur_report) {
            error(
                "Specify only one cost source: --benchmark_aws_cur_report (AWS CUR) or " +
                "--gcp_billing_table (GCP billing export), not both."
            )
        }
        ch_gcp_billing_table = Channel.value(params.gcp_billing_table ?: '')
```

and add `ch_gcp_billing_table` as the final argument to the `NORMALIZE_BENCHMARK_JSONL(...)` call alongside `ch_cur` and `ch_cur_label_map`.

- [ ] **Step 4: Verify the config parses and the schema is valid**

```bash
nextflow lint -harshil-alignment workflows/nf_aggregate/main.nf modules/local/normalize_benchmark_jsonl/main.nf
nextflow run . --help
python3 -c "import json; json.load(open('nextflow_schema.json')); print('schema ok')"
```

Expected: no lint errors, `--help` lists `--gcp_billing_table`, schema parses.
**Do not pass `-format`** — it is destructive on existing files.

- [ ] **Step 5: Run the nf-test suite for the touched module**

Run: `nf-test test modules/local/normalize_benchmark_jsonl --profile docker`
Expected: PASS. If the container lacks `google-cloud-bigquery`, the AWS-path tests must still pass — the import is inside `_bigquery_client`, so it is only reached when a table is actually supplied.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "✨ feat(gcp): add the gcp_billing_table param and wire it through"
```

---

### Task 7: Documentation

**Files:**
- Modify: `AGENTS.md` (Gotchas section, and the Key Params table)
- Modify: `README.md`

- [ ] **Step 1: Add the Key Params row**

In `AGENTS.md`, in the Key Params table:

```markdown
| `gcp_billing_table`           | null                          | GCP billing export table (project.dataset.table)  |
```

- [ ] **Step 2: Add the Gotchas entries**

Append to the Gotchas list in `AGENTS.md`:

```markdown
- **GCP billing labels use DASHES, and the values are lowercased.** The run/session labels
  in a Google billing export are applied by the Seqera scheduler, not by Nextflow's
  `ResourceLabelPolicy.GOOGLE` — so they are `seqera-io-platform-workflowid` and
  `nextflow-io-sessionid`, never the underscored forms Nextflow would produce. Google also
  lowercases label *values*, so a Platform run id `4Bi5xBK6E2Nbhj` is billed as
  `4bi5xbk6e2nbhj`; `gcp_rows_to_cost_rows` maps it back to the canonical spelling using
  the run ids already loaded from the API, because `_load_cost_pools` joins on an exact
  string. Measured on a real export (2026-09-18): 53,046 scheduler rows / $133.67.
- **Google Batch spend carries NO run id — only `batch-job-id`.** Nextflow's Batch job name
  is `nf-<hash>-<millis>`, so the task hash is free on GCP with nothing configured, but
  there is no run label unless `resourceLabels` (or a Platform dynamic resource label) sets
  one. Attributing by hash alone is unsafe — Nextflow hashes are content-addressed, so two
  nightly runs of one pipeline over the same inputs share hashes and would cross-attribute.
  So those rows are dropped and their total is warned about instead ($49.78 across 303,227
  rows in the real export). A Batch-vs-SIC comparison is not trustworthy until that label
  is set.
- **GCP cost is GROSS; credits are never subtracted.** A negotiated discount applying to one
  engine and not the other would taint an engine comparison. The known cost of this: the
  only credit type on run-labelled rows is `SUSTAINED_USAGE_DISCOUNT`, worth ~4% of
  scheduler spend and ~0.2% of Batch spend, and it structurally favours the long-lived VMs
  the scheduler runs. Deliberate, and isolated in `build_gcp_cost_query`.
- **GCP has ONE cost basis, unlike AWS.** There is no ECS split-cost-allocation analogue, so
  `split_cost`/`unused_cost` are always zero and `comparable_cost` renders blank. Both
  engines bill on the same VM-charge basis, which makes them directly comparable — the
  opposite of the AWS situation. The purchase-option split is still gated to machine SKUs
  (`instance (core|ram)`), because disks and networking are labelled to the same run, so
  `spot + ondemand < unblended` holds on GCP too.
- **Billing-export partitions commonly expire after 30 days.** The validated table sets
  `timePartitioning.expirationMs = 2592000000`, so a report covering older runs will find no
  cost rows for them and mark them `not_found`. That is the export's retention, not a bug.
```

- [ ] **Step 3: Add the README usage**

In `README.md`, after the AWS CUR usage:

```markdown
### Google Cloud cost analysis

For runs on Google Cloud, point the pipeline at a Cloud Billing BigQuery export instead of
an AWS CUR file:

```bash
nextflow run seqeralabs/nf-aggregate \
    --input run_ids.csv \
    --outdir ./results \
    --gcp_billing_table my-project.all_billing_data.gcp_billing_export_v1_XXXXXX \
    -profile docker,intelligent_compute_report
```

The two cost sources are mutually exclusive. The query runs against BigQuery with the
pipeline's own credentials and is billed to the project owning the export, so that project
needs `bigquery.jobs.create` plus read access to the dataset.

Seqera scheduler (Cloud compute environment) runs are attributed automatically. **Google
Batch runs need a run-id resource label**, set either through Platform dynamic resource
labels (`${workflowId}`, `${sessionId}`) or in the pipeline config:

```groovy
process.resourceLabels = [
    'unique-run-id': "${workflow.runName}",
    'pipeline-session-id': "${workflow.sessionId}",
]
```

Without it, Google Batch spend is reported as unattributed in the run log rather than
counted.
```

- [ ] **Step 4: Rebuild the local report to confirm the docs match reality**

```bash
uv run --with typer --with pyyaml --with google-cloud-bigquery \
  python bin/benchmark_report.py normalize-jsonl \
  --data-dir /path/to/json_data \
  --gcp-billing-table tower-cloud-testing.all_billing_data.gcp_billing_export_v1_01F197_9D74B5_BC674D \
  --output-dir /tmp/jsonl_bundle
head -3 /tmp/jsonl_bundle/costs.jsonl
```

Expected: `costs.jsonl` rows with non-zero `cost`, and a warning naming the unattributed Google Batch total.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "📝 docs(gcp): document the billing-export cost source and its labels"
```

---

## Self-Review

**Spec coverage:** D1 single basis → Task 3. D2 gross cost → Task 2 (`test_query_never_subtracts_credits`). D3 canonical case → Task 3. D4 run id required + diagnostic → Tasks 3 and 5. D5 push-down aggregation → Task 2. Row schema → Task 3. Label findings → Task 1. Machine-SKU gate → Task 2. Azure exclusion → spec only, no task, deliberate.

**Placeholder scan:** no TBDs; every code step carries the actual code.

**Type consistency:** `normalize_gcp_cost_rows` returns `(rows, diagnostics)` in Tasks 4 and 5; diagnostic keys are `unattributed_batch_cost` / `unattributed_batch_rows` in Tasks 3, 4 and 5; `gcp_billing_table` is the parameter name in Tasks 5 and 6 (`--gcp-billing-table` as the CLI flag, `params.gcp_billing_table` in Nextflow).
