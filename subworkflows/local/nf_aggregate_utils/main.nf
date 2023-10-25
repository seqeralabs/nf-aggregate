//
// Subworkflow with functionality specific to the nf-aggregate pipeline
//

/*
========================================================================================
    IMPORT MODULES/SUBWORKFLOWS
========================================================================================
*/

include { NEXTFLOW_PIPELINE_UTILS; getWorkflowVersion } from '../../nf-core/nextflowpipelineutils/main'
include { NF_VALIDATION_PLUGIN_UTILS                  } from '../../nf-core/nfvalidation_plugin_utils/main.nf'

/*
========================================================================================
    SUBWORKFLOW TO INITIALISE PIPELINE
========================================================================================
*/

workflow PIPELINE_INITIALISATION {

    main:

    //
    // Print version and exit if required and dump pipeline parameters to JSON file
    //
    NEXTFLOW_PIPELINE_UTILS (
        params.version,
        true,
        params.outdir,
        workflow.profile.tokenize(',').intersect(['conda', 'mamba']).size() >= 1
    )

    //
    // Validate parameters and generate parameter summary to stdout
    //
    def pre_help_text = ''
    def post_help_text = ''
    def String workflow_command = "nextflow run ${workflow.manifest.name} -profile <docker/singularity/.../institute> --input ids.txt --outdir <OUTDIR>"
    NF_VALIDATION_PLUGIN_UTILS (
        params.help,
        workflow_command,
        pre_help_text,
        post_help_text,
        params.validate_params,
        "nextflow_schema.json"
    )

    // Read in ids from --input file
    Channel
        .from(file(params.input))
        .splitCsv(header:false, sep:'', strip:true)
        .map { it[0] }
        .unique()
        .set { ch_ids }

    emit:
    ids            = ch_ids
    summary_params = NF_VALIDATION_PLUGIN_UTILS.out.summary_params
}

/*
========================================================================================
    SUBWORKFLOW FOR PIPELINE COMPLETION
========================================================================================
*/

workflow PIPELINE_COMPLETION {

    take:
    versions // channel: software tools versions

    main:

    //
    // MODULE: Dump software versions for all tools used in the workflow
    //
    pipeline_version_info = Channel.of("""\"workflow\":
        nextflow: ${workflow.nextflow.version}
        ${workflow.manifest.name}: ${workflow.manifest.version}
    """.stripIndent())

    versions = versions.mix(pipeline_version_info)
    versions.collectFile(name: 'nf_aggregate_mqc_versions.yml', storeDir: "${params.outdir}/pipeline_info")
}