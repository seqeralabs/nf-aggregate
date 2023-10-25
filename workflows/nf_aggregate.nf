//
// WORKFLOW: Run main seqeralabs/nf-aggregate workflow
//

include { SEQERA_RUNS_DUMP } from '../modules/local/seqera_runs_dump'

workflow NF_AGGREGATE {

    take:
    ids       // channel: run ids read in from --input
    workspace //  string: workspace name e.g. community/showcase

    main:

    ch_versions = Channel.empty()

    SEQERA_RUNS_DUMP (
        ids,
        workspace
    )
    ch_versions = ch_versions.mix(SEQERA_RUNS_DUMP.out.versions.first())

    emit:
    versions = ch_versions
}
