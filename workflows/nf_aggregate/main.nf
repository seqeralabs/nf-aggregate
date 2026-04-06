//
// WORKFLOW: Run main seqeralabs/nf-aggregate workflow
//

include { BENCHMARK_REPORT        } from '../../modules/local/benchmark_report'
include { EXTRACT_TARBALL        } from '../../modules/local/extract_tarball'
include { PLOT_RUN_GANTT         } from '../../modules/local/plot_run_gantt'
include { SEQERA_RUNS_DUMP       } from '../../modules/local/seqera_runs_dump'
include { MULTIQC                } from '../../modules/nf-core/multiqc'
include { getProcessVersions     } from '../../subworkflows/local/utils_nf_aggregate'
include { getWorkflowVersions    } from '../../subworkflows/local/utils_nf_aggregate'
include { paramsSummaryMultiqc   } from '../../subworkflows/local/utils_nf_aggregate'
include { paramsSummaryMap       } from 'plugin/nf-schema'
import groovy.json.JsonOutput

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

    ch_versions = Channel.empty()
    ch_multiqc_files = Channel.empty()

    //
    // Split runs into API-fetched vs externally-provided tarballs
    //
    ids.branch {
        api:      it.workspace != 'external'
        external: it.workspace == 'external' && it.logs
    }.set { ch_split }

    // Collect API runs so the channel can be consumed by multiple operators
    ch_api_runs = ch_split.api.collect().flatMap { it }

    //
    // MODULE: Fetch run information via the Seqera CLI (API runs only)
    // Only needed when MultiQC or Gantt chart are enabled
    //
    if (!skip_multiqc || !skip_run_gantt) {
        SEQERA_RUNS_DUMP(
            ch_api_runs,
            seqera_api_endpoint,
            java_truststore_path ?: '',
            java_truststore_password ?: '',
        )
        ch_versions = ch_versions.mix(SEQERA_RUNS_DUMP.out.versions)

        //
        // MODULE: Generate Gantt chart for workflow execution (API runs only)
        //
        if (!skip_run_gantt) {
            SEQERA_RUNS_DUMP.out.run_dump
                .filter { meta, _run_dir ->
                    meta.fusion
                }
                .set { ch_runs_for_gantt }

            PLOT_RUN_GANTT(
                ch_runs_for_gantt
            )
            ch_versions = ch_versions.mix(PLOT_RUN_GANTT.out.versions)
        }
    }

    //
    // MODULE: Extract external tarballs containing run JSON data
    //
    def samplesheet_dir = file(params.input).parent
    ch_tarballs = ch_split.external.map { meta ->
        def logs_path = meta.logs.startsWith('/') ? file(meta.logs) : samplesheet_dir.resolve(meta.logs)
        [meta, file(logs_path, checkIfExists: true)]
    }
    EXTRACT_TARBALL(ch_tarballs)
    ch_versions = ch_versions.mix(EXTRACT_TARBALL.out.versions)

    //
    // BENCHMARK REPORT: JSON → DuckDB → HTML report
    //
    if (params.generate_benchmark_report) {

        // Path A: Fetch run data via API for non-external runs
        ch_api_jsons = ch_api_runs.map { meta ->
            def data = SeqeraApi.fetchRunData(meta, seqera_api_endpoint)
            data.meta = [id: meta.id, workspace: meta.workspace, group: meta.group ?: 'default']
            def json_file = file("${workDir}/run_data/${meta.id}.json")
            json_file.parent.mkdirs()
            json_file.text = JsonOutput.toJson(data)
            return json_file
        }

        // Path B: Collect JSON files from extracted tarballs
        ch_tarball_jsons = EXTRACT_TARBALL.out.extracted.flatMap { meta, dir ->
            def jsons = []
            dir.toFile().eachFileMatch(~/.*\.json/) { jsons << file(it) }
            return jsons
        }

        // Merge both paths into a single data directory
        ch_data_dir = ch_api_jsons
            .mix(ch_tarball_jsons)
            .collect()
            .map { files ->
                def dir = file("${workDir}/benchmark_data")
                dir.mkdirs()
                files.each { f -> f.copyTo(dir.resolve(f.name)) }
                return dir
            }

        ch_cur = params.benchmark_aws_cur_report
            ? Channel.fromPath(params.benchmark_aws_cur_report)
            : Channel.fromPath("${projectDir}/assets/NO_FILE", checkIfExists: false).ifEmpty(file("${projectDir}/assets/NO_FILE"))

        BENCHMARK_REPORT(
            ch_data_dir,
            ch_cur.ifEmpty(file("${projectDir}/assets/NO_FILE")),
            file("${projectDir}/assets/brand.yml", checkIfExists: true),
            file("${projectDir}/assets/seqera_logo_color.svg", checkIfExists: true),
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
    // MODULE: MultiQC (uses API run dumps only; external runs don't produce dumps)
    //
    ch_multiqc_report = Channel.empty()
    if (!skip_multiqc) {
        ch_multiqc_config = Channel.fromPath("${projectDir}/workflows/nf_aggregate/assets/multiqc_config.yml", checkIfExists: true)
        summary_params = paramsSummaryMap(workflow, parameters_schema: "nextflow_schema.json")
        ch_workflow_summary = Channel.value(paramsSummaryMultiqc(summary_params))
        ch_multiqc_files = ch_multiqc_files.mix(ch_workflow_summary.collectFile(name: 'workflow_summary_mqc.yaml'))
        ch_multiqc_files = ch_multiqc_files.mix(ch_collated_versions)
        ch_multiqc_files = ch_multiqc_files.mix(SEQERA_RUNS_DUMP.out.run_dump.collect { it[1] })

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
