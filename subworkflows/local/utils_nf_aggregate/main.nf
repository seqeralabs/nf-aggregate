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

include { UTILS_NEXTFLOW_PIPELINE } from '../../nf-core/utils_nextflow_pipeline'
include { getWorkflowVersion      } from '../../nf-core/utils_nextflow_pipeline'
include { UTILS_NFSCHEMA_PLUGIN   } from '../../nf-core/utils_nfschema_plugin'
include { samplesheetToList       } from 'plugin/nf-schema'

/*
========================================================================================
    SUBWORKFLOW TO INITIALISE PIPELINE
========================================================================================
*/

workflow PIPELINE_INITIALISATION {
    take:
    version           // boolean: Display version and exit
    validate_params   // boolean: Boolean whether to validate parameters against the schema at runtime
    outdir            //  string: The output directory where the results will be saved
    input             //  string: Path to input samplesheet

    main:

    //
    // Print version and exit if required and dump pipeline parameters to JSON file
    //
    UTILS_NEXTFLOW_PIPELINE (
        version,
        true,
        outdir,
        workflow.profile.tokenize(',').intersect(['conda', 'mamba']).size() >= 1
    )

    UTILS_NFSCHEMA_PLUGIN (
        workflow,
        validate_params,
        null
    )

    // Read in ids from --input file
    Channel
        .fromList(samplesheetToList(input, "assets/schema_input.json"))
        .flatten()
        .set { ch_ids }

    emit:
    ids = ch_ids
}

/*
========================================================================================
    FUNCTIONS
========================================================================================
*/

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
    return yaml.dumpAsMap(versions).trim()
}

//
// Get workflow versions from pipeline
//
def getWorkflowVersions() {
    return """
    'Workflow':
        "Nextflow": "$workflow.nextflow.version"
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
