# bin/ — CLI Scripts

Python scripts executed inside Nextflow process containers. Placed in `bin/` so Nextflow auto-adds them to `$PATH`.

## plot_run_gantt.py

Fusion-only Gantt chart. Reads `workflow-tasks.json` + `.fusion.log` from dump directory. Groups tasks by instance ID + machine type. pandas + plotly_express timeline. Only runs for fusion-enabled workflows.
