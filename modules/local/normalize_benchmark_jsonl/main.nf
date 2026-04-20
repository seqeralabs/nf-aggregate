process NORMALIZE_BENCHMARK_JSONL {

    conda 'python=3.12 typer=0.15 pyyaml=6 pyarrow=18'
    container 'community.wave.seqera.io/library/python_duckdb_jinja2_typer_pruned:2d95e1e826bbe38f'

    input:
    path data_dir
    path benchmark_aws_cur_report
    path machines_dir

    output:
    path "jsonl_bundle/", emit: jsonl
    path "versions.yml",  emit: versions

    script:
    def cost_flag = benchmark_aws_cur_report.name != 'NO_FILE' ? "--costs ${benchmark_aws_cur_report}" : ""
    def machines_flag = machines_dir.name != 'NO_FILE' ? "--machines-dir ${machines_dir}" : ""
    """
    benchmark_report.py normalize-jsonl \\
        --data-dir ${data_dir} \\
        ${cost_flag} \\
        ${machines_flag} \\
        --output-dir jsonl_bundle

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
    END_VERSIONS
    """
}
