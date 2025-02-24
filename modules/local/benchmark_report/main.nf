process BENCHMARK_REPORT {

    container 'cr.seqera.io/scidev/benchmark-reports:sha-7fe0d8e'
    containerOptions '--user root'

    input:
    path run_dumps
    val  groups
    path benchmark_aws_cur_report

    output:
    path "benchmark_report.html" , emit: benchmark_html
    path "versions.yml"          , emit: versions

    script:
    def aws_cost_param = benchmark_aws_cur_report ? "--profile cost -P aws_cost:\$TASK_DIR/${benchmark_aws_cur_report}" : ""
    def benchmark_samplesheet = "benchmark_samplesheet.csv"

    """
    # Set up R environment from renv
    export R_LIBS_USER=/project/renv/library/linux-ubuntu-noble/R-4.4/x86_64-pc-linux-gnu
    TASK_DIR="\$PWD"

    # Setup cache directories
    export QUARTO_CACHE=/tmp/quarto/cache
    export XDG_CACHE_HOME=/tmp/quarto

    # Create the benchmark samplesheet csv
    echo "group,file_path" > ${benchmark_samplesheet}
    ${groups.withIndex().collect { group, idx ->
        "echo \"${group},\$TASK_DIR/${run_dumps[idx]}\" >> ${benchmark_samplesheet}"
    }.join('\n')}

    cd /project
    quarto render main_benchmark_report.qmd \\
        -P log_csv:"\$TASK_DIR/"${benchmark_samplesheet} \\
        $aws_cost_param \\
        --output-dir .\\
        --output benchmark_report.html

    cp /project/benchmark_report.html "\$TASK_DIR/"
    cd "\$TASK_DIR/"

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        quarto-cli: \$(quarto -v)
    END_VERSIONS
    """
}
