# Retroactive Nextflow Data-Lineage Reconstruction: Feasibility Analysis

> **Date:** 2025-07-14
> **Scope:** Determine whether Nextflow-compatible lineage metadata can be reconstructed from existing Seqera Platform API run records for historical pipeline runs that predate native Nextflow lineage support (introduced in Nextflow 25.04).

---

## 1. Executive Summary

**Verdict: Partially feasible — useful but fundamentally incomplete.**

The Seqera Platform API provides sufficient data to reconstruct meaningful `WorkflowRun` and partial `TaskRun` lineage records. However, **`FileOutput` records — the core of the lineage provenance graph — cannot be reconstructed**, because the API does not store per-task input/output file paths, file checksums, or inter-task data-flow relationships. The result would be a "skeleton" lineage store: workflow and task metadata without the file-level provenance chain that makes Nextflow lineage truly useful.

---

## 2. Background

### 2.1 Nextflow Lineage Data Model (v1beta1)

The Nextflow lineage system (source: [`nextflow-io/nextflow` modules/nf-lineage](https://github.com/nextflow-io/nextflow/tree/master/modules/nf-lineage/src/main/nextflow/lineage/model/v1beta1)) defines these record types:

| Record Type | Purpose | Key Fields |
|---|---|---|
| **WorkflowRun** | Top-level run metadata | `workflow` (scriptFiles, repository, commitId), `sessionId`, `name`, `params`, `config` |
| **TaskRun** | Individual task execution | `sessionId`, `name`, `codeChecksum`, `script`, `input` (with LID refs), `container`, `conda`, `spack`, `architecture`, `globalVars`, `binEntries`, `workflowRun` |
| **FileOutput** | Output file with provenance | `path`, `checksum`, `source` (LID), `workflowRun` (LID), `taskRun` (LID), `size`, `createdAt`, `modifiedAt`, `labels` |
| **WorkflowOutput** | Published workflow outputs | `createdAt`, `workflowRun`, `output` (List\<Parameter\>) |
| **TaskOutput** | Task output declarations | `taskRun`, `workflowRun`, `createdAt`, `output` (List\<Parameter\>), `labels` |

Lineage IDs (LIDs) use the format `lid://<hash>` where the hash is derived from Nextflow's internal `CacheHelper` — a Murmur3-based hash of task inputs, script, container, etc. File checksums use `{value, algorithm: "nextflow", mode: "standard"}`.

### 2.2 Seqera Platform API Data Available

The `nf-agg` codebase (`lib/SeqeraApi.groovy`) fetches data from four API endpoints per run:

| Endpoint | Data Returned |
|---|---|
| `GET /workflow/{id}` | Workflow metadata: `id`, `runName`, `sessionId`, `repository`, `commitId`, `revision`, `projectName`, `commandLine`, `params` (object), `configText`, `configFiles`, `container`, `containerEngine`, `scriptFile`, `scriptName`, `workDir`, `launchDir`, `projectDir`, `homeDir`, `start`, `complete`, `duration`, `status`, `userName`, `manifest`, `nextflow` version, `fusion`, `wave`, `stats`, `resume`, `success` |
| `GET /workflow/{id}/tasks` | Per-task data: `hash`, `name`, `process`, `tag`, `submit`, `start`, `complete`, `module`, **`container`**, `attempt`, **`script`**, `scratch`, **`workdir`**, `queue`, `cpus`, `memory`, `disk`, `time`, `env`, `executor`, `machineType`, `cloudZone`, `cost`, `exitStatus`, `duration`, `realtime`, `nativeId`, resource metrics |
| `GET /workflow/{id}/metrics` | Per-process aggregate stats: `cpu`, `mem`, `vmem`, `time`, `reads`, `writes`, `cpuUsage`, `memUsage`, `timeUsage` (each with min/max/mean/q1/q2/q3) |
| `GET /workflow/{id}/progress` | Aggregate progress: `cpuEfficiency`, `memoryEfficiency`, `cpuTime`, `readBytes`, `writeBytes` |

---

## 3. Field-by-Field Feasibility Mapping

### 3.1 WorkflowRun Record

| Lineage Field | API Source | Feasibility | Notes |
|---|---|---|---|
| `version` | — | ✅ **Populatable** | Hardcode `"lineage/v1beta1"` |
| `type` | — | ✅ **Populatable** | Hardcode `"WorkflowRun"` |
| `workflow.repository` | `workflow.repository` | ✅ **Exact match** | Directly available |
| `workflow.commitId` | `workflow.commitId` | ✅ **Exact match** | Directly available |
| `workflow.scriptFiles` | `workflow.scriptFile`, `workflow.scriptName` | ⚠️ **Partial** | API returns only the main script file path and name, not the full list of all script files with checksums. The `configFiles` array provides config file paths but without content checksums. Cannot reconstruct `List<DataPath>` with checksums. |
| `sessionId` | `workflow.sessionId` | ✅ **Exact match** | Directly available |
| `name` | `workflow.runName` | ✅ **Exact match** | Directly available |
| `params` | `workflow.params` | ⚠️ **Partial** | API returns params as a flat JSON object. Lineage expects `List<Parameter>` with `{type, name, value}` tuples. The param values are available but the `type` field (Nextflow type system: `val`, `path`, etc.) is **not stored by the API**. Can approximate by inferring types from values, but not exact. |
| `config` | `workflow.configText` | ⚠️ **Partial** | API returns the raw config text as a string. Lineage expects the resolved config as a `Map`. Would need to parse the Nextflow config syntax into a structured map, which is non-trivial (Nextflow config has its own DSL). Not reliably parseable without the Nextflow config parser itself. |

**WorkflowRun verdict:** ~70% reconstructable. Core identity fields (repository, commitId, sessionId, name) are fully available. Script file list and resolved config are partially available but structurally different from what lineage expects.

### 3.2 TaskRun Record

| Lineage Field | API Source | Feasibility | Notes |
|---|---|---|---|
| `version` | — | ✅ **Populatable** | Hardcode `"lineage/v1beta1"` |
| `type` | — | ✅ **Populatable** | Hardcode `"TaskRun"` |
| `sessionId` | `workflow.sessionId` | ✅ **Exact match** | Same session for all tasks in a run |
| `name` | `task.name` | ✅ **Exact match** | Directly available |
| `codeChecksum` | — | ❌ **Not available** | The API does not store the code checksum. While the `task.script` is available, recomputing the checksum requires Nextflow's `CacheHelper.hasher()` (Murmur3-based). The algorithm is internal to Nextflow and would need to be replicated exactly. Even then, the native lineage `codeChecksum` hashes the *process source code* (before variable substitution), not the resolved script — the API only has the resolved script. |
| `script` | `task.script` | ✅ **Exact match** | The resolved task script is stored per-task in the API. This is the same resolved script that lineage stores. |
| `input` | — | ❌ **Not available** | **Critical gap.** The API does not store task input channel values, input file paths, or input LID references. This is the primary data that enables lineage traversal (FileOutput → TaskRun → upstream FileOutputs). Without this, the provenance graph cannot be constructed. |
| `container` | `task.container` | ✅ **Exact match** | Per-task container image is stored in the API |
| `conda` | — | ❌ **Not available** | Conda environment paths are not stored in the API |
| `spack` | — | ❌ **Not available** | Spack environment info is not stored in the API |
| `architecture` | — | ❌ **Not available** | Not stored in the API |
| `globalVars` | — | ❌ **Not available** | Global variable definitions are not stored |
| `binEntries` | — | ❌ **Not available** | Binary/script entries from `bin/` directory are not stored |
| `workflowRun` | Constructible | ⚠️ **Synthetic** | Can construct a `lid://` reference, but the LID hash must be synthesized (see LID section below) |

**TaskRun verdict:** ~30% reconstructable. The critical `input` field that enables provenance graph traversal is completely absent. `script` and `container` are available but `codeChecksum`, `conda`, `spack`, `globalVars`, and `binEntries` are not.

### 3.3 FileOutput Record

| Lineage Field | API Source | Feasibility | Notes |
|---|---|---|---|
| `path` | — | ❌ **Not available** | The API does not store output file paths per task. The `task.workdir` gives the work directory, but not which files were produced as outputs. |
| `checksum` | — | ❌ **Not available** | File content checksums (Nextflow Murmur3 hashes) are not stored. Files would need to be re-read from storage, which may no longer exist for old runs. |
| `source` | — | ❌ **Not available** | Requires knowing the upstream TaskRun LID or FileOutput LID that produced this file. This data-flow relationship is not captured by the API. |
| `workflowRun` | Constructible | ⚠️ **Synthetic** | Could reference a synthetic workflow LID |
| `taskRun` | Constructible | ⚠️ **Synthetic** | Could reference a synthetic task LID, but can't determine which task produced which file |
| `size` | — | ❌ **Not available** | File sizes are not stored per-output |
| `createdAt` | — | ❌ **Not available** | Per-file creation timestamps are not stored |
| `modifiedAt` | — | ❌ **Not available** | Per-file modification timestamps are not stored |
| `labels` | — | ❌ **Not available** | Not stored per-file |

**FileOutput verdict:** ~0% reconstructable. Essentially none of the file-level provenance data exists in the API. This is the most critical gap because `FileOutput` records are the backbone of lineage traversal.

### 3.4 WorkflowOutput / TaskOutput Records

| Record | Feasibility | Notes |
|---|---|---|
| **WorkflowOutput** | ❌ **Not available** | Requires knowing published output paths and their LID mappings. API doesn't store this. |
| **TaskOutput** | ❌ **Not available** | Requires knowing task output channel declarations and their values. API doesn't store this. |

### 3.5 Lineage IDs (LIDs)

| LID Type | Feasibility | Notes |
|---|---|---|
| **WorkflowRun LID** | ⚠️ **Synthetic only** | The native lineage WorkflowRun LID is a hash of the workflow execution state. We cannot reproduce this. Could use the Platform `workflow.id` as a synthetic LID (e.g., `lid://platform-{workflow.id}`), but it won't match any natively-generated LIDs. |
| **TaskRun LID** | ⚠️ **Partial** | Native LIDs are based on the task hash (same as the cache hash). The API provides `task.hash` (the Nextflow work directory hash, e.g., `86/2df531...`). The first 2 chars + remaining form the full hash: `862df531...`. This is the *same hash* used for native lineage LIDs (`lid://862df53160e07cd823c0c3960545e747`). **However**, the API `task.hash` is truncated (short form like `86/2df531`) — only 8 hex chars, not the full 32-char hash. This means we cannot construct full LIDs from the API hash alone. |
| **FileOutput LID** | ❌ **Not constructible** | Based on content hashes of the actual files. Cannot be reconstructed without file access. |

---

## 4. Gap Report

### 4.1 Absolute Blockers (Cannot be reconstructed)

| Gap | Impact | Rationale |
|---|---|---|
| **Task input channel values & file references** | Breaks provenance graph | The API stores no information about what files or values were passed into each task's input channels. Without this, the DAG of data dependencies between tasks cannot be reconstructed. This is the single most important lineage feature. |
| **Output file paths per task** | No FileOutput records possible | The API doesn't record which files a task produced. The `workdir` path is known but the specific output files are not enumerated. |
| **File content checksums** | No integrity verification | Nextflow lineage checksums use a proprietary Murmur3-based hash (`CacheHelper`). Even if files still exist in storage, recomputing these checksums requires the Nextflow hasher. Standard checksums (MD5/SHA) would not be compatible. |
| **Full task hash** | LIDs are incomplete | The API provides truncated task hashes (~8 hex chars). Native LIDs use the full 32-char hash. Work directories may still exist on cloud storage containing the full hash in the path, but accessing them is not guaranteed and would require storage-level access. |

### 4.2 Partial Gaps (Reconstructable with caveats)

| Gap | Impact | Workaround |
|---|---|---|
| **Script file list with checksums** | Incomplete WorkflowRun.workflow | Can include main `scriptFile` path but without checksum. If git repository and commitId are known, script files could theoretically be enumerated from the git tree. |
| **Resolved config as Map** | WorkflowRun.config is approximate | `configText` is available as a string. A best-effort parser could extract key-value pairs, but Nextflow config syntax (closures, conditionals, profiles) makes reliable parsing infeasible without the Nextflow config engine. |
| **Parameter types** | WorkflowRun.params loses type info | Values are available, types can be heuristically inferred (`string`, `integer`, `boolean`, `path`) but won't match Nextflow's internal type system exactly. |
| **Code checksum** | TaskRun.codeChecksum unavailable | The resolved `script` is available, but the native `codeChecksum` hashes the *unresolved process source code*. These are different. Even hashing the resolved script would use a different algorithm than `CacheHelper`. |

### 4.3 Available but Unused by Lineage

The API provides rich data that lineage doesn't track but could supplement a "retroactive lineage" format:

- Execution timing (submit/start/complete per task)
- Resource usage (CPU, memory, I/O metrics)
- Cost data
- Machine types and cloud zones
- Exit statuses and retry attempts

---

## 5. Feasibility Assessment

### Can we produce spec-compliant lineage records?

**No.** The records would be structurally conformant (correct JSON shape with correct field names) but semantically incomplete:

- `WorkflowRun` — ~70% complete: identity fields present, config/scriptFiles degraded
- `TaskRun` — ~30% complete: script and container present, but `input` (the critical provenance field) completely absent
- `FileOutput` — ~0% complete: none of the required data exists in the API
- `WorkflowOutput` / `TaskOutput` — 0% complete

### Can we produce *useful* lineage records?

**Marginally.** The reconstructed records could answer:
- ✅ "What pipeline+revision ran, with what params?" (WorkflowRun)
- ✅ "What tasks ran, with what scripts and containers?" (TaskRun, partial)
- ❌ "What files did task X produce?" (FileOutput — impossible)
- ❌ "What upstream data produced this output?" (provenance traversal — impossible)
- ❌ "Are these two output files from the same computation?" (checksum comparison — impossible)

The provenance traversal use case — the raison d'être of data lineage — **cannot be supported**.

---

## 6. Recommended Approach

Given the analysis above, we recommend a **tiered strategy**:

### Tier 1: "Lineage-Lite" Metadata Export (Feasible Now)

Generate a custom metadata format that captures what the API *does* provide, structured to be as close to lineage records as possible:

**Implementation plan:**
1. Add a new module `modules/local/lineage_export/main.nf`
2. In `lib/SeqeraApi.groovy`, the existing `fetchRunData()` already retrieves all needed data
3. Create a Python script `bin/lineage_export.py` that transforms API data into lineage-shaped JSON:

```python
def build_workflow_run(workflow_data):
    return {
        "version": "lineage/v1beta1",
        "type": "WorkflowRun",
        "workflow": {
            "scriptFiles": [],  # Cannot populate with checksums
            "repository": workflow_data.get("repository"),
            "commitId": workflow_data.get("commitId"),
        },
        "sessionId": workflow_data.get("sessionId"),
        "name": workflow_data.get("runName"),
        "params": [
            {"type": infer_type(v), "name": k, "value": v}
            for k, v in (workflow_data.get("params") or {}).items()
        ],
        "config": {},  # Would need config parser
        "_meta": {
            "source": "retroactive-reconstruction",
            "platformRunId": workflow_data.get("id"),
            "complete": False,  # Flag as incomplete
        }
    }
```

4. Output records include a `_meta` extension field clearly marking them as retroactively reconstructed and incomplete.

**Entry points in nf-agg:**
- `workflows/nf_aggregate/main.nf` — add the lineage export module alongside `BENCHMARK_REPORT`
- `lib/SeqeraApi.groovy` — `fetchRunData()` already provides all needed API data
- New `bin/lineage_export.py` — transformation logic
- New `modules/local/lineage_export/main.nf` — Nextflow process wrapper

**Output format:** Directory of JSON files mimicking the `.lineage/` store structure:
```
lineage_export/
  <synthetic-workflow-lid>/         # WorkflowRun record
  <task-hash>/                      # TaskRun records (using short hash)
  manifest.json                     # Index of all records with completeness flags
```

### Tier 2: Augmented Lineage via Work Directory Scanning (Conditional)

If the Nextflow work directories (`task.workdir` paths from the API) are still accessible in cloud storage:

1. Read `.command.run` files from each task's work directory to get the full task hash
2. List output files in each work directory
3. Compute checksums of files still present
4. Parse `.command.log` or `.command.trace` for additional metadata

**Viability:** Highly dependent on data retention policies. Work directories are often cleaned up after pipeline completion. This approach works only if `nextflow clean` has not been run and cloud storage buckets still retain the data.

### Tier 3: Native Lineage for Future Runs (Recommended Long-term)

For any runs going forward, enable native Nextflow lineage (`lineage.enabled = true`) which captures complete provenance data at execution time. The retroactive approach should be seen as a bridge solution only.

---

## 7. Data Transformation Summary

| Source (Seqera API) | Target (Lineage Record) | Transformation |
|---|---|---|
| `workflow.id` | WorkflowRun LID | `lid://platform-{id}` (synthetic, non-standard) |
| `workflow.repository` | `WorkflowRun.workflow.repository` | Direct copy |
| `workflow.commitId` | `WorkflowRun.workflow.commitId` | Direct copy |
| `workflow.sessionId` | `WorkflowRun.sessionId` | Direct copy |
| `workflow.runName` | `WorkflowRun.name` | Direct copy |
| `workflow.params` | `WorkflowRun.params` | Convert `{k: v}` → `[{type: infer(v), name: k, value: v}]` |
| `workflow.configText` | `WorkflowRun.config` | Best-effort parse or store as `{"_raw": configText}` |
| `workflow.scriptFile` | `WorkflowRun.workflow.scriptFiles` | Single-entry list without checksum |
| `task.hash` | TaskRun LID | `lid://{normalized_hash}` (short, non-standard) |
| `task.name` | `TaskRun.name` | Direct copy |
| `task.script` | `TaskRun.script` | Direct copy |
| `task.container` | `TaskRun.container` | Direct copy |
| `workflow.sessionId` | `TaskRun.sessionId` | Direct copy |
| Synthetic WF LID | `TaskRun.workflowRun` | Reference to synthetic WorkflowRun LID |
| — | `TaskRun.input` | **Cannot populate** |
| — | `TaskRun.codeChecksum` | **Cannot populate** (resolved script ≠ source code) |
| — | `FileOutput.*` | **Cannot populate** |

---

## 8. Conclusions

1. **Full lineage reconstruction is not feasible.** The Seqera Platform API was not designed to capture the fine-grained data-flow information that Nextflow lineage tracks. The most critical missing pieces — task input references, output file paths, and file checksums — are fundamental to the lineage provenance model and cannot be derived from the API.

2. **Partial reconstruction is feasible and potentially useful** for audit/documentation purposes: recording which pipeline version, parameters, and containers were used for historical runs. This provides "what ran" but not "what data flowed where."

3. **The `nf-agg` codebase is well-positioned** to add a lineage export module. The `SeqeraApi.fetchRunData()` method already retrieves all available API data, and the pipeline architecture (modules + DuckDB) makes it straightforward to add a new output module.

4. **Recommended path forward:**
   - Implement Tier 1 (lineage-lite export) as a pragmatic documentation tool
   - Clearly mark all retroactive records as incomplete/synthetic
   - Enable native lineage for all future runs
   - Consider Tier 2 (work directory scanning) only for high-value historical runs where work directories are known to still exist

---

## Appendix A: Source Evidence

| Claim | Source File | Evidence |
|---|---|---|
| API provides `task.script` | Seqera API spec `Task` schema | `script: type: string` field in OpenAPI YAML |
| API provides `task.container` | Seqera API spec `Task` schema | `container: type: string` field |
| API provides `workflow.params` | Seqera API spec `Workflow` schema | `params: type: object, additionalProperties: true` |
| API provides `workflow.configText` | Seqera API spec `Workflow` schema | `configText: type: string` |
| API provides `workflow.commitId` | Seqera API spec `Workflow` schema | `commitId: maxLength: 40, type: string` |
| API provides `task.hash` | Seqera API spec `Task` schema | `hash: type: string` |
| API does NOT provide task inputs | Seqera API spec `Task` schema | No `input` field in the Task schema |
| API does NOT provide file outputs | Seqera API spec | No file-level output endpoint exists |
| Lineage uses Murmur3 checksums | `Checksum.groovy` source | `CacheHelper.hasher()` → Murmur3 hash |
| Lineage `codeChecksum` hashes source | `TaskRun.groovy` source | "Checksum of the task source code" (not resolved script) |
| `nf-agg` fetches 4 endpoints | `lib/SeqeraApi.groovy` | `fetchRunData()` calls `/workflow/{id}`, `/workflow/{id}/metrics`, `/workflow/{id}/tasks`, `/workflow/{id}/progress` |
| `nf-agg` task data includes hash, name, script | `bin/benchmark_report.py` L140-170 | `build_database()` extracts `hash`, `name`, `process`, `script` not used but available |

## Appendix B: Nextflow Lineage Source Model Reference

Source: [`nextflow-io/nextflow`](https://github.com/nextflow-io/nextflow/tree/master/modules/nf-lineage/src/main/nextflow/lineage/model/v1beta1)

```
LinModel.VERSION = "lineage/v1beta1"

WorkflowRun { workflow: Workflow, sessionId: String, name: String, params: List<Parameter>, config: Map }
Workflow { scriptFiles: List<DataPath>, repository: String, commitId: String }
TaskRun { sessionId, name, codeChecksum: Checksum, script, input: List<Parameter>, container, conda, spack, architecture, globalVars: Map, binEntries: List<DataPath>, workflowRun: String }
FileOutput { path, checksum: Checksum, source, workflowRun, taskRun, size: long, createdAt, modifiedAt, labels: List<String> }
WorkflowOutput { createdAt, workflowRun, output: List<Parameter> }
TaskOutput { taskRun, workflowRun, createdAt, output: List<Parameter>, labels: List<String> }
Checksum { value, algorithm, mode }
DataPath { path, checksum: Checksum }
Parameter { type, name, value: Object }
```
