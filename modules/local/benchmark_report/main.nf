process BENCHMARK_REPORT {
    debug true

    container 'cr.seqera.io/scidev/benchmark-reports:sha-7fe0d8e'
    stageInMode 'copy'

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
    # Store task work directory at beginning
    TASK_DIR="\$PWD"

    # Create the samplesheet header
    echo "group,file_path" > ${benchmark_samplesheet}

    # Add each group and file path with full task directory path
    ${groups.withIndex().collect { group, idx ->
        "echo '${group},/project/${run_dumps[idx]}' >> ${benchmark_samplesheet}"
    }.join('\n')}

    # Copy run dumps to /project directory
    cp -r ${run_dumps} /project/

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
