// Extract a run-data tarball into a directory of JSON files
process EXTRACT_TARBALL {
    tag "${meta.id}"

    input:
    tuple val(meta), path(tarball)

    output:
    tuple val(meta), path("${prefix}"), emit: extracted
    path "versions.yml",                emit: versions

    script:
    prefix = task.ext.prefix ?: "${meta.id}"
    """
    mkdir -p ${prefix}
    tar -xzf ${tarball} -C ${prefix}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        tar: \$(tar --version | head -1 | sed 's/.*(GNU tar) //')
    END_VERSIONS
    """
}
