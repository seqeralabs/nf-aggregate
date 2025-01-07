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

    # Perform the joins
    db.sql(f"""
        -- First join (service_info + workflow_load)
        CREATE TABLE join_1 AS
        SELECT *
        FROM service_info
        FULL JOIN workflow_load USING (run_id);

        COPY (SELECT * FROM join_1)
        TO '{run_id}_join_1.tsv' (HEADER, DELIMITER '\t');

        -- Second join (previous result + workflow)
        CREATE TABLE join_2 AS
        SELECT *
        FROM join_1
        FULL JOIN workflow USING (run_id);

        COPY (SELECT * FROM join_2)
        TO '{run_id}_join_2.tsv' (HEADER, DELIMITER '\t');
    """)

def main():
    parser = argparse.ArgumentParser(description='Join workflow data files')
    parser.add_argument('run_id', help='Run ID to process')
    args = parser.parse_args()

    join_workflow_data(args.run_id)

if __name__ == "__main__":
    main()
