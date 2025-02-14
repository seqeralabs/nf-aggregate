process BENCHMARK_REPORT {
    debug true

    container 'cr.seqera.io/scidev/benchmark-reports:sha-7fe0d8e'

    input:
    path run_dumps
    path benchmark_samplesheet
    path benchmark_report_cost_allocation_file
    val  benchmark_report_name

    output:
    path "benchmark_report.html" , emit: benchmark_html
    path "versions.yml"          , emit: versions

    script:
    def aws_cost_param = benchmark_report_cost_allocation_file ? "--profile cost -P 'aws_cost:/${benchmark_report_cost_allocation_file}'" : ""
    """
    initial_workdir="\$PWD"
    cp ${benchmark_samplesheet} /project/${benchmark_samplesheet}
    cd /project
    export HOME=\$PWD
    export QUARTO_CACHE=/tmp/quarto/cache
    export XDG_CACHE_HOME=/tmp/quarto
    mkdir -p /tmp/quarto/cache

    # Set up R environment from renv
    export R_LIBS_USER=/project/renv/library/linux-ubuntu-noble/R-4.4/x86_64-pc-linux-gnu

    quarto render ${benchmark_report_name} \\
        -P log_csv:${benchmark_samplesheet} \\
        --output benchmark_report.html \\
        --output-dir .
    cp /project/benchmark_report.html "\$initial_workdir/"
    cd "\$initial_workdir/"

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        quarto-cli: \$(quarto -v)
    END_VERSIONS
    """
}
