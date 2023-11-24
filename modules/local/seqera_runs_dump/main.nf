process SEQERA_RUNS_DUMP {
    tag "$run_id"
    conda 'tower-cli=0.9.0'

    input:
    val run_id
    val workspace

    output:
    tuple val(run_id), path("*_run_dump")   , emit: run_dump
    tuple val(run_id), path("workflow.json"), emit: workflow_json
    path "versions.yml"                     , emit: versions

    script:
    def args = task.ext.args ?: ''
    def args2 = task.ext.args2 ?: ''
    def prefix = task.ext.prefix ?: "${run_id}"
    """
    tw \\
        --access-token=\$TOWER_ACCESS_TOKEN \\
        $args \\
        runs \\
        dump \\
        -id=$run_id \\
        --workspace=$workspace \\
        --output="${prefix}_run_dump.tar.gz" \\
        $args2

    mkdir ${prefix}_run_dump
    tar \\
        -xvf \\
        ${prefix}_run_dump.tar.gz \\
        -C ${prefix}_run_dump

    cp ${prefix}_run_dump/workflow.json .

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        seqera-cli: \$(echo \$(tw --version 2>&1) | sed 's/^.*Tower CLI version //; s/ *\$//')
    END_VERSIONS
    """
}
