# lib/ — Groovy Libraries

Auto-loaded by Nextflow at pipeline startup. Available in workflow/process scripts without explicit import.

## SeqeraApi.groovy

Plain `java.net.URL.openConnection()` HTTP client for Seqera Platform API. Used in the v2 benchmark path — called directly in `map{}` operators, no container needed.

### Methods

| Method                                                | Purpose                                                                          |
| ----------------------------------------------------- | -------------------------------------------------------------------------------- |
| `apiGet(url, headers)`                                | Single GET request, returns parsed JSON map                                      |
| `apiGetAllTasks(baseUrl, headers)`                    | Paginated GET for `/tasks` endpoint (100/page)                                   |
| `resolveWorkspaceId(workspace, apiEndpoint, headers)` | "org/workspace" string → numeric workspace ID                                    |
| `fetchRunData(meta, apiEndpoint)`                     | Orchestrator: preflights `/service-info` + `/user-info`, then calls 4 run endpoints → `{workflow, metrics, tasks, progress}` |

### API Endpoints Called

Preflight once per endpoint/token pair:

1. `GET /service-info` — validates the API endpoint is reachable
2. `GET /user-info` — validates the bearer token before workspace resolution

Per run:
1. `GET /workflow/{id}?workspaceId={wsId}` — run metadata
2. `GET /workflow/{id}/metrics?workspaceId={wsId}` — resource metrics
3. `GET /workflow/{id}/tasks?workspaceId={wsId}` — all tasks (paginated)
4. `GET /workflow/{id}/progress?workspaceId={wsId}` — progress summary

### Auth

Uses `TOWER_ACCESS_TOKEN` env var via `System.getenv()`. Forwarded to Nextflow processes via `env {}` block in `nextflow.config`.

### Workspace Resolution

Calls `/orgs` → finds org by name → calls `/orgs/{orgId}/workspaces` → finds workspace by name → returns numeric ID.

### Gotchas

- Uses plain `java.net.URL.openConnection()` for HTTP requests — no external plugin dependency
- Runs in the Nextflow head JVM, not in a container process
- Network errors throw `RuntimeException` which will fail the pipeline
- Bad endpoints fail during `/service-info` preflight; bad or expired tokens fail during `/user-info` preflight
