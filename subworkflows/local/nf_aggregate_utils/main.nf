//
// Subworkflow with functionality specific to the nf-aggregate pipeline
//

import groovy.json.JsonSlurper
import org.yaml.snakeyaml.Yaml
import java.nio.file.Paths

/*
========================================================================================
    IMPORT MODULES/SUBWORKFLOWS
========================================================================================
*/

include { NEXTFLOW_PIPELINE_UTILS; getWorkflowVersion } from '../../nf-core/nextflowpipelineutils/main'
include { NF_VALIDATION_PLUGIN_UTILS                  } from '../../nf-core/nfvalidation_plugin_utils/main.nf'

/*
========================================================================================
    SUBWORKFLOW TO INITIALISE PIPELINE
========================================================================================
*/

workflow PIPELINE_INITIALISATION {

    main:

    //
    // Print version and exit if required and dump pipeline parameters to JSON file
    //
    NEXTFLOW_PIPELINE_UTILS (
        params.version,
        true,
        params.outdir,
        workflow.profile.tokenize(',').intersect(['conda', 'mamba']).size() >= 1
    )

    //
    // Validate parameters and generate parameter summary to stdout
    //
    def pre_help_text = ''
    def post_help_text = ''
    def String workflow_command = "nextflow run ${workflow.manifest.name} -profile <docker/singularity/.../institute> --input ids.txt --outdir <OUTDIR>"
    NF_VALIDATION_PLUGIN_UTILS (
        params.help,
        workflow_command,
        pre_help_text,
        post_help_text,
        params.validate_params,
        "nextflow_schema.json"
    )

    // Read in ids from --input file
    Channel
        .from(file(params.input))
        .splitCsv(header:false, sep:'', strip:true)
        .map { it[0] }
        .unique()
        .set { ch_ids }

    emit:
    ids            = ch_ids
    summary_params = NF_VALIDATION_PLUGIN_UTILS.out.summary_params
}

/*
========================================================================================
    SUBWORKFLOW FOR PIPELINE COMPLETION
========================================================================================
*/

workflow PIPELINE_COMPLETION {

    take:
    versions // channel: software tools versions

    main:

    //
    // MODULE: Dump software versions for all tools used in the workflow
    //
    pipeline_version_info = Channel.of("""\"workflow\":
        nextflow: ${workflow.nextflow.version}
        ${workflow.manifest.name}: ${workflow.manifest.version}
    """.stripIndent())

    versions = versions.mix(pipeline_version_info)
    versions.collectFile(name: 'nf_aggregate_mqc_versions.yml', storeDir: "${params.outdir}/pipeline_info")
}

/*
========================================================================================
    FUNCTIONS
========================================================================================
*/

//
// Function that parses Seqera CLI 'workflow.json' output file to get workflow name
//
def getWorkflowName(json_file) {
    return new JsonSlurper().parseText(json_file.text).get('manifest')['name']
}

//
// Function that parses Seqera CLI 'workflow.json' output file to get work directory
//
def getWorkflowWorkDir(json_file) {
    return new JsonSlurper().parseText(json_file.text).get('workDir')
}

//
// Function that parses Seqera CLI 'workflow.json' output file to get output directory
//
def getWorkflowPublishDir(json_file, outdir) {
    def path = new JsonSlurper().parseText(json_file.text).get('params')[outdir]
    File file = new File(outdir)
    if (!file.isAbsolute()) {
        def workdir = getWorkflowWorkDir(json_file)
        if (workdir.startsWith('s3://')) {
            path = Paths.get(workdir, path)
        }  
    }
    return path
}

//
// Get software versions from pipeline
//
def getProcessVersions(yaml_file) {
    Yaml parser = new Yaml()
    versions = parser.load(yaml_file).collectEntries { k,v -> [ k.tokenize(':')[-1], v ] }
    Yaml yaml = new Yaml()
    return yaml.dumpAsMap(versions)
}

//
// Get workflow versions from pipeline
//
def getWorkflowVersions() {
    return """
    'Workflow':
      "Nextflow": "$workflow.nextflow.version",
      "$workflow.manifest.name": "$workflow.manifest.version"
    """.stripIndent().trim()
}

//
// Get workflow summary for MultiQC
//
def paramsSummaryMultiqc(summary) {
    def summary_section = ''
    for (group in summary.keySet()) {
        def group_params = summary.get(group)  // This gets the parameters of that particular group
        if (group_params) {
            summary_section += "    <p style=\"font-size:110%\"><b>$group</b></p>\n"
            summary_section += "    <dl class=\"dl-horizontal\">\n"
            for (param in group_params.keySet()) {
                summary_section += "        <dt>$param</dt><dd><samp>${group_params.get(param) ?: '<span style=\"color:#999999;\">N/A</a>'}</samp></dd>\n"
            }
            summary_section += "    </dl>\n"
        }
    }

    String yaml_file_text  = "id: '${workflow.manifest.name.replace('/','-')}-summary'\n"
    yaml_file_text        += "description: ' - this information is collected when the pipeline is started.'\n"
    yaml_file_text        += "section_name: '${workflow.manifest.name} Workflow Summary'\n"
    yaml_file_text        += "section_href: 'https://github.com/${workflow.manifest.name}'\n"
    yaml_file_text        += "plot_type: 'html'\n"
    yaml_file_text        += "data: |\n"
    yaml_file_text        += "${summary_section}"

    return yaml_file_text
}