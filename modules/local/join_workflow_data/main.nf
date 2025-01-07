process JOIN_WORKFLOW_DATA {
    conda "python duckdb"

    input:
    path workflow_metadata, arity: "2..*"
    path workflow_load, arity: "2..*"
    path workflow_data, arity: "2..*"

    output:
    path ("*_join_1.tsv"), emit: join_1
    path ("*_join_2.tsv"), emit: join_2
    path ("*_join_3.tsv"), emit: join_3

    script:
    """
    join_workflow_data.py
    """
}
