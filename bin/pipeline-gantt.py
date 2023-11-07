#!/usr/bin/env python3

import json
from datetime import datetime
from typing import IO
from pathlib import Path

import click
import pandas as pd
import plotly.express as px


def extract_instance(fusion_logs: Path) -> str:
    with fusion_logs.open() as file:
        for line_number, line in enumerate(file, start=1):
            try:
                log = json.loads(line)
                if 'instance-id' in log:
                    return log['instance-id']
            except json.JSONDecodeError:
                print(f"WARN: invalid JSON at '{fusion_logs}' line {line_number}")
        return ""

@click.command()
@click.option('--title', default='Pipeline GANTT', help='Plot title.')
@click.option('--input-dir', type=click.Path(), help='The pipeline dump tar.gz input file.')
@click.option('--output-file', type=click.Path(), help='The HTML output file')
def build_gantt(title: str, input_dir: str, output_file: str):
    tasks = []
    instance_ids = {}

    for path in Path(input_dir).glob('workflow-tasks.json'):
        with path.open() as json_file:
            tasks = json.load(json_file)
    for path in Path(input_dir).glob('**/.fusion.log'):
        task_id = int(path.parent.name)
        instance_id = extract_instance(path)
        instance_ids[task_id] = instance_id

    for t in tasks:
        t['instanceId'] = instance_ids.get(t['taskId'], "unknow")

    data = [{k: v for k, v in t.items() if k in ['taskId', 'name', 'start', 'complete', 'memory', 'cpus', 'machineType', 'instanceId']} for t in tasks]
    df = pd.DataFrame({
                          'id': f"T{d['taskId']}",
                          'name': d['name'],
                          'size': f"{d['cpus']}c_{d['memory'] / 1024 ** 3:.0f}GB",
                          'start': datetime.strptime(d['start'], '%Y-%m-%dT%H:%M:%SZ'),
                          'complete': datetime.strptime(d['complete'], '%Y-%m-%dT%H:%M:%SZ'),
                          'instance': f"{d['instanceId']} ({d['machineType']})"
                      }
                      for d in data
                      )

    fig = px.timeline(df, title=title, x_start="start", x_end="complete", y="id", color="instance", text="name", pattern_shape="size")
    fig.write_html(output_file)


if __name__ == '__main__':
    build_gantt()
