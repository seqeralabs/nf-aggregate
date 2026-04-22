process RENDER_BENCHMARK_REPORT {

    conda 'python=3.12 jinja2=3.1 typer=0.15 pyyaml=6'
    container 'community.wave.seqera.io/library/python_duckdb_jinja2_typer_pruned:2d95e1e826bbe38f'

    input:
    path report_data_json
    path brand_yml
    path logo_svg

    output:
    path "benchmark_report.html", emit: html
    path "versions.yml",          emit: versions

    script:
    def brand_flag = brand_yml.name != 'NO_FILE' ? "--brand ${brand_yml}" : ""
    def logo_flag = logo_svg.name != 'NO_FILE' ? "--logo ${logo_svg}" : ""
    """
    render_benchmark_report.py \\
        --data ${report_data_json} \\
        ${brand_flag} \\
        ${logo_flag} \\
        --output benchmark_report.html

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
    END_VERSIONS
    """
}
