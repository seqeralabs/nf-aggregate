
Long getWorkspaceId(orgName, workspaceName, api_endpoint, authHeader) {
    Map response
    try {
        def responseString = new URL("${api_endpoint}/orgs").getText(requestProperties: authHeader)
        response = new groovy.json.JsonSlurper().parseText(responseString)
    } catch (Exception e) {
        log.warn "Could not fetch organization ${orgName} from API endpoint ${api_endpoint}"
        throw new nextflow.exception.ProcessException("Failed to get organization details for ${orgName} in workspace ${workspaceName}", e)
    }

    def orgId = response
        ?.organizations
        ?.collectEntries { org -> [org.name, org.orgId] }
        ?.get(orgName)
    if(!orgId) log.warn "Could not find organization '${orgName}'"

    try {
        def workspaceReponse = new URL("${api_endpoint}/orgs/${orgId}/workspaces").getText(requestProperties: authHeader)
        def workspaceMap = new groovy.json.JsonSlurper()
            .parseText(workspaceReponse)
            ?.workspaces
            ?.collectEntries { ws -> [ws.name, ws.id]}
        return workspaceMap?.get(workspaceName)
    } catch (Exception e) {
        log.error "Failed to fetch workspaces for orgId: ${orgId}"
        return null
    }
}

Map getRunMetadata(meta, log, api_endpoint, trustStorePath, trustStorePassword) {
    def runId = meta.id
    def (orgName, workspaceName) = meta.workspace.tokenize("/")

    def token = System.getenv("TOWER_ACCESS_TOKEN")
    def authHeader = ["Authorization": "Bearer ${token}"]
    def workspaceId = getWorkspaceId(orgName, workspaceName, api_endpoint, authHeader)
    def endpointUrl = "${api_endpoint}/workflow/${runId}?workspaceId=${workspaceId}"
    if(!workspaceId) {
        log.error "Failed to get workspaceId for ${orgName}/${workspaceName}"
        return [:]
    }

    try {
        def workflowResponseString = new URL(endpointUrl).getText(requestProperties: authHeader)
        def workflowResponse = new groovy.json.JsonSlurper().parseText(workflowResponseString)
        def metaMap = workflowResponse
            ?.workflow
            ?.subMap("runName", "workDir", "projectName")
        def configText = new groovy.json.JsonBuilder(workflowResponse?.workflow?.configText)
        def pattern = /fusion\s*\{\\n\s*enabled\s*=\s*true/
        def matcher = configText.toPrettyString() =~ pattern
        metaMap.fusion = matcher.find()

        return metaMap ?: [:]
    } catch (Exception ex) {
        log.warn """
        Could not get workflow details for workflow ${runId} in workspace ${meta.workspace}:
            ↳ From request to ${endpointUrl}
        """.stripIndent()
        log.error "Exception: ${ex.message}", ex
        throw new nextflow.exception.ProcessException("Failed to get workflow details for workflow ${runId} in workspace ${meta.workspace}", ex)
    }
    return [:]
}
