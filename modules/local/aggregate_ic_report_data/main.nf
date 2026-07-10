process AGGREGATE_IC_REPORT_DATA {

    conda 'python=3.12 typer=0.15 pyyaml=6'
    container 'community.wave.seqera.io/library/python_duckdb_jinja2_typer_pruned:2d95e1e826bbe38f'

    input:
    path jsonl_bundle
    val web_base

    output:
    path "report_data_ic.json", emit: data
    path "versions.yml", emit: versions

    script:
    """
    aggregate_ic_report_data.py \\
        --jsonl-dir ${jsonl_bundle} \\
        --web-base ${web_base} \\
        --output report_data_ic.json

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
    END_VERSIONS
    """
}
