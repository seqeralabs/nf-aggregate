include { getRunMetadata } from './functions'

process SEQERA_RUNS_DUMP {
    tag "$meta.id"
    conda 'tower-cli=0.9.2'
    container 'seqeralabs/nf-aggregate:tower-cli-0.9.2--hdfd78af_1'

    input:
    val meta
    val api_endpoint

    output:
    tuple val(metaOut), path("${prefix}"), emit: run_dump
    path "versions.yml"                  , emit: versions

    script:
    def args = task.ext.args ?: ''
    def args2 = task.ext.args2 ?: ''
    prefix = task.ext.prefix ?: "${meta.id}"
    metaOut = meta + getRunMetadata(meta, log, api_endpoint)
    """
    tw \\
        $args \\
        --url=${api_endpoint} \\
        --access-token=$TOWER_ACCESS_TOKEN \\
        runs \\
        dump \\
        -id=${meta.id} \\
        --workspace=${meta.workspace} \\
        --output="${prefix}.tar.gz" \\
        $args2

    mkdir -p ${prefix}
    tar \\
        -xvf \\
        ${prefix}.tar.gz \\
        -C ${prefix}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        seqera-cli: \$(echo \$(tw --version 2>&1) | sed 's/^.*Tower CLI version //; s/ *\$//')
    END_VERSIONS
    """
}
