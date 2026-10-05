# tests/lib/

## Purpose

This directory holds nf-test `nextflow_function` tests for helper code under `lib/`.

Current coverage:

- `../pipeline_seqera_api_helpers/` — inline workflow smoke tests for `SeqeraApi` helpers (nf-test `nextflow_function` cannot compile `fn(*input)` on current Nextflow).

## Conventions

Reference: nf-test Function Testing docs — https://www.nf-test.com/docs/testcases/nextflow_function/

- Prefer `nextflow_function` tests here instead of introducing a separate Spock/Gradle harness.
- Keep assertions local and explicit.
- Stub `SeqeraApi.metaClass.'static'.apiGet` inline when isolating pagination or workspace-resolution behavior.
- Reserve pipeline routing/integration scenarios for the sibling `tests/pipeline_*/` directories.
