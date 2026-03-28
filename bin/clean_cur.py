#!/usr/bin/env python3
"""Process AWS Cost and Usage Report (CUR) parquet into normalized costs CSV.

Handles both formats:
  - CUR 2.0 (MAP format): resource_tags is MAP(VARCHAR, VARCHAR)
  - CUR 1.0 (flattened):  resource_tags_user_unique_run_id, etc.

Output: costs.csv with columns: run_id, process, hash, cost, used_cost, unused_cost
"""

from pathlib import Path

import duckdb
import typer

app = typer.Typer(add_completion=False)


def detect_format(db: duckdb.DuckDBPyConnection, cur_path: str) -> str:
    """Detect CUR format: 'map' (CUR 2.0) or 'flat' (CUR 1.0) or 'unknown'."""
    cur_cols = {
        r[0]
        for r in db.execute(
            f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{cur_path}'))"
        ).fetchall()
    }

    is_map = (
        "resource_tags" in cur_cols
        and "resource_tags_user_unique_run_id" not in cur_cols
    )
    if is_map:
        return "map"

    has_run_id = "resource_tags_user_unique_run_id" in cur_cols
    has_nf_run_id = "resource_tags_user_nf_unique_run_id" in cur_cols
    if has_run_id or has_nf_run_id:
        return "flat"

    return "unknown"


def build_costs_map_format(
    db: duckdb.DuckDBPyConnection, cur_path: str
) -> None:
    """Build costs table from CUR 2.0 MAP format."""
    db.execute(f"""
        CREATE TABLE costs AS
        SELECT
            COALESCE(
                resource_tags['user_unique_run_id'],
                resource_tags['user_nf_unique_run_id']
            ) AS run_id,
            resource_tags['user_pipeline_process'] AS process,
            LEFT(resource_tags['user_task_hash'], 8) AS hash,
            SUM(
                COALESCE(split_line_item_split_cost, line_item_unblended_cost, 0)
                + COALESCE(split_line_item_unused_cost, 0)
            ) AS cost,
            SUM(
                COALESCE(split_line_item_split_cost, line_item_unblended_cost, 0)
            ) AS used_cost,
            SUM(COALESCE(split_line_item_unused_cost, 0)) AS unused_cost,
        FROM read_parquet('{cur_path}')
        WHERE resource_tags['user_unique_run_id'] IS NOT NULL
           OR resource_tags['user_nf_unique_run_id'] IS NOT NULL
        GROUP BY ALL
    """)


def build_costs_flat_format(
    db: duckdb.DuckDBPyConnection, cur_path: str
) -> None:
    """Build costs table from CUR 1.0 flattened format."""
    cur_cols = {
        r[0]
        for r in db.execute(
            f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{cur_path}'))"
        ).fetchall()
    }

    has_nf_run_id = "resource_tags_user_nf_unique_run_id" in cur_cols
    has_run_id = "resource_tags_user_unique_run_id" in cur_cols

    if has_run_id and has_nf_run_id:
        run_id_expr = "COALESCE(resource_tags_user_unique_run_id, resource_tags_user_nf_unique_run_id)"
        where_clause = (
            "resource_tags_user_unique_run_id IS NOT NULL "
            "OR resource_tags_user_nf_unique_run_id IS NOT NULL"
        )
    elif has_run_id:
        run_id_expr = "resource_tags_user_unique_run_id"
        where_clause = "resource_tags_user_unique_run_id IS NOT NULL"
    elif has_nf_run_id:
        run_id_expr = "resource_tags_user_nf_unique_run_id"
        where_clause = "resource_tags_user_nf_unique_run_id IS NOT NULL"
    else:
        typer.echo("No run ID column found in CUR parquet", err=True)
        raise typer.Exit(code=1)

    process_expr = "resource_tags_user_pipeline_process"
    hash_expr = "LEFT(resource_tags_user_task_hash, 8)"

    db.execute(f"""
        CREATE TABLE costs AS
        SELECT
            {run_id_expr} AS run_id,
            {process_expr} AS process,
            {hash_expr} AS hash,
            SUM(
                COALESCE(split_line_item_split_cost, line_item_unblended_cost, 0)
                + COALESCE(split_line_item_unused_cost, 0)
            ) AS cost,
            SUM(
                COALESCE(split_line_item_split_cost, line_item_unblended_cost, 0)
            ) AS used_cost,
            SUM(COALESCE(split_line_item_unused_cost, 0)) AS unused_cost,
        FROM read_parquet('{cur_path}')
        WHERE {where_clause}
        GROUP BY ALL
    """)


@app.command()
def main(
    cur_parquet: Path = typer.Argument(
        ..., exists=True, help="AWS CUR parquet file"
    ),
    output: Path = typer.Option(
        Path("costs.csv"), help="Output CSV file"
    ),
) -> None:
    """Process AWS CUR parquet into normalized costs CSV."""
    db = duckdb.connect()
    cur_str = str(cur_parquet)

    fmt = detect_format(db, cur_str)
    if fmt == "map":
        typer.echo("Detected CUR 2.0 (MAP format)")
        build_costs_map_format(db, cur_str)
    elif fmt == "flat":
        typer.echo("Detected CUR 1.0 (flattened format)")
        build_costs_flat_format(db, cur_str)
    else:
        typer.echo(
            "Could not detect CUR format — no run ID columns found",
            err=True,
        )
        raise typer.Exit(code=1)

    output.parent.mkdir(parents=True, exist_ok=True)
    db.execute(f"COPY costs TO '{output}' (HEADER, DELIMITER ',')")
    count = db.execute("SELECT COUNT(*) FROM costs").fetchone()[0]
    typer.echo(f"Wrote {count} cost rows to {output}")
    db.close()


if __name__ == "__main__":
    app()
