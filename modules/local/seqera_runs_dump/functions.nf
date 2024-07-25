@Grab('com.github.groovy-wslite:groovy-wslite:1.1.2;transitive=false')
import wslite.rest.RESTClient
import groovy.json.JsonSlurper
import nextflow.exception.ProcessException

// Set system properties for custom Java trustStore
def setTrustStore(trustStorePath, trustStorePassword) {
    System.setProperty("javax.net.ssl.trustStore", trustStorePath)
    if (trustStorePassword) {
        System.setProperty("javax.net.ssl.trustStorePassword", trustStorePassword)
    }
}

Long getWorkspaceId(orgName, workspaceName, client, authHeader) {
    def orgResponse = client.get(path: '/orgs', headers: authHeader)
    if (orgResponse.statusCode == 200) {
        def orgMap = orgResponse.json?.organizations.collectEntries { org -> [org.name, org.orgId] }
        def orgId = orgMap.get(orgName)
        if(!orgId) log.warn "Could not find organization '${orgName}'"

        // GET the workspaces in this org
        def workspaceReponse = client.get(path: "/orgs/${orgId}/workspaces", headers: authHeader)
        if (workspaceReponse.statusCode == 200) {
            def workspaceMap = workspaceReponse.json?.workspaces.collectEntries { ws -> [ws.name, ws.id]}
            return workspaceMap?.get(workspaceName)
        } else {
            log.error "Failed to fetch workspaces for orgId: ${orgId}, statusCode: ${workspaceResponse.statusCode}"
        }
    }
    return null
}

Map getRunMetadata(meta, log, api_endpoint, trustStorePath, trustStorePassword) {
    def runId = meta.id
    def (orgName, workspaceName) = meta.workspace.tokenize("/")

    if (trustStorePath) {
        log.info "Setting custom truststore: ${trustStorePath}"
        setTrustStore(trustStorePath, trustStorePassword)
    }

    def client = new RESTClient(api_endpoint)
    def token = System.getenv("TOWER_ACCESS_TOKEN")
    def authHeader = ["Authorization": "Bearer ${token}"]

    try {
        def workspaceId = getWorkspaceId(orgName, workspaceName, client, authHeader)
        if (workspaceId) {
            def workflowResponse = client.get(path: "/workflow/${runId}", query: ["workspaceId":workspaceId], headers: authHeader)
            if (workflowResponse.statusCode == 200) {
                metaMap = workflowResponse?.json?.workflow?.subMap("runName", "workDir", "projectName")
                config = new ConfigSlurper().parse( workflowResponse?.json?.workflow?.configText )
                metaMap.fusion =  config.fusion.enabled

                return metaMap ?: [:]
            }
        }
    } catch (wslite.rest.RESTClientException ex) {
        log.warn """
        Could not get workflow details for workflow ${runId} in workspace ${meta.workspace}:
            ↳ Status code ${ex.response?.statusCode} returned from request to ${ex.request?.url} (authentication headers excluded)
        """.stripIndent()
        log.error(ex)
        throw new ProcessException("Failed to get workflow details for workflow ${runId} in workspace ${meta.workspace}", ex)
    } catch (Exception ex) {
        log.warn """
        An error occurred while getting workflow details for workflow ${runId} in workspace ${meta.workspace}:
            ↳ ${ex.message}
        """.stripIndent()
        log.error(ex)
        throw new ProcessException("Failed to get workflow details for workflow ${runId} in workspace ${meta.workspace}", ex)

    }
    return [:]
}
