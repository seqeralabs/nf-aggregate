// Process AWS CUR parquet into normalized costs CSV
// Handles both CUR 1.0 (flattened columns) and CUR 2.0 (MAP format)
process CLEAN_CUR {

    conda 'python=3.12 duckdb=1.3 typer=0.15 pyarrow=18'
    container 'community.wave.seqera.io/library/python_duckdb_typer_pyarrow:19ccd807ea5ffdd2'

    input:
    path cur_parquet

    output:
    path "costs.csv",    emit: costs_csv
    path "versions.yml", emit: versions

    script:
    """
    clean_cur.py \\
        ${cur_parquet} \\
        --output costs.csv

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        duckdb: \$(python -c "import duckdb; print(duckdb.__version__)")
    END_VERSIONS
    """
}
