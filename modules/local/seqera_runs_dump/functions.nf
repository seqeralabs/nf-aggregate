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
                metaMap = workflowResponse?.json?.workflow?.subMap("runName", "workDir", "projectName")
                return metaMap ?: [:]
            }
        }
    } catch(Exception ex) {
        log.warn "Could not get workflow details for workflow ${runId} in workspace ${meta.workspace}"
    }
    return [:]
}
