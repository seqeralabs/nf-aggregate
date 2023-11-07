process CUSTOM_DUMPSOFTWAREVERSIONS {
    label 'process_single'

    // Requires `pyyaml` which does not have a dedicated container but is in the MultiQC container
    conda 'modules/nf-core/custom/dumpsoftwareversions/environment.yml'

    input:
    path versions

    output:
    path "software_versions.yml"    , emit: yml
    path "software_mqc_versions.yml", emit: mqc_yml
    path "versions.yml"             , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    template 'dumpsoftwareversions.py'
}
