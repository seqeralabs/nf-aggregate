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
