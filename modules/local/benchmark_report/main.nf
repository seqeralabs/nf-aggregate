process BENCHMARK_REPORT {

    container 'cr.seqera.io/scidev/benchmark-reports:sha-a6d15e8'

    input:
    path run_dumps
    val  benchmark_runs
    path machine_files
    path benchmark_aws_cur_report
    val  remove_failed_tasks

    output:
    path "benchmark_report.html" , emit: benchmark_html
    path "versions.yml"          , emit: versions

    script:
    def aws_cost_param = benchmark_aws_cur_report ? "--profile cost -P aws_cost:\$TASK_DIR/${benchmark_aws_cur_report}" : ""
    def benchmark_samplesheet = "benchmark_samplesheet.csv"
    def failed_tasks = remove_failed_tasks ? "-P remove_failed_tasks:True" : ""

    """
    # Set up R environment from renv
    export R_LIBS_USER=/project/renv/library/linux-ubuntu-noble/R-4.4/x86_64-pc-linux-gnu
    TASK_DIR="\$PWD"

    # Setup cache directories
    export QUARTO_CACHE=/tmp/quarto/cache
    export XDG_CACHE_HOME=/tmp/quarto

    # Copy the baseline report project from the container and overlay repo-managed fixes.
    cp -R /project report_project
    cp -R ${projectDir}/modules/local/benchmark_report/overrides/. report_project/

    # Create the benchmark samplesheet csv
    echo "group,file_path,machines_path" > ${benchmark_samplesheet}
    ${benchmark_runs.collect { run ->
        def group = run.group ?: ''
        def fileName = run.file_name
        def machinesName = run.machines_name ?: ''
        def stagedFilePath = fileName ? "\$TASK_DIR/${fileName}" : ''
        def stagedMachinesPath = machinesName ? "\$TASK_DIR/${machinesName}" : ''
        "echo \"${group},${stagedFilePath},${stagedMachinesPath}\" >> ${benchmark_samplesheet}"
    }.join('\n')}

    cd report_project
    quarto render main_benchmark_report.qmd \\
        -P log_csv:"\$TASK_DIR/"${benchmark_samplesheet} \\
        $aws_cost_param \\
        $failed_tasks \\
        --output-dir .\\
        --output benchmark_report.html

    cp benchmark_report.html "\$TASK_DIR/"
    cd "\$TASK_DIR/"

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        r: \$(R --version | head -1 | sed 's/R version \\([0-9.]*\\).*/\\1/')
        quarto-cli: \$(quarto --version | head -1 | sed 's/quarto //g')
END_VERSIONS
    """
}
