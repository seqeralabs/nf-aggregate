# pipeline_seqera_api_helpers

## Purpose

Smoke-tests `SeqeraApi` pagination and workspace resolution without nf-test `nextflow_function` (Nextflow cannot compile the generated `fn(*input)` calls).

## Expected behavior

- Workflow completes with no processes and all inline assertions pass.
