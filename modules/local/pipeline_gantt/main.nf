process PIPELINE_GANTT {
    tag "$run_id"
    conda 'conda-forge::click=8.0.1 conda-forge::pandas=1.1.5 conda-forge::plotly_express=0.4.1 conda-package::procps-ng conda-forge::typing'
    container "${ workflow.containerEngine == 'singularity' && !task.ext.singularity_pull_docker_container ?
        'https://depot.galaxyproject.org/singularity/tower-cli:0.9.0--h9ee0642_0' :
        'docker.io/drpatelh/pythongantt:dev' }"

    input:
    tuple val(run_id), path(run_dump)

    output:
    tuple val(run_id), path("*.html"), emit: html
    path "versions.yml"              , emit: versions

    script:
    def prefix = task.ext.prefix ?: "${run_id}"
    """
    pipeline-gantt.py \\
        --title "GANTT Plot for run: $run_id" \\
        --input-dir $run_dump \\
        --output-file ./${prefix}_gantt.html

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        python: \$(python --version | sed 's/Python //g')
        pandas: \$(python -c "import pandas; print(pandas.__version__)")
        plotly_express: \$(python -c "import plotly_express; print(plotly_express.__version__)")
        click: \$(python -c "import click; print(click.__version__)")
    END_VERSIONS
    """
}
