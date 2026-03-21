// Benchmark report v2: Python + DuckDB + eCharts (replaces R/Quarto)
process BENCHMARK_REPORT_V2 {

    conda 'python=3.12 duckdb=1.3 jinja2=3.1 typer=0.15 pyarrow=18 pyyaml=6'
    container 'ghcr.io/seqeralabs/nf-agg:python-duckdb'

    input:
    path data_dir
    path benchmark_aws_cur_report
    path brand_yml
    path logo_svg

    output:
    path "benchmark_report.html", emit: html
    path "versions.yml",          emit: versions

    script:
    def cost_flag = benchmark_aws_cur_report ? "--costs ${benchmark_aws_cur_report}" : ""
    def brand_flag = brand_yml ? "--brand ${brand_yml}" : ""
    def logo_flag = logo_svg ? "--logo ${logo_svg}" : ""
    """
    benchmark_report.py \\
        --data-dir ${data_dir} \\
        ${cost_flag} \\
        ${brand_flag} \\
        ${logo_flag} \\
        --output benchmark_report.html

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        duckdb: \$(python -c "import duckdb; print(duckdb.__version__)")
    END_VERSIONS
    """
}
