# workflows/ — Nextflow Workflows

## nf_aggregate/main.nf

Main orchestrator workflow. Takes: ids channel, multiqc config/logo, API endpoint, skip flags, truststore params.

### Execution Paths

1. **Always:** `SEQERA_RUNS_DUMP` → collects run dumps for MultiQC + Gantt
2. **Fusion runs + !skip_run_gantt:** `PLOT_RUN_GANTT` per fusion-enabled run
3. **generate_benchmark_report:** `SeqeraApi.fetchRunData()` in `map{}` → collect JSONs → `BENCHMARK_REPORT`
4. **!skip_multiqc:** `MULTIQC` aggregating all run dumps + version info

### Data Collection Pattern

```nextflow
ids.map { meta ->
    def data = SeqeraApi.fetchRunData(meta, seqera_api_endpoint)
    data.meta = [id: meta.id, workspace: meta.workspace, group: meta.group ?: 'default']
    return data
}
```

Runs in the Nextflow head process (no container). Writes JSON files to `workDir/run_data/`, copies to `workDir/benchmark_data/` dir, passes to `BENCHMARK_REPORT`.

### Software Versions

All process versions collected → `collated_software_mqc_versions.yml` in `pipeline_info/`.

### Config

`workflows/nf_aggregate/nextflow.config` — included from root `nextflow.config`. Contains workflow-specific param defaults.
