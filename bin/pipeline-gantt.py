#!/usr/bin/env python3

import json
import tarfile
from datetime import datetime
from typing import IO

import click
import pandas as pd
import plotly.express as px


def extract_instance(fusion_logs: str, lines: IO) -> str:
    for i, line in enumerate(lines):
        try:
            log = json.loads(line)
            if 'instance-id' in log:
                return log['instance-id']
        except json.JSONDecodeError:
            print(f"WARN: invalid JSON at '{fusion_logs}' line {i}")
    return ""


@click.command()
@click.option('--title', default='Pipeline GANTT', help='Plot title.')
@click.option('--input-file', type=click.Path(), help='The pipeline dump tar.gz input file.')
@click.option('--output-file', type=click.Path(), help='The HTML output file')
def build_gantt(title: str, input_file: str, output_file: str):
    tasks = []
    instance_ids = {}

    tar = tarfile.open(input_file, "r:gz")
    for member in tar.getmembers():
        if member.name == "workflow-tasks.json":
            tasks = json.load(tar.extractfile(member))
        if member.name.endswith(".fusion.log"):
            _, task_id, _ = member.name.split('/')
            instance_id = extract_instance(member.name, tar.extractfile(member))
            instance_ids[int(task_id)] = instance_id

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
