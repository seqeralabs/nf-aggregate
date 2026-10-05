/*
 * SeqeraApi helper checks without nf-test's function harness (Nextflow cannot compile fn(*input)).
 */

def assertEq(actual, expected, label) {
    if (actual != expected) {
        error("${label}: expected ${expected} but got ${actual}")
    }
}

workflow {
    // apiGetAllTasks pagination
    SeqeraApi.metaClass.'static'.apiGet = { String url, Map headers ->
        if (url.contains('offset=0')) {
            return [tasks: (1..100).collect { [taskId: it] }]
        }
        if (url.contains('offset=100')) {
            return [tasks: [[taskId: 101], [taskId: 102]]]
        }
        error("Unexpected URL: ${url}")
    }
    def tasks = SeqeraApi.apiGetAllTasks(
        'https://example.com/tasks?workspaceId=55',
        [Authorization: 'Bearer test-token']
    )
    assertEq(tasks*.taskId, (1..102).toList(), 'apiGetAllTasks pagination')

    // resolveWorkspaceId success
    SeqeraApi.metaClass.'static'.apiGet = { String url, Map headers ->
        if (url == 'https://api.example.com/orgs') {
            return [organizations: [[name: 'acme', orgId: 7], [name: 'other', orgId: 8]]]
        }
        if (url == 'https://api.example.com/orgs/7/workspaces') {
            return [workspaces: [[name: 'workspace-a', id: 11], [name: 'workspace-b', id: 42]]]
        }
        error("Unexpected URL: ${url}")
    }
    def wsId = SeqeraApi.resolveWorkspaceId(
        'acme/workspace-b',
        'https://api.example.com',
        [Authorization: 'Bearer test-token']
    )
    assertEq(wsId, 42L, 'resolveWorkspaceId')

    // resolveWorkspaceId missing workspace
    SeqeraApi.metaClass.'static'.apiGet = { String url, Map headers ->
        if (url == 'https://api.example.com/orgs') {
            return [organizations: [[name: 'acme', orgId: 7]]]
        }
        if (url == 'https://api.example.com/orgs/7/workspaces') {
            return [workspaces: [[name: 'workspace-a', id: 11]]]
        }
        error("Unexpected URL: ${url}")
    }
    try {
        SeqeraApi.resolveWorkspaceId(
            'acme/workspace-b',
            'https://api.example.com',
            [Authorization: 'Bearer test-token']
        )
        error('resolveWorkspaceId should fail for missing workspace')
    }
    catch (RuntimeException e) {
        if (!e.message.contains("Workspace 'workspace-b' not found in org 'acme'")) {
            error("Unexpected error: ${e.message}")
        }
    }
}
