process BENCHMARK_REPORT {
    debug true

    container 'cr.seqera.io/scidev/benchmark-reports:sha-7fe0d8e'

    input:
    path run_dumps
    path benchmark_samplesheet
    path benchmark_aws_cur_report

    output:
    path "benchmark_report.html" , emit: benchmark_html
    path "versions.yml"          , emit: versions

    script:
    def aws_cost_param = benchmark_aws_cur_report ? "--profile cost -P aws_cost:/${benchmark_aws_cur_report}" : ""
    """
    initial_workdir="\$PWD"

    export HOME=\$PWD
    export QUARTO_CACHE=/tmp/quarto/cache
    export XDG_CACHE_HOME=/tmp/quarto
    mkdir -p /tmp/quarto/cache

    # Set up R environment from renv
    export R_LIBS_USER=/project/renv/library/linux-ubuntu-noble/R-4.4/x86_64-pc-linux-gnu

    cd /project
    echo \$PWD
    quarto render main_benchmark_report.qmd \\
        -P log_csv:"\$initial_workdir/"${benchmark_samplesheet} \\
        --output-dir .\\
        --output benchmark_report.html

    cp /project/benchmark_report.html "\$initial_workdir/"
    cd "\$initial_workdir/"

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        quarto-cli: \$(quarto -v)
    END_VERSIONS
    """
}
