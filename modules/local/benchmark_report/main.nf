process BENCHMARK_REPORT {
    debug true

    container 'cr.seqera.io/scidev/benchmark-reports:sha-7fe0d8e'

    input:
    path run_dumps
    val  group
    path benchmark_report_cost_allocation_file
    val  benchmark_report_name

    output:
    path "versions.yml"          , emit: versions

    script:
    def aws_cost_param = benchmark_report_cost_allocation_file ? "--profile cost -P 'aws_cost:/${benchmark_report_cost_allocation_file}'" : ""

    // Create CSV content with all entries - just use filenames for now
    def csv_content = ["group,file_path"]
    run_dumps.eachWithIndex { run_dump, i ->
        csv_content << "${group[i]},${run_dump.toString()}"
    }
    def csv_string = csv_content.join('\n')
    """
    export HOME=\$PWD
    export QUARTO_CACHE=/tmp/quarto/cache
    export XDG_CACHE_HOME=/tmp/quarto
    mkdir -p /tmp/quarto/cache
    chmod -R 777 /tmp/quarto

    echo '${csv_string}' > benchmark_samplesheet.csv

    # Set up R environment from renv
    export R_LIBS_USER=/project/renv/library/linux-ubuntu-noble/R-4.4/x86_64-pc-linux-gnu

    # Debug: Check pandoc installation
    ls -la /opt/quarto/bin/tools || echo "tools dir not found"
    ls -la /opt/quarto/bin/tools/pandoc || echo "pandoc not found in tools"

    # Add pandoc to PATH
    export PATH=/opt/quarto/bin/tools/pandoc:\$PATH

    /usr/local/lib/R/bin/Rscript --version
    pandoc --version || echo "pandoc still not working"
    quarto check --log-level debug

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        R: \$(quarto -v)
    END_VERSIONS
    """
}
