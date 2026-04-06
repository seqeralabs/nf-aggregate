# seqera_runs_dump

Fetch run data via Seqera CLI (`tw runs dump`). Used by the legacy v1 path, MultiQC, and Gantt chart.

## Process

**Conda:** `tower-cli=0.9.2`
**Container:** `seqeralabs/nf-aggregate:tower-cli-0.9.2--hdfd78af_1`

### Inputs

| Input                      | Type | Description                                 |
| -------------------------- | ---- | ------------------------------------------- |
| `meta`                     | val  | Run metadata: `{id, workspace, group, ...}` |
| `api_endpoint`             | val  | Seqera Platform API URL                     |
| `java_truststore_path`     | val  | Optional path for private certs             |
| `java_truststore_password` | val  | Optional truststore password                |

### Outputs

- `{id}/` directory — extracted run dump (tar.gz → directory)
- `versions.yml` — seqera-cli version

### Metadata Enrichment

Before the process runs, `getRunMetadata()` (in `functions.nf`) pre-fetches workflow details via raw Groovy `URL.getText()` API calls to enrich `meta` with:

- `runName`, `workDir`, `projectName`
- `fusion` — detected via regex on `configText`: `fusion\s*\{\\n\s*enabled\s*=\s*true`

This enriched meta is emitted as `metaOut` so downstream processes (PLOT_RUN_GANTT) can filter on `meta.fusion`.

## functions.nf

| Function           | Purpose                                                                                    |
| ------------------ | ------------------------------------------------------------------------------------------ |
| `getWorkspaceId()` | org/workspace string → numeric workspace ID (same logic as `SeqeraApi.resolveWorkspaceId`) |
| `getRunMetadata()` | Fetch workflow details, detect fusion, return enriched meta map                            |

### Duplication Note

`getWorkspaceId()` duplicates `SeqeraApi.resolveWorkspaceId()` in `lib/SeqeraApi.groovy`. The v2 path uses SeqeraApi; this module uses its own copy. Consolidation opportunity exists but low priority since v1 path is legacy.
