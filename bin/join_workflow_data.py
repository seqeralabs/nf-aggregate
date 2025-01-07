#!/usr/bin/env python3

import duckdb
import glob

def join_workflow_data():
    """Join workflow data files using DuckDB"""
    db = duckdb.connect(":memory:")

    # Get all workflow files in current directory
    workflow_metadata_files = glob.glob("*_workflow_metadata.tsv")
    workflow_load_files = glob.glob("*_workflow_load.tsv")
    workflow_files = glob.glob("*_workflow.tsv")

    if not (workflow_metadata_files and workflow_load_files and workflow_files):
        print("No workflow files found in current directory")
        return

    # Read all files
    db.sql("""
        CREATE TABLE service_info AS
        SELECT * FROM read_csv_auto('*_workflow_metadata.tsv', delim='\t');
    """)

    db.sql("""
        CREATE TABLE workflow_load AS
        SELECT * FROM read_csv_auto('*_workflow_load.tsv', delim='\t');
    """)

    db.sql("""
        CREATE TABLE workflow AS
        SELECT * FROM read_csv_auto('*_workflow.tsv', delim='\t');
    """)

    # First join
    db.sql("""
        CREATE TABLE join_1 AS
        SELECT
            COALESCE(s.run_id, w.run_id) run_id,
            s.pipelineId,
            s.organizationId,
            s.organizationName,
            s.workspaceId,
            s.workspaceName,
            s.userId,
            s.runUrl,
            w.pending,
            w.submitted,
            w.running,
            w.succeeded,
            w.failed,
            w.cached,
            w.memoryEfficiency,
            w.cpuEfficiency,
            w.cpus,
            w.cpuTime,
            w.cpuLoad,
            w.memoryRss,
            w.memoryReq,
            w.readBytes,
            w.writeBytes,
            w.volCtxSwitch,
            w.invCtxSwitch,
            w.cost,
            w.loadTasks,
            w.loadCpus,
            w.loadMemory,
            w.peakCpus,
            w.peakTasks,
            w.peakMemory,
            w.executors,
            w.dateCreated,
            w.lastUpdated
        FROM service_info s
        FULL OUTER JOIN workflow_load w
        ON s.run_id = w.run_id;
    """)

    db.sql("""
        COPY (SELECT * FROM join_1) TO 'join_1.tsv' (HEADER, DELIMITER '\t');
    """)

    # Second join
    db.sql("""
        CREATE TABLE join_2 AS
        SELECT
            COALESCE(j.run_id, w.run_id) run_id,
            j.*,
            w.status,
            w.repository,
            w.start,
            w.complete,
            w.duration
        FROM join_1 j
        FULL OUTER JOIN workflow w
        ON j.run_id = w.run_id;
    """)

    db.sql("""
        COPY (SELECT * FROM join_2) TO 'join_2.tsv' (HEADER, DELIMITER '\t');
    """)

    # Final join with renamed columns
    db.sql("""
        COPY (
            SELECT
                run_id,
                pipelineId,
                organizationId,
                organizationName,
                workspaceId,
                workspaceName,
                userId,
                runUrl,
                dateCreated "dateCreated.x",
                lastUpdated "lastUpdated.x",
                status,
                repository,
                start,
                complete,
                duration
            FROM join_2
        ) TO 'join_3.tsv' (HEADER, DELIMITER '\t');
    """)

def main():
    join_workflow_data()

if __name__ == "__main__":
    main()
