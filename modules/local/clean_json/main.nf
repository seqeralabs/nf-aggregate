// Clean raw Seqera API JSON into normalized CSVs
process CLEAN_JSON {

    conda 'python=3.12 duckdb=1.3 typer=0.15 pyyaml=6'

    input:
    path data_dir

    output:
    path "cleaned/runs.csv",    emit: runs_csv
    path "cleaned/tasks.csv",   emit: tasks_csv
    path "cleaned/metrics.csv", emit: metrics_csv, optional: true
    path "versions.yml",        emit: versions

    script:
    """
    clean_json.py \\
        --data-dir ${data_dir} \\
        --output-dir cleaned

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        duckdb: \$(python -c "import duckdb; print(duckdb.__version__)")
    END_VERSIONS
    """
}
