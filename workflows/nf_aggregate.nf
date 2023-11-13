//
// WORKFLOW: Run main seqeralabs/nf-aggregate workflow
//

include { SEQERA_RUNS_DUMP            } from '../modules/local/seqera_runs_dump'
include { PLOT_RUN_GANTT              } from '../modules/local/plot_run_gantt'
include { MULTIQC                     } from '../modules/nf-core/multiqc'
include { CUSTOM_DUMPSOFTWAREVERSIONS } from '../modules/nf-core/custom/dumpsoftwareversions'
include { AWS_S3_LS_MULTIQC           } from '../subworkflows/local/aws_s3_ls_multiqc'
include { paramsSummaryMultiqc        } from '../subworkflows/local/nf_aggregate_utils'
include { getWorkflowName             } from '../subworkflows/local/nf_aggregate_utils'
include { getWorkflowWorkDir          } from '../subworkflows/local/nf_aggregate_utils'
include { paramsSummaryMap            } from 'plugin/nf-validation'

workflow NF_AGGREGATE {

    take:
    ids                   // channel: run ids read in from --input
    workspace             //  string: workspace name e.g. community/showcase
    multiqc_config        // channel: default config file used by MultiQC
    multiqc_custom_config // channel: user specified custom config file used by MultiQC
    multiqc_logo          // channel: logo rendered in MultiQC report
    aws_account_id        //  string: AWS account number
    aws_role_name         //  string: AWS role name

    main:

    ch_versions = Channel.empty()
    ch_multiqc_files = Channel.empty()

    //
    // MODULE: Fetch run information via the Seqera CLI
    //
    SEQERA_RUNS_DUMP (
        ids,
        workspace
    )
    ch_versions = ch_versions.mix(SEQERA_RUNS_DUMP.out.versions.first())

    SEQERA_RUNS_DUMP
        .out
        .workflow_json
        .map { 
            id, json ->
                [ "${getWorkflowName(json)}_${id}", getWorkflowWorkDir(json) ]
        }
        .branch {
            id, path ->
                aws  : path.startsWith('s3://')
                    return [ id, path ]
                azure: path.startsWith('az://')
                    return [ id, path ]
                gcp  : path.startsWith('gs://')
                    return [ id, path ]
                local: path.startsWith('/')
                    return [ id, path ]
        }
        .set { ch_work_dirs }

    //
    // SUBWORKFLOW: Get size of work directory on AWS
    //
    if (aws_account_id && aws_role_name) {
        def work_multiqc_header = """
            # plot_type: 'generalstats'
            Sample Name\tWork storage (GB)
            """.stripIndent()
        AWS_S3_LS_MULTIQC (
            ch_work_dirs.aws,
            aws_account_id,
            aws_role_name,
            work_multiqc_header,
            'work_bucket_listing'
        )
        ch_versions = ch_versions.mix(AWS_S3_LS_MULTIQC.out.versions.first())
        ch_multiqc_files = ch_multiqc_files.mix(AWS_S3_LS_MULTIQC.out.bucket_size_multiqc)
    }

    //
    // MODULE: Generate Gantt chart for workflow execution
    //
    if (!params.skip_run_gantt) {
        PLOT_RUN_GANTT (
            SEQERA_RUNS_DUMP.out.run_dump
        )
        ch_versions = ch_versions.mix(PLOT_RUN_GANTT.out.versions.first())
    }

    //
    // MODULE: Pipeline reporting
    //
    CUSTOM_DUMPSOFTWAREVERSIONS (
        ch_versions.unique().collectFile(name: 'collated_versions.yml')
    )
    
    //
    // MODULE: MultiQC
    //
    ch_multiqc_report = Channel.empty()
    if (!params.skip_multiqc) {
        summary_params = paramsSummaryMap(workflow, parameters_schema: "nextflow_schema.json")
        ch_workflow_summary = Channel.value(paramsSummaryMultiqc(summary_params))
        ch_multiqc_files = ch_multiqc_files.mix(ch_workflow_summary.collectFile(name: 'workflow_summary_mqc.yaml'))
        ch_multiqc_files = ch_multiqc_files.mix(CUSTOM_DUMPSOFTWAREVERSIONS.out.mqc_yml.collect())
        ch_multiqc_files = ch_multiqc_files.mix(SEQERA_RUNS_DUMP.out.run_dump.collect{it[1]})
        MULTIQC (
            ch_multiqc_files.collect(),
            multiqc_config.toList(),
            multiqc_custom_config.toList(),
            multiqc_logo.toList()
        )
        ch_multiqc_report = MULTIQC.out.report
    }

    emit:
    multiqc_report = ch_multiqc_report
    versions       = ch_versions
}
