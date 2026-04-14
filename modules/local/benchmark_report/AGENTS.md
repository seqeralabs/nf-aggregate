# benchmark_report (compat config)

Purpose
- Shared publishDir configuration for the benchmark-report stages.

Owns
- `nextflow.config` only

Applies to
- `NORMALIZE_BENCHMARK_JSONL`
- `AGGREGATE_BENCHMARK_REPORT_DATA`
- `RENDER_BENCHMARK_REPORT`

Invariants
- Published benchmark artifacts land under `${params.outdir}/benchmark_report/`.
- `versions.yml` stays unpublished here and is collated by the workflow.
- `jsonl_bundle/` should publish as a directory with its JSONL members beneath it.

Edit guidance
- Keep this file about publishing behavior only.
- If output filenames or process names change, update this config and the pipeline snapshots together.
