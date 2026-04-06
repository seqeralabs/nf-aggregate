# lib/ — Groovy Libraries

Auto-loaded by Nextflow at pipeline startup. Available in workflow/process scripts without explicit import.

## SeqeraApi.groovy

nf-boost `request()` wrappers for Seqera Platform API. Used in the v2 benchmark path — called directly in `map{}` operators, no container needed.

### Methods

| Method                                                | Purpose                                                                          |
| ----------------------------------------------------- | -------------------------------------------------------------------------------- |
| `apiGet(url, headers)`                                | Single GET request, returns parsed JSON map                                      |
| `apiGetAllTasks(baseUrl, headers)`                    | Paginated GET for `/tasks` endpoint (100/page)                                   |
| `resolveWorkspaceId(workspace, apiEndpoint, headers)` | "org/workspace" string → numeric workspace ID                                    |
| `fetchRunData(meta, apiEndpoint)`                     | Orchestrator: calls 4 endpoints per run → `{workflow, metrics, tasks, progress}` |

### API Endpoints Called (per run)

1. `GET /workflow/{id}?workspaceId={wsId}` — run metadata
2. `GET /workflow/{id}/metrics?workspaceId={wsId}` — resource metrics
3. `GET /workflow/{id}/tasks?workspaceId={wsId}` — all tasks (paginated)
4. `GET /workflow/{id}/progress?workspaceId={wsId}` — progress summary

### Auth

Uses `TOWER_ACCESS_TOKEN` env var via `System.getenv()`. Forwarded to Nextflow processes via `env {}` block in `nextflow.config`.

### Workspace Resolution

Calls `/orgs` → finds org by name → calls `/orgs/{orgId}/workspaces` → finds workspace by name → returns numeric ID.

### Gotchas

- Uses `nextflow.boost.BoostFunctions` — requires `nf-boost` plugin
- Runs in the Nextflow head JVM, not in a container process
- Network errors throw `RuntimeException` which will fail the pipeline
