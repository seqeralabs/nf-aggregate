# plot_run_gantt

Gantt chart for fusion-enabled pipeline runs. Visualizes task execution timeline grouped by cloud instance.

## Process

**Conda:** `click=8.0.1 pandas=1.1.5 plotly_express=0.4.1 typing=3.10.0.0`
**Container:** `seqeralabs/nf-aggregate:click-8.0.1_pandas-1.1.5_plotly_express-0.4.1_typing-3.10.0.0--ccea219dc6c3d6a1`

### Inputs

| Input      | Type | Description                                    |
| ---------- | ---- | ---------------------------------------------- |
| `meta`     | val  | Run metadata (must have `meta.fusion == true`) |
| `run_dump` | path | Run dump directory from SEQERA_RUNS_DUMP       |

### Outputs

- `{id}_gantt.html` — interactive Plotly timeline
- `versions.yml` — python, pandas, plotly_express, click versions

### Filter

Only runs for fusion-enabled workflows:

```nextflow
.filter { meta, _run_dir -> meta.fusion && !skip_run_gantt }
```

### Script

Calls `bin/plot_run_gantt.py` which reads `workflow-tasks.json` + `.fusion.log` files from the dump directory. Tasks grouped by instance ID + machine type on the y-axis.
