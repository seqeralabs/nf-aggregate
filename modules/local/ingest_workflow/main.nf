process INGEST_WORKFLOW {
    tag "${meta.id}"
    conda "r-base r-optparse r-tidyverse r-jsonlite"

    input:
    tuple val(meta), path(run_dump)

    output:
    path ("*_workflow_data.csv"), emit: workflow_data
    path ("*_tasks_data.csv"), emit: tasks_data

    script:
    """
    ingest_workflow.R \\
        --workflow ${run_dump}/workflow.json \\
        --workflow_load ${run_dump}/workflow-load.json \\
        --workflow_launch ${run_dump}/workflow-launch.json \\
        --service_info ${run_dump}/service-info.json \\
        --output ${meta.id}_workflow_data.csv

    ingest_tasks.R \\
        --tasks ${run_dump}/workflow-tasks.json \\
        --output ${meta.id}_tasks_data.csv
    """
}
