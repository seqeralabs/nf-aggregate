def mod_container = switch([workflow.containerEngine, workflow.profile]) {
    case {it[0] == 'singularity' &&  it[1].contains('arm')} -> 'oras://community.wave.seqera.io/library/click_pandas_plotly_express_typing:3fe674b9fa7b15b8'
    case {it[0] == 'singularity'} -> 'oras://community.wave.seqera.io/library/click_pandas_plotly_express_typing:a4af841350996386'
    case {it[1].contains('arm')} -> 'community.wave.seqera.io/library/click_pandas_plotly_express_typing:2e5e17c7ed2d1115'
    default -> 'community.wave.seqera.io/library/click_pandas_plotly_express_typing:21adb9e2d1b605a5'
}

process PLOT_RUN_GANTT {
    tag "$meta.id"

    conda 'click=8.0.1 pandas=1.1.5 plotly_express=0.4.1 typing=3.10.0.0'
    container mod_container

    input:
    tuple val(meta), path(run_dump)

    output:
    tuple val(meta), path("*.html"), emit: html
    path "versions.yml"            , emit: versions

    script:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    plot_run_gantt.py \\
        --title "GANTT plot for run: ${meta.id}" \\
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
