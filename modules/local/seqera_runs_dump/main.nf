include { getRunMetadata } from './functions'

process SEQERA_RUNS_DUMP {
    tag "$meta.id"
    conda 'tower-cli=0.9.2'
    container 'seqeralabs/nf-aggregate:tower-cli-0.9.2--hdfd78af_1'

    input:
    val meta
    val api_endpoint
    val java_truststore_path
    val java_truststore_password

    output:
    tuple val(metaOut), path("${prefix}"), emit: run_dump
    path "versions.yml"                  , emit: versions

    script:
    def args = task.ext.args ?: ''
    def args2 = task.ext.args2 ?: ''
    def prefix = task.ext.prefix ?: "${meta.id}"
    def metaOut = meta + getRunMetadata(meta, log, api_endpoint, java_truststore_path, java_truststore_password)
    def fusion = metaOut.fusion ? '--add-fusion-logs' : ''
    def javaTrustStore = java_truststore_path ? "-Djavax.net.ssl.trustStore=${java_truststore_path}" : ''
    def javaTrustStorePassword = java_truststore_password ? "-Djavax.net.ssl.trustStorePassword=${java_truststore_password}" : ''
    """
    tw \\
        $args \\
        $javaTrustStore \\
        $javaTrustStorePassword \\
        --url=${api_endpoint} \\
        --access-token=$TOWER_ACCESS_TOKEN \\
        runs \\
        dump \\
        -id=${meta.id} \\
        --workspace=${meta.workspace} \\
        --output="${prefix}.tar.gz" \\
        $fusion \\
        $args2

    mkdir -p ${prefix}
    tar \\
        -xvf \\
        ${prefix}.tar.gz \\
        -C ${prefix}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        seqera-cli: \$(echo \$(NO_COLOR=true tw --version 2>&1) | sed 's/^.*Tower CLI version //; s/ *\$//')
    END_VERSIONS
    """
}
