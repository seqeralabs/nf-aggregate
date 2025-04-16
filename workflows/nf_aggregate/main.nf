//
// WORKFLOW: Run main seqeralabs/nf-aggregate workflow
//

include { BENCHMARK_REPORT     } from '../../modules/local/benchmark_report'
include { PLOT_RUN_GANTT       } from '../../modules/local/plot_run_gantt'
include { SEQERA_RUNS_DUMP     } from '../../modules/local/seqera_runs_dump'
include { MULTIQC              } from '../../modules/nf-core/multiqc'
include { getProcessVersions   } from '../../subworkflows/local/utils_nf_aggregate'
include { getWorkflowVersions  } from '../../subworkflows/local/utils_nf_aggregate'
include { paramsSummaryMultiqc } from '../../subworkflows/local/utils_nf_aggregate'
include { paramsSummaryMap     } from 'plugin/nf-schema'

workflow NF_AGGREGATE {
    take:
    ids                      // channel: run ids read in from --input
    multiqc_custom_config    // channel: user specified custom config file used by MultiQC
    multiqc_logo             // channel: logo rendered in MultiQC report
    seqera_api_endpoint      //     val: Seqera Platform API endpoint URL
    skip_run_gantt           //     val: Skip GANTT chart creation for each run
    skip_multiqc             //     val: Skip MultiQC
    java_truststore_path     //     val: Path to java truststore if using private certs
    java_truststore_password //     val: Password for java truststore if using private certs

    main:

    // Split ids into runs to fetch logs from platform deployment and runs provided externally
        ids
        .branch {meta ->
            external: meta.workspace == 'external'
                return [meta, meta.logs]
            fetch_run_dumps: true
        }
        .set { ids_split}

    ch_versions = Channel.empty()
    ch_multiqc_files = Channel.empty()

    //
    // MODULE: Fetch run information via the Seqera CLI
    //

    SEQERA_RUNS_DUMP(
        ids_split.fetch_run_dumps,
        seqera_api_endpoint,
        java_truststore_path ?: '',
        java_truststore_password ?: '',
    )
    ch_versions = ch_versions.mix(SEQERA_RUNS_DUMP.out.versions)

    // Merge run dumps with external runs
    SEQERA_RUNS_DUMP.out.run_dump
        .mix(ids_split.external)
        .set{ ch_all_runs }

    //
    // MODULE: Generate Gantt chart for workflow execution
    //
    if(!params.skip_run_gantt){
        ch_all_runs
            .filter { meta, _run_dir -> meta.fusion}
            .set { ch_runs_for_gantt }

        PLOT_RUN_GANTT(
            ch_runs_for_gantt
        )
        ch_versions = ch_versions.mix(PLOT_RUN_GANTT.out.versions)
    }

    //
    // MODULE: Generate benchmark report
    //
    if (params.generate_benchmark_report) {
        // Check if cur report is specified
        aws_cur_report = params.benchmark_aws_cur_report ? Channel.fromPath(params.benchmark_aws_cur_report) : []

        BENCHMARK_REPORT(
            ch_all_runs.collect { it[1] },
            ch_all_runs.collect { it[0].group },
            aws_cur_report,
            params.remove_failed_tasks,
        )
        ch_versions = ch_versions.mix(BENCHMARK_REPORT.out.versions)
    }

    //
    // Collate software versions
    //
    ch_versions
        .unique()
        .map { getProcessVersions(it) }
        .mix(Channel.of(getWorkflowVersions()))
        .collectFile(storeDir: "${params.outdir}/pipeline_info", name: 'collated_software_mqc_versions.yml', newLine: true)
        .set { ch_collated_versions }

    //
    // MODULE: MultiQC
    //
    ch_multiqc_report = Channel.empty()
    if (!skip_multiqc) {
        ch_multiqc_config = Channel.fromPath("${projectDir}/workflows/nf_aggregate/assets/multiqc_config.yml", checkIfExists: true)
        summary_params = paramsSummaryMap(workflow, parameters_schema: "nextflow_schema.json")
        ch_workflow_summary = Channel.value(paramsSummaryMultiqc(summary_params))
        ch_multiqc_files = ch_multiqc_files.mix(ch_workflow_summary.collectFile(name: 'workflow_summary_mqc.yaml'))
        ch_multiqc_files = ch_multiqc_files.mix(ch_collated_versions)
        ch_multiqc_files = ch_multiqc_files.mix(ch_all_runs.collect { it[1] })

        MULTIQC(
            ch_multiqc_files.collect(),
            ch_multiqc_config.toList(),
            multiqc_custom_config.toList(),
            multiqc_logo.toList(),
            [],
            [],
        )

        ch_multiqc_report = MULTIQC.out.report
    }

    emit:
    multiqc_report = ch_multiqc_report
    versions       = ch_versions
}
