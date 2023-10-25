//
// WORKFLOW: Run main seqeralabs/nf-aggregate workflow
//

include { SEQERA_RUNS_DUMP            } from '../modules/local/seqera_runs_dump'
include { MULTIQC                     } from '../modules/nf-core/multiqc'
include { CUSTOM_DUMPSOFTWAREVERSIONS } from '../modules/nf-core/custom/dumpsoftwareversions'                                                              
include { paramsSummaryMultiqc        } from '../subworkflows/local/nf_aggregate_utils'
include { paramsSummaryMap            } from 'plugin/nf-validation'

workflow NF_AGGREGATE {

    take:
    ids       // channel: run ids read in from --input
    workspace //  string: workspace name e.g. community/showcase

    main:

    ch_versions = Channel.empty()

    //
    // MODULE: Fetch run information via the Seqera CLI
    //
    SEQERA_RUNS_DUMP (
        ids,
        workspace
    )
    ch_versions = ch_versions.mix(SEQERA_RUNS_DUMP.out.versions.first())

    //
    // MODULE: Pipeline reporting
    //
    CUSTOM_DUMPSOFTWAREVERSIONS (
        ch_versions.unique().collectFile(name: 'collated_versions.yml')
    )
    
    //
    // MODULE: MultiQC
    //
    ch_multiqc_files = Channel.empty()
    summary_params = paramsSummaryMap(workflow, parameters_schema: "nextflow_schema.json")
    ch_workflow_summary = Channel.value(paramsSummaryMultiqc(summary_params))
    ch_multiqc_files = ch_multiqc_files.mix(ch_workflow_summary.collectFile(name: 'workflow_summary_mqc.yaml'))
    ch_multiqc_files = ch_multiqc_files.mix(CUSTOM_DUMPSOFTWAREVERSIONS.out.mqc_yml.collect())
    ch_multiqc_files = ch_multiqc_files.mix(SEQERA_RUNS_DUMP.out.run_dump.collect{it[1]})
    MULTIQC (
        ch_multiqc_files.collect(),
        [],
        [],
        []
    )

    emit:
    multiqc_report = MULTIQC.out.report
    versions       = ch_versions
}
