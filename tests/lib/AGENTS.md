# tests/lib/

## Purpose

This directory holds nf-test `nextflow_function` tests for helper code under `lib/`.

Current coverage:

- `SeqeraApi.groovy.test` — unit-ish behavioral coverage for `SeqeraApi` helpers using nf-test function tests and inline Groovy stubbing.

## Conventions

Reference: nf-test Function Testing docs — https://www.nf-test.com/docs/testcases/nextflow_function/

- Prefer `nextflow_function` tests here instead of introducing a separate Spock/Gradle harness.
- Keep assertions local and explicit.
- Stub `SeqeraApi.metaClass.'static'.apiGet` inline when isolating pagination or workspace-resolution behavior.
- Reserve pipeline routing/integration scenarios for the sibling `tests/pipeline_*/` directories.
