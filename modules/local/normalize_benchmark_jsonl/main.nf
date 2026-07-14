process NORMALIZE_BENCHMARK_JSONL {

    conda 'python=3.12 typer=0.15 pyyaml=6 duckdb=1.1'
    container 'community.wave.seqera.io/library/python_duckdb_jinja2_typer_pruned:2d95e1e826bbe38f'

    input:
    path data_dir
    path benchmark_aws_cur_report
    path benchmark_aws_cur_label_map
    path machines_dir

    output:
    path "jsonl_bundle/", emit: jsonl
    path "versions.yml",  emit: versions

    script:
    def cost_flag = benchmark_aws_cur_report ? "--costs ${benchmark_aws_cur_report}" : ""
    def label_map_flag = benchmark_aws_cur_label_map ? "--cost-label-map ${benchmark_aws_cur_label_map}" : ""
    def machines_flag = machines_dir ? "--machines-dir ${machines_dir}" : ""
    """
    normalize_benchmark_jsonl.py \\
        --data-dir ${data_dir} \\
        ${cost_flag} \\
        ${label_map_flag} \\
        ${machines_flag} \\
        --output-dir jsonl_bundle

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
    END_VERSIONS
    """
}
