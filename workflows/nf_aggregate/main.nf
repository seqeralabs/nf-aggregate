//
// WORKFLOW: Run main seqeralabs/nf-aggregate workflow
//

include { BENCHMARK_REPORT        } from '../../modules/local/benchmark_report'
include { EXTRACT_TARBALL        } from '../../modules/local/extract_tarball'
include { softwareVersionsToYAML } from 'plugin/nf-core-utils'

workflow NF_AGGREGATE {
    take:
    ids                      // channel: run ids read in from --input
    seqera_api_endpoint      //     val: Seqera Platform API endpoint URL
    java_truststore_path     //     val: Path to java truststore if using private certs
    java_truststore_password //     val: Password for java truststore if using private certs

    main:

    ch_versions = Channel.empty()

    //
    // Split runs into API-fetched vs externally-provided tarballs
    //
    ids.branch {
        api:      it.workspace != 'external'
        external: it.workspace == 'external' && it.logs
    }.set { ch_split }

    ch_api_runs = ch_split.api

    if (!params.generate_benchmark_report) {
        ch_split.api.count().subscribe { n ->
            if (n > 0) {
                log.warn "Found ${n} API run(s) but --generate_benchmark_report is not enabled. " +
                         "API runs will not produce any output. Enable --generate_benchmark_report to process them."
            }
        }
    }

    //
    // MODULE: Extract external tarballs containing run JSON data
    //
    def samplesheet_dir = file(params.input).parent
    ch_external_logs = ch_split.external.map { meta ->
        def logs_path = meta.logs.startsWith('/') ? file(meta.logs) : samplesheet_dir.resolve(meta.logs)
        [meta, file(logs_path, checkIfExists: true)]
    }

    ch_external_logs.branch {
        dirs:     it[1].isDirectory()
        tarballs: !it[1].isDirectory()
    }.set { ch_external_split }

    EXTRACT_TARBALL(ch_external_split.tarballs)
    ch_versions = ch_versions.mix(EXTRACT_TARBALL.out.versions)

    //
    // BENCHMARK REPORT: JSON → DuckDB → HTML report
    //
    if (params.generate_benchmark_report) {

        // Path A: Fetch run data via API for non-external runs
        ch_api_jsons = ch_api_runs.map { meta ->
            def data = null
            def maxRetries = 3
            for (int attempt = 1; attempt <= maxRetries; attempt++) {
                try {
                    data = SeqeraApi.fetchRunData(meta, seqera_api_endpoint)
                    break
                } catch (Exception e) {
                    if (attempt == maxRetries) {
                        throw new RuntimeException("Failed to fetch run data for ${meta.id} after ${maxRetries} attempts: ${e.message}", e)
                    }
                    def sleepMs = 1000 * Math.pow(2, attempt - 1) as long
                    log.warn "API call failed for run ${meta.id} (attempt ${attempt}/${maxRetries}), retrying in ${sleepMs}ms: ${e.message}"
                    Thread.sleep(sleepMs)
                }
            }
            data.meta = [id: meta.id, workspace: meta.workspace, group: meta.group ?: 'default']
            def tmpDir = java.nio.file.Files.createTempDirectory("nf-agg-run-${meta.id}-")
            def json_file = file(tmpDir.resolve("${meta.id}.json"))
            json_file.text = groovy.json.JsonOutput.toJson(data)
            return json_file
        }

        // Path B: Collect JSON files from extracted tarballs
        ch_tarball_jsons = EXTRACT_TARBALL.out.extracted.flatMap { meta, dir ->
            def jsons = []
            dir.toFile().eachFileMatch(~/.*\.json/) { jsons << file(it) }
            return jsons
        }

        ch_external_dir_jsons = ch_external_split.dirs.flatMap { meta, dir ->
            def jsons = []
            dir.toFile().eachFileMatch(~/.*\.json/) { jsons << file(it) }
            return jsons
        }

        // Merge both paths into a single data directory
        ch_data_dir = ch_api_jsons
            .mix(ch_tarball_jsons)
            .mix(ch_external_dir_jsons)
            .collect()
            .map { files ->
                def dir = file(java.nio.file.Files.createTempDirectory("nf-agg-benchmark-"))
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
    softwareVersionsToYAML(
        softwareVersions: ch_versions.unique(),
        nextflowVersion: workflow.nextflow.version,
    ).collectFile(
        storeDir: "${params.outdir}/pipeline_info",
        name: 'collated_software_versions.yml',
        sort: true,
        newLine: true,
    )

    emit:
    versions = ch_versions
}
