process PARSE_MULTIQC_TABLES {
    input:
    path multiqc_data

    output:
    path ("*_workflows.csv"), emit: workflows_table
    path ("*_workflows.csv"), emit: tasks_table

    script:
    """
    ingest_data.qmd
    """
}
