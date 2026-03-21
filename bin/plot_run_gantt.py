#!/usr/bin/env python3
"""Generate a Gantt chart from pipeline task data."""

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import typer

app = typer.Typer(add_completion=False)


def extract_instance(fusion_logs: Path) -> str:
    with fusion_logs.open() as file:
        for line_number, line in enumerate(file, start=1):
            try:
                log = json.loads(line)
                if "instance-id" in log:
                    return log["instance-id"]
            except json.JSONDecodeError:
                print(f"WARN: invalid JSON at '{fusion_logs}' line {line_number}")
        return ""


@app.command()
def build_gantt(
    title: str = typer.Option("Pipeline GANTT", help="Plot title."),
    input_dir: Path = typer.Option(..., help="The pipeline dump directory."),
    output_file: Path = typer.Option(..., help="The HTML output file."),
) -> None:
    tasks = []
    instance_ids = {}

    for path in input_dir.glob("workflow-tasks.json"):
        with path.open() as json_file:
            tasks = json.load(json_file)
    for path in input_dir.glob("**/.fusion.log"):
        task_id = int(path.parent.name)
        instance_id = extract_instance(path)
        instance_ids[task_id] = instance_id

    for t in tasks:
        t["instanceId"] = instance_ids.get(t["taskId"], "unknown")

    data = [
        {
            k: v
            for k, v in t.items()
            if k
            in [
                "taskId",
                "name",
                "start",
                "complete",
                "memory",
                "cpus",
                "machineType",
                "instanceId",
            ]
        }
        for t in tasks
    ]
    df = pd.DataFrame(
        {
            "id": f"T{d['taskId']}",
            "name": d["name"],
            "size": f"{d['cpus']}c_{math.ceil(d.get('memory', 1073741824) / 1024 ** 3):.0f}GB",
            "start": datetime.strptime(d["start"], "%Y-%m-%dT%H:%M:%SZ"),
            "complete": datetime.strptime(d["complete"], "%Y-%m-%dT%H:%M:%SZ")
            + timedelta(seconds=1),
            "instance": f"{d.get('instanceId', 'HEAD')} ({d.get('machineType', 'unknown')})",
        }
        for d in data
        if d.get("complete")
    )

    fig = px.timeline(
        df,
        title=title,
        x_start="start",
        x_end="complete",
        y="id",
        color="instance",
        text="name",
    )
    fig.write_html(str(output_file))


if __name__ == "__main__":
    app()
