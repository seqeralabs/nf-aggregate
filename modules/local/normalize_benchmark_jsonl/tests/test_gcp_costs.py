import pytest

from benchmark_report_gcp_costs import (
    DEFAULT_GCP_COST_LABEL_ALIASES,
    _task_hash_from_job_id,
    load_gcp_cost_label_aliases,
)


def test_default_aliases_cover_both_separators():
    """Two label producers, two separator conventions — both must resolve.

    The Seqera scheduler writes its own keys with DASHES
    (`seqera-io-platform-workflowid`). A user-declared `resourceLabels` map is passed to
    Google VERBATIM — Nextflow never rewrites user labels, and Google permits underscores —
    so the Batch cost-tracking template lands as `unique_run_id`, `pipeline_session_id`,
    `pipeline_process`, `task_hash`.

    An earlier version of this file asserted no alias contained an underscore. That was
    wrong, and it cost $29.26 of real Google Batch spend across 4 runs, silently dropped as
    unattributed because the reader only looked for `unique-run-id`.
    """
    assert DEFAULT_GCP_COST_LABEL_ALIASES["run_id"][0] == "seqera-io-platform-workflowid"
    assert DEFAULT_GCP_COST_LABEL_ALIASES["session_id"][0] == "nextflow-io-sessionid"
    # Both spellings, for every field a user-declared template can set.
    for field, dashed, scored in [
        ("run_id", "unique-run-id", "unique_run_id"),
        ("session_id", "pipeline-session-id", "pipeline_session_id"),
        ("process", "pipeline-process", "pipeline_process"),
        ("task_hash", "task-hash", "task_hash"),
    ]:
        assert dashed in DEFAULT_GCP_COST_LABEL_ALIASES[field], f"{field} missing {dashed}"
        assert scored in DEFAULT_GCP_COST_LABEL_ALIASES[field], f"{field} missing {scored}"
    # The Batch job id is its own field: it needs regex extraction, not a plain read.
    assert DEFAULT_GCP_COST_LABEL_ALIASES["batch_job_id"] == ["batch-job-id"]


def test_query_reads_the_underscore_label_keys():
    """The regression guard for the miss above: these exact keys must appear in the SQL."""
    sql = build_gcp_cost_query("p.d.t", DEFAULT_GCP_COST_LABEL_ALIASES)
    for key in ("unique_run_id", "pipeline_session_id", "pipeline_process", "task_hash"):
        assert f"l.key = '{key}'" in sql, f"query never reads {key}"


def test_query_prefers_an_explicit_task_hash_over_the_batch_job_id():
    """An explicit `task_hash` label is exact; the job id needs a regex and can be absent.

    Both truncate to 8 characters, which is the grain the aggregator keys on
    (`benchmark_report_aggregate.py:57` does `.replace("/", "")[:8]`).
    """
    sql = build_gcp_cost_query("p.d.t", DEFAULT_GCP_COST_LABEL_ALIASES)
    hash_expr = sql[sql.index("AS hash_raw")-700:sql.index("AS hash_raw")]
    assert "task_hash" in hash_expr
    assert "nf-([0-9a-f]+)" in hash_expr
    assert hash_expr.index("task_hash") < hash_expr.index("nf-([0-9a-f]+)"), \
        "explicit task_hash must be tried before the batch-job-id regex"


def test_process_label_is_carried_not_blanked():
    """`pipeline_process` exists on every labelled Google Batch row in the real export.

    The original implementation hardcoded `process: ""` on the belief that GCP had no
    process label. It does, so blanking it threw away task-grain attribution.
    """
    rows, _ = gcp_rows_to_cost_rows(
        [_raw(process="nfcore_rnaseq_align", hash="602fa449")], ["nnjl9fvczoruf"]
    )
    assert rows[0]["process"] == "nfcore_rnaseq_align"
    assert rows[0]["hash"] == "602fa449"


def test_process_absent_stays_blank():
    """A scheduler run carries no process label; blank must still be the answer there."""
    rows, _ = gcp_rows_to_cost_rows([_raw()], ["nnjl9fvczoruf"])
    assert rows[0]["process"] == ""


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
        # Provenance: the IC aggregator reads this to decide one cost basis vs two.
        "source",
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


def test_reserved_keyword_alias_is_quoted():
    """`hash` is reserved in BigQuery; a bare `AS hash` fails the entire query.

    Caught only by running the query against a real export, never by the string
    assertions above — which is exactly why this guard exists.
    """
    sql = build_gcp_cost_query("p.d.t", DEFAULT_GCP_COST_LABEL_ALIASES)
    assert "AS `hash`" in sql
    assert "AS hash," not in sql
