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
