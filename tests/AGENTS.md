# tests/

## Layout
Each pipeline-level scenario lives in its own directory:

- `pipeline_api_only/`
- `pipeline_mixed_no_benchmark/`
- `pipeline_benchmark_tarball/`
- `pipeline_benchmark_directory/`

Each scenario directory contains:
- `main.nf.test` — the nf-test scenario
- `main.nf.test.snap` — the snapshot for that scenario
- `AGENTS.md` — scenario-specific guidance for future edits

## Conventions
- One scenario per directory.
- Keep assertions local and explicit rather than heavily abstracted.
- Prefer stable fixture files under `workflows/nf_aggregate/assets/`.
- If routing behavior changes, update the scenario-specific `AGENTS.md` along with the test.

## Running tests
Run all pipeline-level scenario tests with:

```bash
find tests -name 'main.nf.test' | sort | xargs nf-test test --profile=+docker --verbose
```
