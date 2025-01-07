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
            'id': task['id'],
            'process': task['process'],
            'cpu_mean': task.get('pcpu', 0),
            'mem_mean': task.get('pmem', 0),
            'vmem_mean': task.get('vmem', 0),
            'time_mean': task.get('realtime', 0),
            'reads_mean': task.get('readBytes', 0),
            'writes_mean': task.get('writeBytes', 0),
            'cost': task.get('cost', 0),
            'duration': task.get('duration', 0),
            'name': task.get('name', ''),
            'tag': task.get('tag', ''),
            'hash': task.get('hash', ''),
            'status': task.get('status', '')
        }
        flattened_tasks.append(flat_task)

    return pd.DataFrame(flattened_tasks)

def process_run_dumps(output_dir: Path):
    """Process all run dumps and create standardized TSV outputs"""

    # Initialize DuckDB
    db = duckdb.connect(':memory:')

    # Find all workflow-tasks.json files
    task_files = glob.glob("**/workflow-tasks.json", recursive=True)

    # Process each task file
    all_tasks = []
    for task_file in task_files:
        run_id = Path(task_file).parent.name
        df = process_workflow_tasks(task_file)
        df['run_id'] = run_id
        all_tasks.append(df)

    # Combine all tasks
    if all_tasks:
        combined_tasks = pd.concat(all_tasks, ignore_index=True)

        # Create workflow_tasks.tsv
        db.sql("""
            CREATE TABLE tasks AS SELECT * FROM combined_tasks;

            COPY (
                SELECT
                    run_id,
                    id,
                    process,
                    cpu_mean as cpu.mean,
                    mem_mean as mem.mean,
                    vmem_mean as vmem.mean,
                    time_mean as time.mean,
                    reads_mean as reads.mean,
                    writes_mean as writes.mean,
                    cost,
                    duration
                FROM tasks
                ORDER BY run_id, id
            ) TO '{}' (HEADER, DELIMITER '\t')
        """.format(output_dir / 'workflow_tasks.tsv'))

def main():
    output_dir = Path("processed")
    output_dir.mkdir(exist_ok=True)

    process_run_dumps(output_dir)

if __name__ == "__main__":
    main()
