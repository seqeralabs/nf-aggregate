#!/usr/bin/env python3

import duckdb
import argparse
from pathlib import Path

def process_workflow_data(workflow_file: Path, workflow_load_file: Path,
                         workflow_launch_file: Path, service_info_file: Path,
                         group_file: Path, output_file: Path):
    """
    Process workflow data using DuckDB, merging multiple input files
    """
    # Initialize DuckDB in-memory
    db = duckdb.connect(database=':memory:')

    # Read all input files
    db.sql(f"""
        CREATE TABLE workflow AS SELECT * FROM read_csv_auto('{workflow_file}');
        CREATE TABLE workflow_load AS SELECT * FROM read_csv_auto('{workflow_load_file}');
        CREATE TABLE workflow_launch AS SELECT * FROM read_csv_auto('{workflow_launch_file}');
        CREATE TABLE service_info AS SELECT * FROM read_csv_auto('{service_info_file}');
        CREATE TABLE groups AS SELECT * FROM read_csv_auto('{group_file}');
    """)

    # Process and merge the data
    db.sql("""
        WITH merged_base AS (
            SELECT
                w.*,
                wl.*,
                wla.*,
                si.*,
                g.group
            FROM workflow w
            FULL JOIN workflow_load wl USING (run_id)
            FULL JOIN workflow_launch wla USING (run_id)
            FULL JOIN service_info si USING (run_id)
            LEFT JOIN groups g USING (run_id)
        ),

        merged_logs AS (
            SELECT
                *,
                -- Extract pipeline name from repository URL
                CASE
                    WHEN REGEXP_EXTRACT(repository, '[^/]+$') = 'nf-stresstest'
                    THEN run_name
                    ELSE REGEXP_EXTRACT(repository, '[^/]+$')
                END as pipeline,
                -- Convert and round numeric fields
                ROUND(CAST(cost AS DOUBLE), 2) as cost,
                ROUND(CAST(cpuTime AS DOUBLE) / 60 / 60 / 1000, 1) as cpuTime,
                ROUND(CAST(readBytes AS DOUBLE) / (1024*1024*1024), 2) as readBytes,
                ROUND(CAST(writeBytes AS DOUBLE) / (1024*1024*1024), 2) as writeBytes,
                ROUND(CAST(cpuEfficiency AS DOUBLE), 2) as cpuEfficiency,
                ROUND(CAST(memoryEfficiency AS DOUBLE), 2) as memoryEfficiency,
                CAST(succeeded AS INTEGER) + CAST(failed AS INTEGER) + CAST(cached AS INTEGER) as total_tasks
            FROM merged_base
        ),

        -- Calculate pipeline order based on min walltime
        pipeline_order AS (
            SELECT
                pipeline,
                MIN(duration) as min_walltime
            FROM merged_logs
            GROUP BY pipeline
            ORDER BY min_walltime
        )

        SELECT
            m.*,
            p.min_walltime
        FROM merged_logs m
        LEFT JOIN pipeline_order p USING (pipeline)
        ORDER BY pipeline
    """)

    # Export to CSV
    db.sql(f"COPY (SELECT * FROM merged_logs) TO '{output_file}' (HEADER, DELIMITER ',')")

    # Close the connection
    db.close()

def main():
    parser = argparse.ArgumentParser(description='Process Seqera workflow data using DuckDB')
    parser.add_argument('--workflow', type=Path, required=True, help='Workflow CSV file')
    parser.add_argument('--workflow-load', type=Path, required=True, help='Workflow load CSV file')
    parser.add_argument('--workflow-launch', type=Path, required=True, help='Workflow launch CSV file')
    parser.add_argument('--service-info', type=Path, required=True, help='Service info CSV file')
    parser.add_argument('--output', type=Path, required=True, help='Output CSV file path')

    args = parser.parse_args()

    process_workflow_data(
        args.workflow,
        args.workflow_load,
        args.workflow_launch,
        args.service_info,
        args.group,
        args.output
    )

if __name__ == "__main__":
    main()
