// Benchmark report v2: Python + DuckDB + eCharts (compatible with existing run dumps)
process BENCHMARK_REPORT_V2 {

    conda 'python=3.12 duckdb=1.3 jinja2=3.1 typer=0.12 pyarrow=18'
    container 'ghcr.io/seqeralabs/nf-agg:python-duckdb'

    input:
    path run_dumps
    val  groups
    path benchmark_aws_cur_report

    output:
    path "benchmark_report.html", emit: html
    path "versions.yml",          emit: versions

    script:
    def cost_flag = benchmark_aws_cur_report ? "--costs ${benchmark_aws_cur_report}" : ""
    """
    mkdir -p run_dumps
    ${run_dumps.withIndex().collect { run_dump, idx ->
        "ln -s \$PWD/${run_dump} run_dumps/run_${idx}"
    }.join('\n')}

    benchmark_report.py \\
        --dump-dir run_dumps \\
        ${cost_flag} \\
        --output benchmark_report.html

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        duckdb: \$(python -c "import duckdb; print(duckdb.__version__)")
    END_VERSIONS
    """
}
