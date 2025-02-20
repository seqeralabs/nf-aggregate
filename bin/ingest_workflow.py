#!/usr/bin/env python3

import duckdb
import argparse
from pathlib import Path

def process_workflow_data(input_file: Path, output_file: Path):
    """
    Process workflow data using DuckDB and save to CSV
    """
    # Initialize DuckDB in-memory
    db = duckdb.connect(database=':memory:')

    # Read the input CSV file
    db.sql(f"""
        CREATE TABLE workflow AS
        SELECT * FROM read_csv_auto('{input_file}')
    """)

    # Process the data
    db.sql("""
        CREATE TABLE merged_logs AS
        SELECT
            *,
            -- Extract pipeline name from repository URL (last element after /)
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
        FROM workflow
    """)

    # Export to CSV
    db.sql(f"COPY merged_logs TO '{output_file}' (HEADER, DELIMITER ',')")

    # Close the connection
    db.close()

def main():
    parser = argparse.ArgumentParser(description='Process workflow data using DuckDB')
    parser.add_argument('workflow', type=Path, help='Workflow JSON file path')
    parser.add_argument('workflow_load', type=Path, help='Workflow load JSON file path')
    parser.add_argument('workflow_launch', type=Path, help='Workflow launch JSON file path')
    parser.add_argument('service_info', type=Path, help='Service info JSON file path')
    parser.add_argument('output', type=Path, help='Output CSV file path')

    args = parser.parse_args()

    process_workflow_data(args.input, args.output)

if __name__ == "__main__":
    main()
