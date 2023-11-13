process PLOT_RUN_GANTT {
    tag "$run_id"
    conda 'click=8.0.1 pandas=1.1.5 plotly_express=0.4.1 typing=3.10.0.0'

    input:
    tuple val(run_id), path(run_dump)

    output:
    tuple val(run_id), path("*.html"), emit: html
    path "versions.yml"              , emit: versions

    script:
    def prefix = task.ext.prefix ?: "${run_id}"
    """
    plot_run_gantt.py \\
        --title "GANTT plot for run: $run_id" \\
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
