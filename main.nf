#!/usr/bin/env nextflow
/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    seqeralabs/nf-aggregate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Github : https://github.com/seqeralabs/nf-aggregate
----------------------------------------------------------------------------------------
*/

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    IMPORT FUNCTIONS / MODULES / SUBWORKFLOWS / WORKFLOWS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

include { NF_AGGREGATE } from './workflows/nf_aggregate'
include {
    checkCondaChannels
    dumpParametersToJSON
    getWorkflowVersion
} from 'plugin/nf-core-utils'
include {
    paramsSummaryLog
    samplesheetToList
    validateParameters
} from 'plugin/nf-schema'

/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    NAMED WORKFLOWS FOR PIPELINE
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

//
// WORKFLOW: Run main analysis pipeline depending on type of input
//
workflow SEQERALABS_NF_AGGREGATE {
    take:
    samplesheet // channel: samplesheet read in from --input

    main:
    if (params.version) {
        log.info("${workflow.manifest.name} ${getWorkflowVersion()}")
        System.exit(0)
    }

    if (workflow.profile.tokenize(',').intersect(['conda', 'mamba'])) {
        checkCondaChannels()
    }

    log.info paramsSummaryLog(workflow)

    if (params.validate_params) {
        validateParameters()
    }

    ch_ids = Channel
        .fromList(samplesheetToList(samplesheet, 'assets/schema_input.json'))
        .flatten()

    //
    // WORKFLOW: Run pipeline
    //
    NF_AGGREGATE(
        ch_ids,
        params.seqera_api_endpoint,
        params.java_truststore_path,
        params.java_truststore_password,
    )
}
/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    RUN MAIN WORKFLOW
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
*/

workflow {

    //
    // WORKFLOW: Run main workflow
    //
    SEQERALABS_NF_AGGREGATE(
        params.input
    )
}

workflow.onComplete {
    dumpParametersToJSON(params.outdir, params, workflow.launchDir)
}
