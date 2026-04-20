// Seqera Platform API client using plain java.net HTTP

class SeqeraApi {

    static Map apiGet(String url, Map headers) {
        def conn = new URL(url).openConnection()
        try {
            conn.setRequestMethod('GET')
            headers.each { k, v -> conn.setRequestProperty(k, v) }
            def code = conn.getResponseCode()
            if (code != 200) {
                throw new RuntimeException("API request failed: ${url} → HTTP ${code}")
            }
            def stream = conn.getInputStream()
            try {
                def text = stream.getText()
                return new groovy.json.JsonSlurper().parseText(text)
            } finally {
                stream.close()
            }
        } finally {
            conn.disconnect()
        }
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
     *
     * Per-row overrides (from the input samplesheet):
     *   meta.platform  – Seqera Platform API URL; falls back to the global apiEndpoint
     *   meta.token_env – env-var name holding the bearer token; falls back to TOWER_ACCESS_TOKEN
     */
    static Map fetchRunData(Map meta, String apiEndpoint) {
        def effectiveEndpoint = meta.platform ?: apiEndpoint
        def tokenEnvVar = meta.token_env ?: "TOWER_ACCESS_TOKEN"
        def token = System.getenv(tokenEnvVar)
        if (!token) {
            throw new RuntimeException(
                "Environment variable '${tokenEnvVar}' is not set (required for run ${meta.id})"
            )
        }
        def headers = ["Authorization": "Bearer ${token}"]
        def wsId = resolveWorkspaceId(meta.workspace, effectiveEndpoint, headers)
        def base = "${effectiveEndpoint}/workflow/${meta.id}?workspaceId=${wsId}"

        def workflow = apiGet(base, headers)
        def metrics = apiGet("${effectiveEndpoint}/workflow/${meta.id}/metrics?workspaceId=${wsId}", headers)
        def tasks = apiGetAllTasks("${effectiveEndpoint}/workflow/${meta.id}/tasks?workspaceId=${wsId}", headers)
        def progress = apiGet("${effectiveEndpoint}/workflow/${meta.id}/progress?workspaceId=${wsId}", headers)

        return [
            workflow: workflow?.workflow,
            metrics : metrics?.metrics ?: [],
            tasks   : tasks,
            progress: progress?.progress,
        ]
    }
}
