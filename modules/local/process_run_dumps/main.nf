process PROCESS_RUN_DUMPS {
    tag "${meta.id}"
    conda "python pandas duckdb"

    input:
    tuple val(meta), path(run_dump)

    output:
    // TODO path ("*_workflow.tsv"), emit: workflow_data
    // TODO path ("*_workflow_launch.tsv"), emit: workflow_launch
    // TODO path ("*_workflow_load.tsv"), emit: workflow_load
    // TODO path ("*_workflow_metadata.tsv"), emit: workflow_metadata
    // TODO path ("*_workflow_metrics.tsv"), emit: workflow_metrics
    path ("*_workflow_tasks.tsv"), emit: workflow_tasks
    // TODO path ("*_other_data.tsv"), emit: other_data
    // TODO path ("*_service_info.tsv"), emit: service_info
    script:
    """
    process_run_dumps.py
    """
}
