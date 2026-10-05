/*
 * nf-test invokes targets as fn(*input). Nextflow cannot compile that spread for
 * Groovy lib static methods, so tests call these single-argument Nextflow functions.
 */

def apiGetAllTasksHarness(Map cfg) {
    return SeqeraApi.apiGetAllTasks(cfg.url as String, cfg.headers as Map)
}

def resolveWorkspaceIdHarness(Map cfg) {
    return SeqeraApi.resolveWorkspaceId(cfg.workspace as String, cfg.endpoint as String, cfg.headers as Map)
}
