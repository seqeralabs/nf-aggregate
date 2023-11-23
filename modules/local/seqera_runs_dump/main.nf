process SEQERA_RUNS_DUMP {
    tag "$meta.id"
    conda 'tower-cli=0.9.0'

    input:
    val meta

    output:
    tuple val(meta), path("${prefix}")    , emit: run_dump
    tuple val(meta), path("workflow.json"), emit: workflow_json
    path "versions.yml"                   , emit: versions

    script:
    def args = task.ext.args ?: ''
    def args2 = task.ext.args2 ?: ''
    prefix = task.ext.prefix ?: "${meta.id}"
    """
    tw \\
        --access-token=\$TOWER_ACCESS_TOKEN \\
        $args \\
        runs \\
        dump \\
        -id=${meta.id} \\
        --workspace=${meta.workspace} \\
        --output="${prefix}.tar.gz" \\
        $args2

    mkdir ${prefix}
    tar \\
        -xvf \\
        ${prefix}.tar.gz \\
        -C ${prefix}

    cp ${prefix}/workflow.json .

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        seqera-cli: \$(echo \$(tw --version 2>&1) | sed 's/^.*Tower CLI version //; s/ *\$//')
    END_VERSIONS
    """
}
