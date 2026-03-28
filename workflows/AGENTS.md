# workflows/ — Nextflow Workflows

## nf_aggregate/main.nf

Main orchestrator workflow. Takes: ids channel, multiqc config/logo, API endpoint, skip flags, truststore params.

### Input Routing

Runs are split into two paths using `branch{}` on the `ids` channel:
- **API runs** (`workspace != 'external'`): fetched via Seqera Platform API
- **External runs** (`workspace == 'external'` + `logs` path): data provided as tarballs

### Execution Paths

1. **API runs:** `SEQERA_RUNS_DUMP` → run dumps for MultiQC + Gantt
2. **External runs:** `EXTRACT_TARBALL` → extracted JSON files for benchmark report
3. **Fusion API runs + !skip_run_gantt:** `PLOT_RUN_GANTT` per fusion-enabled run
4. **generate_benchmark_report:** API JSONs + tarball JSONs merged → `CLEAN_JSON` → `BUILD_TABLES` → `RENDER_REPORT`
5. **!skip_multiqc:** `MULTIQC` aggregating API run dumps + version info

### Benchmark Data Collection

Two parallel paths feed into the benchmark report:

**Path A (API):** `SeqeraApi.fetchRunData()` in `map{}` → JSON files in `workDir/run_data/`
**Path B (Tarball):** `EXTRACT_TARBALL` → JSON files extracted from `.tar.gz`

Both are merged via `mix().collect()` into `workDir/benchmark_data/` dir.

### Software Versions

All process versions collected → `collated_software_mqc_versions.yml` in `pipeline_info/`.

### Config

`workflows/nf_aggregate/nextflow.config` — included from root `nextflow.config`. Contains workflow-specific param defaults.
