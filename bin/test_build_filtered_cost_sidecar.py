from pathlib import Path
import sys

import pyarrow as pa


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_filtered_cost_sidecar as sidecar


def test_build_run_ids_prefers_custom_map_alias_over_default_flat_column():
    aliases = sidecar._dedupe_aliases(["custom_run", *sidecar.DEFAULT_RUN_ID_ALIASES])
    table = pa.table(
        {
            "resource_tags_user_unique_run_id": ["run-default"],
            "resource_tags": [[("custom_run", "run-custom")]],
        }
    )

    run_id_column = sidecar.choose_run_id_column(table.schema, aliases)

    assert run_id_column == "resource_tags_user_unique_run_id"
    assert sidecar.build_run_ids(table, run_id_column, aliases) == ["run-custom"]
