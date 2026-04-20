---
name: fetch-and-compare-platform-runs
description: >
  Fetch Seqera Platform run data for nf-aggregate and compare scheduling,
  runtime, task status, and cost patterns across runs. Use when investigating
  benchmark candidates, refreshing `.seqera/context`, or validating run-level
  differences before building a report.
---

# Fetch and compare Platform runs

Use this skill when the user wants to inspect one or more Seqera Platform runs

before or instead of building a full benchmark report.

## Best workflow

### 1) Fetch run JSON through the repo's standalone fetch path

```bash
env TOWER_ACCESS_TOKEN="$TOWER_ACCESS_TOKEN" \
  uv run --with typer --with pyyaml \
  python bin/benchmark_report.py fetch \
  --run-ids <RUN_ID_1> \
  --run-ids <RUN_ID_2> \
  --workspace <org/workspace> \
  --api-endpoint <https://api.cloud.seqera.io or other API base> \
  --output-dir /tmp/run_json
```

This uses the same workspace-resolution and API-fetch logic as the pipeline.

### 2) Inspect the fetched JSON before normalizing

Check:

- workflow status and timestamps
- commit/revision
- number of tasks fetched
- task states: completed / running / failed
- submit-&gt;start wait time
- start-&gt;complete runtime
- instance / machine-type differences
- per-task cost signals where available

### 3) Only then decide whether to

- update `.seqera/context`
- normalize to JSONL for a benchmark report
- compare dev vs prod or scheduler vs batch runs

## What to compare

For each run, extract:

- `runName`
- `status`
- `submit`, `start`, `complete`
- `commitId`
- `projectName`
- task counts by status
- representative processes observed
- average and max scheduling delay
- average runtime of completed tasks
- obvious cost or machine-type differences

## Repo-specific interpretation hints

- Short-task variance often comes from Batch/spot provisioning and staging jitter.
- Large submit-&gt;start gaps usually indicate scheduling overhead, not process-level code regressions.
- The most meaningful report differences often appear later in heavier alignment/indexing phases, so early QC-only comparisons can be misleading.
- If runs are still active, state that clearly and call out what phases have not yet been observed.

## When to escalate to full report generation

Build a full benchmark report when:

- there are enough completed tasks to compare cohorts meaningfully
- the user wants charts or HTML output
- cost and aggregated process summaries matter more than raw run inspection
- you need JSONL handoff artifacts for downstream debugging
