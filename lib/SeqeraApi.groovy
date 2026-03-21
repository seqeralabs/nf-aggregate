// Seqera Platform API client using nf-boost request()

import nextflow.boost.BoostFunctions

class SeqeraApi {

    static Map apiGet(String url, Map headers) {
        def conn = BoostFunctions.request(url, method: 'GET', headers: headers)
        def code = conn.getResponseCode()
        if (code != 200) {
            throw new RuntimeException("API request failed: ${url} → HTTP ${code}")
        }
        def text = conn.getInputStream().getText()
        return new groovy.json.JsonSlurper().parseText(text)
    }

    /**
     * Paginate through /tasks endpoint. Returns flat list of all tasks.
     */
    static List apiGetAllTasks(String baseUrl, Map headers) {
        def tasks = []
        def offset = 0
        def pageSize = 100
        while (true) {
            def sep = baseUrl.contains('?') ? '&' : '?'
            def url = "${baseUrl}${sep}max=${pageSize}&offset=${offset}"
            def resp = apiGet(url, headers)
            def page = resp?.tasks ?: []
            tasks.addAll(page)
            if (page.size() < pageSize) break
            offset += pageSize
        }
        return tasks
    }

    /**
     * Resolve "org/workspace" string to numeric workspace ID.
     */
    static Long resolveWorkspaceId(String workspace, String apiEndpoint, Map headers) {
        def (orgName, workspaceName) = workspace.tokenize("/")

        def orgsResp = apiGet("${apiEndpoint}/orgs", headers)
        def orgId = orgsResp?.organizations?.find { it.name == orgName }?.orgId
        if (!orgId) {
            throw new RuntimeException("Organization '${orgName}' not found")
        }

        def wsResp = apiGet("${apiEndpoint}/orgs/${orgId}/workspaces", headers)
        def wsId = wsResp?.workspaces?.find { it.name == workspaceName }?.id
        if (!wsId) {
            throw new RuntimeException("Workspace '${workspaceName}' not found in org '${orgName}'")
        }
        return wsId
    }

    /**
     * Fetch all data for a single run. Returns map with workflow, metrics, tasks, progress.
     */
    static Map fetchRunData(Map meta, String apiEndpoint) {
        def token = System.getenv("TOWER_ACCESS_TOKEN")
        def headers = ["Authorization": "Bearer ${token}"]
        def wsId = resolveWorkspaceId(meta.workspace, apiEndpoint, headers)
        def base = "${apiEndpoint}/workflow/${meta.id}?workspaceId=${wsId}"

        def workflow = apiGet(base, headers)
        def metrics = apiGet("${apiEndpoint}/workflow/${meta.id}/metrics?workspaceId=${wsId}", headers)
        def tasks = apiGetAllTasks("${apiEndpoint}/workflow/${meta.id}/tasks?workspaceId=${wsId}", headers)
        def progress = apiGet("${apiEndpoint}/workflow/${meta.id}/progress?workspaceId=${wsId}", headers)

        return [
            workflow: workflow?.workflow,
            metrics : metrics?.metrics ?: [],
            tasks   : tasks,
            progress: progress?.progress,
        ]
    }
}
