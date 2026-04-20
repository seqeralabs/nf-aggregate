process AGGREGATE_BENCHMARK_REPORT_DATA {

    conda 'python=3.12 typer=0.15 pyyaml=6'
    container 'community.wave.seqera.io/library/python_duckdb_jinja2_typer_pruned:2d95e1e826bbe38f'

    input:
    path jsonl_bundle

    output:
    path "report_data.json", emit: data
    path "versions.yml",     emit: versions

    script:
    """
    benchmark_report.py \\
        --jsonl-dir ${jsonl_bundle} \\
        --output report_data.json

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
    END_VERSIONS
    """
}
