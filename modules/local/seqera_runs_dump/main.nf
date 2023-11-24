@Grab('com.github.groovy-wslite:groovy-wslite:1.1.2')
import wslite.rest.RESTClient

Long getWorkspaceId(orgName, workspaceName, client, authHeader) {
    def orgResponse = client.get(path: '/orgs', headers: authHeader)
    if (orgResponse.statusCode == 200) {
        def orgMap = orgResponse.json?.organizations.collectEntries { org -> [org.name, org.orgId]}
        def orgId = orgMap.get(orgName)
        if(!orgId) log.warn "Could not find organization '${orgName}'" 

        // GET the workspaces in this org
        def workspaceReponse = client.get(path: "/orgs/${orgId}/workspaces", headers: authHeader)
        if (workspaceReponse.statusCode == 200) {
            def workspaceMap = workspaceReponse.json?.workspaces.collectEntries { ws -> [ws.name, ws.id]}
            return workspaceMap?.get(workspaceName)
        }
    }
    return null
}

Map getRunMetadata(meta, log) {
    def runId = meta.id
    (orgName, workspaceName) = meta.workspace.split("/")

    def client = new RESTClient("https://api.tower.nf")
    token = System.getenv("TOWER_ACCESS_TOKEN")
    authHeader = ["Authorization": "Bearer ${token}"]

    try {
        def workspaceId = getWorkspaceId(orgName, workspaceName, client, authHeader)
        if (workspaceId) {
            def workflowResponse = client.get(path: "/workflow/${runId}", query: ["workspaceId":workspaceId], headers: authHeader)
            if (workflowResponse.statusCode == 200) {
                return workflowResponse?.json?.workflow?.subMap("runName", "workDir")
            }
        }
    } catch(Exception ex) {
        log.warn "Could not get workflow details for workflow ${runId} in workspace ${meta.workspace}"
    }

    return [:]
}

process SEQERA_RUNS_DUMP {
    tag "$meta.id"
    conda 'tower-cli=0.9.0'

    input:
    val meta

    output:
    tuple val(newMeta), path("${prefix}")    , emit: run_dump
    tuple val(newMeta), path("workflow.json"), emit: workflow_json
    path "versions.yml"                   , emit: versions

    script:
    def args = task.ext.args ?: ''
    def args2 = task.ext.args2 ?: ''
    prefix = task.ext.prefix ?: "${meta.id}"
    newMeta = meta + getRunMetadata(meta, log)
    """
    tw \\
        $args \\
        --url=${params.api_url} \\
        --access-token=\$TOWER_ACCESS_TOKEN \\
        runs \\
        dump \\
        -id=${meta.id} \\
        --workspace=${meta.workspace} \\
        --output="${prefix}.tar.gz" \\
        $args2

    mkdir ${prefix}
    tar \\
        -xvf \\
        ${prefix}.tar.gz \\
        -C ${prefix}

    cp ${prefix}/workflow.json .

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        seqera-cli: \$(echo \$(tw --version 2>&1) | sed 's/^.*Tower CLI version //; s/ *\$//')
    END_VERSIONS
    """
}
