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

    """
}
