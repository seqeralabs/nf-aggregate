// Build query result JSON files from normalized CSVs using DuckDB
process BUILD_TABLES {

    conda 'python=3.12 duckdb=1.3 typer=0.15'
    container 'community.wave.seqera.io/library/python_duckdb_typer:4e41feb6944c5694'

    input:
    path runs_csv
    path tasks_csv
    path metrics_csv
    path costs_csv

    output:
    path "tables",       emit: tables_dir
    path "versions.yml", emit: versions

    script:
    def metrics_flag = metrics_csv.name != 'NO_FILE' ? "--metrics-csv ${metrics_csv}" : ""
    def costs_flag = costs_csv.name != 'NO_FILE' ? "--costs-csv ${costs_csv}" : ""
    """
    build_tables.py \\
        --runs-csv ${runs_csv} \\
        --tasks-csv ${tasks_csv} \\
        ${metrics_flag} \\
        ${costs_flag} \\
        --output-dir tables

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        duckdb: \$(python -c "import duckdb; print(duckdb.__version__)")
    END_VERSIONS
    """
}
