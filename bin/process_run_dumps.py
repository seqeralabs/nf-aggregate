#!/usr/bin/env python3

import json
import duckdb
import pandas as pd
from pathlib import Path
from typing import Dict, List
import glob


def process_workflow_tasks(task_file: Path) -> pd.DataFrame:
    """Process workflow tasks JSON file into a structured DataFrame"""
    with open(task_file) as f:
        tasks = json.load(f)

    # Flatten the task data
    flattened_tasks = []
    for task in tasks:
        flat_task = {
            "id": task["id"],
            "process": task["process"],
            "cpu_mean": task.get("pcpu", 0),
            "mem_mean": task.get("pmem", 0),
            "vmem_mean": task.get("vmem", 0),
            "time_mean": task.get("realtime", 0),
            "reads_mean": task.get("readBytes", 0),
            "writes_mean": task.get("writeBytes", 0),
            "cost": task.get("cost", 0),
            "duration": task.get("duration", 0),
            "name": task.get("name", ""),
            "tag": task.get("tag", ""),
            "hash": task.get("hash", ""),
            "status": task.get("status", ""),
        }
        flattened_tasks.append(flat_task)

    return pd.DataFrame(flattened_tasks)


def process_workflow_metadata(metadata_file: Path) -> pd.DataFrame:
    """Process workflow metadata JSON file"""
    with open(metadata_file) as f:
        metadata = json.load(f)

    return pd.DataFrame(
        [
            {
                "run_id": metadata.get("runId", ""),
                "pipelineId": metadata.get("pipelineId", ""),
                "organizationId": metadata.get("organizationId", ""),
                "organizationName": metadata.get("organizationName", ""),
                "workspaceId": metadata.get("workspaceId", ""),
                "workspaceName": metadata.get("workspaceName", ""),
                "userId": metadata.get("userId", ""),
                "runUrl": metadata.get("runUrl", ""),
            }
        ]
    )


def process_workflow(workflow_file: Path) -> pd.DataFrame:
    """Process workflow JSON file"""
    with open(workflow_file) as f:
        workflow = json.load(f)

    return pd.DataFrame(
        [
            {
                "run_id": workflow.get("runId", ""),
                "status": workflow.get("status", ""),
                "repository": workflow.get("repository", ""),
                "start": workflow.get("start", ""),
                "complete": workflow.get("complete", ""),
                "duration": workflow.get("duration", 0),
            }
        ]
    )


def process_run_dumps(output_dir: Path):
    """Process all run dumps and create standardized TSV outputs"""
    db = duckdb.connect(":memory:")

    # Process tasks
    task_files = glob.glob("**/workflow-tasks.json", recursive=True)
    all_tasks = []
    for task_file in task_files:
        run_id = Path(task_file).parent.name
        df = process_workflow_tasks(task_file)
        df["run_id"] = run_id
        all_tasks.append(df)

    # Process metadata
    metadata_files = glob.glob("**/workflow-metadata.json", recursive=True)
    all_metadata = []
    for metadata_file in metadata_files:
        df = process_workflow_metadata(metadata_file)
        all_metadata.append(df)

    # Process workflow
    workflow_files = glob.glob("**/workflow.json", recursive=True)
    all_workflows = []
    for workflow_file in workflow_files:
        df = process_workflow(workflow_file)
        all_workflows.append(df)

    # Combine and save all data
    if all_tasks:
        combined_tasks = pd.concat(all_tasks, ignore_index=True)
        db.sql(
            """
            CREATE TABLE tasks AS SELECT * FROM combined_tasks;
            COPY (
                SELECT
                    run_id,
                    id,
                    process,
                    cpu_mean as "cpu.mean",
                    mem_mean as "mem.mean",
                    vmem_mean as "vmem.mean",
                    time_mean as "time.mean",
                    reads_mean as "reads.mean",
                    writes_mean as "writes.mean",
                    cost,
                    duration
                FROM tasks
                ORDER BY run_id, id
            ) TO '{}' (HEADER, DELIMITER '\t')
        """.format(output_dir / "workflow_tasks.tsv")
        )

    if all_metadata:
        combined_metadata = pd.concat(all_metadata, ignore_index=True)
        db.sql(
            """
            CREATE TABLE metadata AS SELECT * FROM combined_metadata;
            COPY (
                SELECT *
                FROM metadata
                ORDER BY run_id
            ) TO '{}' (HEADER, DELIMITER '\t')
        """.format(output_dir / "workflow_metadata.tsv")
        )

    if all_workflows:
        combined_workflows = pd.concat(all_workflows, ignore_index=True)
        db.sql(
            """
            CREATE TABLE workflows AS SELECT * FROM combined_workflows;
            COPY (
                SELECT *
                FROM workflows
                ORDER BY run_id
            ) TO '{}' (HEADER, DELIMITER '\t')
        """.format(output_dir / "workflow.tsv")
        )


def main():
    output_dir = Path("processed")
    output_dir.mkdir(exist_ok=True)
    process_run_dumps(output_dir)


if __name__ == "__main__":
    main()
