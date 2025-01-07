#!/usr/bin/env python3

import duckdb
import argparse
from pathlib import Path

def join_workflow_data(run_id: str):
    """Join workflow data files using DuckDB"""
    db = duckdb.connect(':memory:')

    # Read the input files
    db.sql(f"""
        CREATE TABLE service_info AS
        SELECT * FROM read_csv_auto('{run_id}_workflow_metadata.tsv');

        CREATE TABLE workflow_load AS
        SELECT * FROM read_csv_auto('{run_id}_workflow_load.tsv');

        CREATE TABLE workflow AS
        SELECT * FROM read_csv_auto('{run_id}_workflow.tsv');
    """)

    # Perform the joins with suffix handling for duplicate columns
    db.sql(f"""
        -- First join (service_info + workflow_load)
        CREATE TABLE join_1 AS
        SELECT
            COALESCE(s.run_id, w.run_id) as run_id,
            s.*,
            w.*
        FROM service_info s
        FULL JOIN workflow_load w
        ON s.run_id = w.run_id;

        COPY (SELECT * FROM join_1)
        TO '{run_id}_join_1.tsv' (HEADER, DELIMITER '\t');

        -- Second join (previous result + workflow)
        CREATE TABLE join_2 AS
        SELECT
            COALESCE(j.run_id, w.run_id) as run_id,
            j.*,
            w.*
        FROM join_1 j
        FULL JOIN workflow w
        ON j.run_id = w.run_id;

        -- Create final join with renamed columns for conflicts
        CREATE TABLE join_3 AS
        SELECT
            run_id,
            -- Add specific column renames for conflicts
            j2.commitId as "commitId.x",
            w.commitId as "commitId.y",
            j2.dateCreated as "dateCreated.x",
            w.dateCreated as "dateCreated.y",
            j2.lastUpdated as "lastUpdated.x",
            w.lastUpdated as "lastUpdated.y",
            j2.group as "group.x",
            w.group as "group.y",
            -- Add remaining columns
            *
        FROM join_2 j2;

        COPY (SELECT * FROM join_3)
        TO '{run_id}_join_3.tsv' (HEADER, DELIMITER '\t');
    """)

def main():
    parser = argparse.ArgumentParser(description='Join workflow data files')
    parser.add_argument('run_id', help='Run ID to process')
    args = parser.parse_args()

    join_workflow_data(args.run_id)

if __name__ == "__main__":
    main()
