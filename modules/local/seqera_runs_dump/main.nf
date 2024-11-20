include { getRunMetadata } from './functions'

def mod_container = switch([workflow.containerEngine, workflow.profile]) {
    case {it[0] == 'singularity' &&  it[1].contains('arm')} -> 'tower-cli:0.9.2--5198075f4b9d6343'
    case {it[0] == 'singularity'} -> 'tower-cli:0.9.2--caeb70536524603e'
    case {it[1].contains('arm')} -> 'tower-cli:0.9.2--a2fbb3505faf1193'
    default -> 'tower-cli:0.9.2--28258d337ec30808'
}

process SEQERA_RUNS_DUMP {
    tag "$meta.id"
    conda 'tower-cli=0.9.2'
    container mod_container

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
    prefix = task.ext.prefix ?: "${meta.id}"
    metaOut = meta + getRunMetadata(meta, log, api_endpoint, java_truststore_path, java_truststore_password)
    def fusion = metaOut.fusion ? '--add-fusion-logs' : ''
    javaTrustStore = java_truststore_path ? "-Djavax.net.ssl.trustStore=${java_truststore_path}" : ''
    javaTrustStorePassword = java_truststore_password ? "-Djavax.net.ssl.trustStorePassword=${java_truststore_password}" : ''
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
