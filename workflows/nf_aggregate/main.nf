//
// WORKFLOW: Run main seqeralabs/nf-aggregate workflow
//

include { NORMALIZE_BENCHMARK_JSONL      } from '../../modules/local/normalize_benchmark_jsonl'
include { AGGREGATE_BENCHMARK_REPORT_DATA } from '../../modules/local/aggregate_benchmark_report_data'
include { RENDER_BENCHMARK_REPORT         } from '../../modules/local/render_benchmark_report'
include { EXTRACT_TARBALL                 } from '../../modules/local/extract_tarball'
include { AGGREGATE_IC_REPORT_DATA } from '../../modules/local/aggregate_ic_report_data'
include { RENDER_IC_REPORT          } from '../../modules/local/render_ic_report'
include { softwareVersionsToYAML          } from 'plugin/nf-core-utils'

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
                log.warn(
                    "Found ${n} API run(s) but --generate_benchmark_report is not enabled. " +
                    "API runs will not produce any output. Enable --generate_benchmark_report to process them."
                )
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
    // BENCHMARK REPORT: raw JSON -> JSONL bundle -> report_data.json -> HTML
    //
    if (params.generate_benchmark_report) {

        def benchmark_work_root = file("${workflow.workDir}/nf-agg/${workflow.runName}")
        benchmark_work_root.mkdirs()
        def api_json_dir = file(benchmark_work_root.resolve("api-json"))
        api_json_dir.mkdirs()

        // Path A: Fetch run data via API for non-external runs
        ch_api_jsons = ch_api_runs.map { meta ->
            def maxRetries = 3
            def data = (1..maxRetries).findResult { attempt ->
                try {
                    return SeqeraApi.fetchRunData(meta, seqera_api_endpoint)
                } catch (Exception e) {
                    if (attempt == maxRetries) {
                        throw new RuntimeException("Failed to fetch run data for ${meta.id} after ${maxRetries} attempts: ${e.message}", e)
                    }
                    def sleepMs = 1000 * Math.pow(2, attempt - 1) as long
                    log.warn "API call failed for run ${meta.id} (attempt ${attempt}/${maxRetries}), retrying in ${sleepMs}ms: ${e.message}"
                    Thread.sleep(sleepMs)
                    return null
                }
            }
            data.meta = [
                id:        meta.id,
                workspace: meta.workspace,
                group:     meta.group ?: 'default',
                platform:  meta.platform ?: null,
                token_env: meta.token_env ?: null,
            ]
            def json_file = file(api_json_dir.resolve("${meta.id}.json"))
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
                def dir = file(benchmark_work_root.resolve("benchmark-data"))
                if (dir.exists()) dir.deleteDir()
                dir.mkdirs()
                files.each { f -> f.copyTo(dir.resolve(f.name)) }
                return dir
            }

        // One CUR parquet param serves both report types (Fusion benchmark + Intelligent
        // Compute) — the data exports are the same shape. Seqera's own cost estimate is
        // never used because it is unreliable.
        //
        // A DIRECTORY location is probed here, on the head node, before anything is staged.
        // The task cannot diagnose this itself: from inside the container an export prefix it
        // is not allowed to LIST is indistinguishable from an empty one, and by then a task
        // has already been provisioned and run for minutes. The probe uses the pipeline's own
        // credentials, so a location that is missing, empty or inaccessible stops the run
        // immediately, naming the path and what to grant.
        ch_cur = Channel.value([])
        if (params.benchmark_aws_cur_report) {
            def cur_location = params.benchmark_aws_cur_report.toString().trim()
            if (!cur_location.toLowerCase().endsWith('.parquet')) {
                def cur_glob = "${cur_location.replaceAll('/+$', '')}/**/*.parquet"
                def cur_matches = null
                try {
                    cur_matches = file(cur_glob)
                }
                catch (Exception probe_error) {
                    throw new RuntimeException(
                        "Could not list the AWS CUR export at '${cur_location}'. " +
                        "The pipeline needs s3:ListBucket and s3:GetObject on that bucket and prefix — " +
                        "a directory location needs LIST, not just object read. Grant those to the " +
                        "compute environment's role, or point --benchmark_aws_cur_report at a single " +
                        "*.parquet file, which needs only object read. Original error: ${probe_error.message}",
                        probe_error
                    )
                }
                if (!cur_matches) {
                    throw new RuntimeException(
                        "No *.parquet files found in the AWS CUR export at '${cur_location}' " +
                        "(searched '${cur_glob}'). Point --benchmark_aws_cur_report at the export " +
                        "directory that holds the parquet files (for AWS Data Exports this is the " +
                        "'data/' folder, partitioned by BILLING_PERIOD), or at a single *.parquet file. " +
                        "An empty result can also mean the role may read objects but not LIST the prefix."
                    )
                }
                log.info("Found ${cur_matches.size()} parquet file(s) in the AWS CUR export at ${cur_location}")
            }
            ch_cur = Channel.fromPath(cur_location, type: 'any')
        }

        // Cost-label overrides for the CUR search: accept EITHER a YAML/JSON file
        // (path, local or S3) OR inline YAML/JSON pasted straight into the launch form.
        // A real file is used as-is; anything else is treated as inline content and
        // materialised to a file, so NORMALIZE_BENCHMARK_JSONL always receives a plain
        // YAML file. Custom keys are searched IN ADDITION to the built-in Seqera defaults.
        ch_cur_label_map = Channel.value([])
        if (params.benchmark_aws_cur_label_map) {
            def raw_label_map = params.benchmark_aws_cur_label_map
            // A pasted form value is a String (path or inline YAML/JSON); a -params-file
            // may already parse it into a Map/List — serialise that to JSON (valid YAML).
            def label_map_content = (raw_label_map instanceof CharSequence)
                ? raw_label_map.toString()
                : groovy.json.JsonOutput.toJson(raw_label_map)
            // glob: false — inline YAML/JSON contains { and [ which file() would
            // otherwise treat as glob metacharacters and return a list.
            def label_map_file = file(label_map_content, glob: false)
            if (!label_map_file.exists()) {
                label_map_file = file(benchmark_work_root.resolve('cost_label_map.yml'))
                label_map_file.text = label_map_content
            }
            ch_cur_label_map = Channel.value(label_map_file)
        }

        // Collect machine metrics CSVs from external runs (if present)
        ch_machines_dir = ch_split.external
            .filter { it.machines }
            .map { meta ->
                def machines_path = meta.machines.startsWith('/') ? file(meta.machines) : samplesheet_dir.resolve(meta.machines)
                file(machines_path, checkIfExists: true)
            }
            .collect()
            .map { files ->
                if (!files) return []
                def dir = file(benchmark_work_root.resolve("machines"))
                if (dir.exists()) dir.deleteDir()
                dir.mkdirs()
                files.each { f -> f.copyTo(dir.resolve(f.name)) }
                return dir
            }
            .ifEmpty([])

        NORMALIZE_BENCHMARK_JSONL(
            ch_data_dir,
            ch_cur,
            ch_cur_label_map,
            ch_machines_dir,
        )
        ch_versions = ch_versions.mix(NORMALIZE_BENCHMARK_JSONL.out.versions)

        if (params.report_type == 'intelligent_compute') {
            AGGREGATE_IC_REPORT_DATA(
                NORMALIZE_BENCHMARK_JSONL.out.jsonl,
                params.seqera_web_url,
                params.include_failed_runs,
            )
            ch_versions = ch_versions.mix(AGGREGATE_IC_REPORT_DATA.out.versions)

            RENDER_IC_REPORT(
                AGGREGATE_IC_REPORT_DATA.out.data,
                file("${projectDir}/assets/brand.yml", checkIfExists: true),
                file("${projectDir}/assets/seqera_logo_color.svg", checkIfExists: true),
            )
            ch_versions = ch_versions.mix(RENDER_IC_REPORT.out.versions)
        }
        else {
            AGGREGATE_BENCHMARK_REPORT_DATA(
                NORMALIZE_BENCHMARK_JSONL.out.jsonl,
                params.include_failed_runs,
            )
            ch_versions = ch_versions.mix(AGGREGATE_BENCHMARK_REPORT_DATA.out.versions)

            RENDER_BENCHMARK_REPORT(
                AGGREGATE_BENCHMARK_REPORT_DATA.out.data,
                file("${projectDir}/assets/brand.yml", checkIfExists: true),
                file("${projectDir}/assets/seqera_logo_color.svg", checkIfExists: true),
            )
            ch_versions = ch_versions.mix(RENDER_BENCHMARK_REPORT.out.versions)
        }
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
