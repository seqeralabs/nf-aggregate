process SEQERA_RUNS_DUMP {
    tag "$run_id"
    //secret 'TOWER_ACCESS_TOKEN'
    conda 'bioconda::tower-cli=0.9.0'
    container "${ workflow.containerEngine == 'singularity' && !task.ext.singularity_pull_docker_container ?
        'https://depot.galaxyproject.org/singularity/tower-cli:0.9.0--h9ee0642_0' :
        'biocontainers/tower-cli:0.9.0--h9ee0642_0' }"

    input:
    val run_id
    val workspace

    output:
    tuple val(run_id), path("*_run_dump"), emit: run_dump
    path "versions.yml"                  , emit: versions

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

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        seqera-cli: \$(echo \$(tw --version 2>&1) | sed 's/^.*Tower CLI version //; s/ *\$//')
    END_VERSIONS
    """
}
