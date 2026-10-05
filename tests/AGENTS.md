# tests/

## Layout

Pipeline-level scenarios live in their own directories:

- `pipeline_api_only/`
- `pipeline_mixed_no_benchmark/`
- `pipeline_benchmark_tarball/`
- `pipeline_benchmark_directory/`
- `pipeline_benchmark_realworld_costs/`

Each scenario directory contains:

- `main.nf.test` — the nf-test scenario
- `main.nf.test.snap` — the snapshot for that scenario
- `AGENTS.md` — scenario-specific guidance for future edits

Function-level nf-test coverage for `lib/` helpers lives separately under:

- `lib/`

Reference: nf-test Function Testing docs — https://www.nf-test.com/docs/testcases/nextflow_function/

## Conventions

- One scenario per directory.
- Keep assertions local and explicit rather than heavily abstracted.
- Prefer stable fixture files under `workflows/nf_aggregate/assets/`.
- If routing behavior changes, update the scenario-specific `AGENTS.md` along with the test.
- Pipeline routing/integration scenarios live under `tests/pipeline_*/`.
- Function-level nf-test coverage for Groovy helpers under `lib/` lives under `tests/lib/`.
- Stage-specific pytest tests live beside the relevant module under `modules/local/*/tests/`.

## Running tests

Run all pipeline-level scenario tests with:

```bash
find tests -name 'main.nf.test' | sort | xargs nf-test test --profile=test,conda --verbose
```
