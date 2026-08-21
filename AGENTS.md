# nf-aggregate

Nextflow pipeline to aggregate metrics across Seqera Platform pipeline runs.

## Git workflow

- **Trunk-based development.** `main` is the trunk and the single long-lived branch. The old
  `dev` branch and any Git Flow (`dev` → release → `main`) conventions are retired — do not
  target `dev`.
- **Branch off `main`.** Create short-lived feature branches from `main` and open pull
  requests back into `main`.
- Keep branches short-lived; commit small and often (conventional commits + gitmoji).
- `commit.gpgsign` must be true (SSH signing via 1Password).

## Architecture

```
input CSV (id, workspace, group, logs, platform, token_env, machines)
  → branch: api (SeqeraApi.fetchRunData) | external (EXTRACT_TARBALL)
  → collect JSON files
  → NORMALIZE_BENCHMARK_JSONL (raw JSON -> jsonl_bundle/)
  → AGGREGATE_BENCHMARK_REPORT_DATA (jsonl_bundle -> report_data.json)
  → RENDER_BENCHMARK_REPORT (report_data.json -> benchmark_report.html)
```

There is no `fusion` column in the samplesheet. Fusion enablement is derived from the
run's API payload (`workflow.fusion.enabled`) during normalization — it is display-only
and never an input.

## Key Params

| Param                       | Default                       | Purpose                           |
| --------------------------- | ----------------------------- | --------------------------------- |
| `generate_benchmark_report`   | false                         | Enable benchmark/IC report                        |
| `report_type`                 | `benchmark`                  | `benchmark` or `intelligent_compute`              |
| `benchmark_aws_cur_report`    | null                          | AWS CUR parquet for cost analysis                 |
| `benchmark_aws_cur_label_map` | null                          | YAML aliases for custom CUR resource label names  |
| `seqera_api_endpoint`         | `https://api.cloud.seqera.io` | Platform API URL                                  |
| `seqera_web_url`              | `https://cloud.seqera.io`    | Platform web base URL for run deep-links          |
| `intelligent_compute_core_report` | null                     | Optional core cost report for IC (not yet wired)  |

The `intelligent_compute_report` profile bundles the IC-report flags
(`generate_benchmark_report = true`, `report_type = 'intelligent_compute'`) so a run only
needs `--input`/`--outdir` (and optionally `--benchmark_aws_cur_report`), e.g.
`-profile docker,intelligent_compute_report`. It intentionally sets no input/output paths.

## Plugins

- `nf-core-utils@0.4.0` — utility helpers such as Conda checks and software-version reporting
- `nf-schema@2.3.0` — param validation and samplesheet parsing

## Env Requirements

- `TOWER_ACCESS_TOKEN` — Seqera Platform API token (forwarded via `env {}` block in nextflow.config)

## Rebuild Command (local testing)

```bash
# Normalize raw run JSON (+ optional CUR parquet) to JSONL bundle:
uv run --with typer --with pyyaml --with pyarrow \
  python bin/benchmark_report.py normalize-jsonl \
  --data-dir /path/to/json_data --output-dir /tmp/jsonl_bundle

# Normalize raw run JSON with CUR cost enrichment + custom label aliases:
uv run --with typer --with pyyaml --with pyarrow \
  python bin/benchmark_report.py normalize-jsonl \
  --data-dir /path/to/json_data --costs /path/to/cur.parquet \
  --cost-label-map /path/to/cur_label_map.yml \
  --output-dir /tmp/jsonl_bundle

# Aggregate JSONL bundle to report data:
uv run --with typer --with pyyaml \
  python bin/benchmark_report.py aggregate-report-data \
  --jsonl-dir /tmp/jsonl_bundle --output /tmp/report_data.json

# Render HTML report from report_data.json:
uv run --with jinja2 --with typer --with pyyaml \
  python bin/benchmark_report.py render-html \
  --data /tmp/report_data.json --brand assets/brand.yml --output /tmp/report.html

# Fetch run data from Seqera Platform API (standalone):
uv run --with typer --with pyyaml \
  python bin/benchmark_report.py fetch \
  --run-ids <id> --workspace org/name --output-dir /tmp/json_data
```

## Gotchas

- Wave freeze strategy: `['conda', 'container', 'dockerfile']` — no `spack` (breaks builds)
- JSONL is the primary handoff (`jsonl_bundle/`) for Fusion-friendly streaming
- `report_data.json` is the explicit boundary between aggregation and rendering
- When a CUR file is supplied but a run has no matching cost rows, aggregation sets `run_costs[].cost_status` to `propagating` (run finished < 24h ago, per `_COST_PROPAGATION_WINDOW_HOURS`, so CUR data likely hasn't landed) or `not_found` (older run, genuinely absent). The report renders `pending` / `no data` instead of a bare dash. Runs with matched cost are `available`; no CUR at all leaves `cost_status` null.
- **Two CUR cost bases, never summed.** AWS emits ECS split cost allocation rows *in addition to* the parent EC2 instance rows they were derived from, so the two describe the same compute. Intelligent Compute tags the instances themselves, so an IC run on the ECS architecture matches both classes — summing them overstated affected runs by ~1.5x (median, measured on a real export). AWS Batch tags only the task, so its instance rows carry no run tag and it was never affected. `normalize` therefore emits `unblended_cost`, `split_cost` and `unused_cost` as separate fields (plus single-basis `cost`/`used_cost` conveniences that prefer the billed instance charge). Note IC split rows carry no `pipeline_process`/`task_hash` labels, so they collapse into the same `(run_id, '', '')` group as the instance rows — the bases are separable only as columns, never by row class after grouping. The IC report exposes the two bases as fixed, non-substituting columns: `cost` (billed machine charge, null for AWS Batch which labels only tasks) and `comparable_cost` (split basis, null for IC on the VM architecture). Neither ever falls back to the other, so a blank cell means that basis does not exist for the run; there is no `cost_basis` field because each column is itself a basis. Cross-engine comparison views use `comparable_cost` and omit runs lacking it, since split cost is amortized and unblended is not. `cost_status` (`available`/`propagating`/`not_found`/null) mirrors the benchmark report.
- **Spot vs on-demand is a subset of the unblended basis, not a third one.** `normalize` emits `spot_cost`/`ondemand_cost` alongside the three cost fields, summed from the EC2 *instance-hour* rows only (`line_item_usage_type` matching `SpotUsage:`/`BoxUsage:`), classified by `product_marketoption` when the export flattens it and by the usage type otherwise (CUR 2.0 nests it in the `product` map). The usage-type gate is load-bearing twice over: it drops the EBS/data-transfer rows tagged to the same run, which are not machine rental, and it drops the EBSOptimized surcharge, which AWS labels `OnDemand` even on a Spot instance — ungated that made 56,894 instance ids in a real export look like they carried two purchase options. So `spot_cost + ondemand_cost < unblended_cost` is expected, never a bug. The IC report applies the engine gate in `_purchase_option_split`: Intelligent Compute only, because AWS Batch labels no machines and a 0% spot reading for it would be a false claim rather than a blank. Surfaced in exactly two places — the Overview "Spot coverage" card (fleet total, weighted by spend, not a mean of per-run percentages) and the Cost section's fourth "Spot mix" view. Deliberately NOT a run summary column; that table is already at ten.
- **Resumed runs are billed per SESSION, not per workflow id.** `-resume` mints a new workflow id, so every CUR run-id label (`uniqueRunId` = `TOWER_WORKFLOW_ID`, `seqera.io/platform/workflowId`) names one attempt only. `normalize` therefore also reads a session label (`nextflow.io/sessionId` → `user_nextflow_io_session_id` for Intelligent Compute, `pipelineSessionId` → `user_pipeline_session_id` for the Batch blog template; overridable via the `session_id` field of `benchmark_aws_cur_label_map`) and grains cost rows by `(run_id, session_id, process, hash)`. `_load_cost_pools` in `benchmark_report_aggregate.py` — shared with the IC report — indexes those rows `by_task`, `by_run` and, for resumed runs only, `by_session`. The session label is NEVER a replacement join key: plenty of exports lack it, and swapping to it would turn "no session label" into a silent $0. A run counts as resumed when it has cached tasks (or the Platform resume flag), so a report with no resumed runs is byte-identical to before.
- **The resume trigger is cached tasks; the money follows the task hash.** Cached tasks are priced from the attempt that ran them by matching the CUR `task_hash` inside the session pool — Nextflow hashes are content-addressed and survive a resume. Per-run cost for a pooled run is the whole session pool (not Σ matched tasks), so lineage rows that map to no surviving task are not dropped. `_session_owners` gives each session exactly ONE owning run (the newest attempt), which is what prevents double counting when a samplesheet lists two attempts of one session. `earlier_attempts` (attempts other than this one) is the field the reports display, because a fresh resume has no rows of its own and a bare attempt count would read "1" while all the money came from an ancestor. When the pool covers fewer task hashes than the run has tasks, aggregation logs a warning and sets `lineage_incomplete`, and both reports call the total a lower bound.
- **Resumed cost is additive reporting, never mixed into a rate.** Pooled lineage cost lives in its own fields (`cost_last_attempt`/`earlier_attempts` in the benchmark report; `session_cost`/`session_comparable_cost` in the IC report) and is rendered *beside* the attempt figure. Every other number in a run row — `wall_time_ms`, `compute_hours`, req/eff vCPU-h, the machine breakdown, and the machines CSV when supplied — describes the reported attempt alone, so $/vCPU-h, spot coverage and all utilisation figures stay on the attempt basis. The two cost bases stay separate here too: an IC lineage reports on the billed unblended basis, a Batch lineage only on the ECS split basis, hence separate `earlier_attempt_cost` and `earlier_attempt_comparable_cost` in `ic_overview`.
- **Cached tasks need no metric backfill.** Platform returns cached tasks with the full trace record of their original execution (cpus, memory, pcpu, rss/peakRss, read/write bytes, machineType, realtime, original timestamps); only `exitStatus`/`errorAction`/`disk`/`numSpotInterruptions` are null, and the metrics endpoint includes cached tasks in its per-process distributions. So run-level CPU-hours, memory and I/O already span the lineage — cost was the only asymmetry. Side effect worth remembering: a cached task's `submit`/`start`/`complete` come from the earlier attempt, so a resumed run's timeline and `wait_ms`/`staging_ms` mix two eras.
- **`bin/` is what the pipeline runs; `modules/local/*/bin/` is what the tests import.** Nextflow only auto-adds the project `bin/` to `$PATH` (module `bin/` dirs are not `resources/usr/bin`, so they are never staged), while `conftest.py` puts the module dirs ahead of `bin/` on `sys.path`. Editing only the module copy leaves the shipped pipeline on stale code and the tests green — exactly the drift that left `bin/benchmark_report_aggregate.py` and `bin/benchmark_report_template.html` missing the `cost_status` work. After touching any of `benchmark_report_{normalize,aggregate,ic_aggregate,render}.py` or either `*_template.html`, copy the module version over the `bin/` one and diff to confirm.
- **Never call `Path.exists()`/`is_dir()`/`glob()` on a Nextflow-staged input without a guard.** Inputs arrive as symlinks in the task dir, and with Fusion they resolve into the NFS mount, where a lookup can fail with **EACCES** (an S3 403, or a prefix the client will not stat) rather than ENOENT. Python 3.12's `Path.exists()` only swallows ENOENT/ENOTDIR/EBADF/ELOOP (`pathlib._IGNORED_ERRNOS == (2, 20, 9, 62)`), so EACCES propagates — that is how `PermissionError: [Errno 13] Permission denied: 'data'` killed a whole benchmark report over the OPTIONAL CUR input, after runs/tasks/metrics.jsonl were already written. Python 3.13+ swallows it instead and would silently emit a cost-free report, which is no better. Use `_require_readable()` (present/absent, raises on unreadable) or `_path_status()` (three-way) from `benchmark_report_normalize.py`, both shared by every stage, and decide per input: the CUR path defers to DuckDB (a path we cannot *walk* may still be *readable*) and only a DuckDB failure is fatal, machine telemetry warns and degrades, the run-data directory fails with a named path. `_unreadable_input_message` carries the actionable cause (missing `s3:ListBucket`+`s3:GetObject`; a directory input needs LIST, not just object read). Guarded sites, all of which take staged inputs: `normalize` (CUR path, machines dir, run-data dir, machine CSV walk), `aggregate`/`aggregate_ic` (`_iter_jsonl` over the JSONL bundle, and the `costs.jsonl` presence test that decides `cur_supplied` — an unreadable file there would relabel every run's `cost_status` as null and present a cost-free report as intentional), and `render` (brand.yml, logo.svg staged from `projectDir`). Deliberately NOT guarded: the report template and the ECharts theme ship inside the container image rather than being staged, and the theme lookup is a fallback chain that skips an unreadable candidate.
- **The CUR location is probed on the head node before anything is staged** (`workflows/nf_aggregate/main.nf`). A directory location is globbed as `<location>/**/*.parquet` with the pipeline's own credentials; a location that cannot be listed, or that holds no parquet, stops the run immediately with the path and the required grants in the message. The task cannot diagnose this itself — from inside the container a prefix it may not LIST is indistinguishable from an empty one, and by then a task has been provisioned and run for minutes. A single `*.parquet` location skips the probe, since it needs only object read. Verified against real Nextflow for trailing slashes, partitioned (`BILLING_PERIOD=`) layouts, empty directories and missing paths.
- `commit.gpgsign` must be true (SSH signing via 1Password)
- RTK `buildOutputFiltering` / `testOutputAggregation` can swallow nf-test output — disable to debug
- **Nextflow `include` statements in `main.nf` must be single-line.** `adamrtalbot/detect-nf-test-changes@v0.0.3` (used by CI) parses include lines and crashes on multi-line blocks. Write `include { A ; B ; C } from '...'` not multi-line blocks.
- **Repository hygiene:** `.nf-core.yml` should stay absent unless nf-core linting is intentionally restored alongside the required config. When changing CI, docs, or plugin declarations, remove stale nf-core-template remnants and keep labels/docs accurate.
- **Plugin references must stay synchronized.** If `nextflow.config` plugin entries change, update `CITATIONS.md`, `README.md`, and agent/context files in the same change so pinned plugins such as `nf-core-utils` and `nf-schema` are cited consistently.
- **`nextflow lint -harshil-alignment -format` is destructive on existing files.** Running `-format` on the existing `nextflow.config` / `workflows/nf_aggregate/main.nf` collapses multi-line blocks and deletes inline comments. Only use `-format` on brand-new `.nf` files. For edits to existing config/workflow files, verify with `nextflow lint -harshil-alignment <file>` (no `-format`) and match surrounding style by hand.

## Cursor Cloud specific instructions

### Services overview

| Service                    | Purpose                                                             | Run command                                                     |
| -------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------- |
| Nextflow pipeline          | Core product — aggregates metrics from Seqera Platform runs         | `nextflow run . --input <csv> --outdir results -profile docker` |
| Python benchmark_report.py | Normalizes JSON -> JSONL, aggregates report data, then renders HTML | See "Rebuild Command" section above                             |

### Running tests

- **pytest (Python unit tests):** `uv run --with typer --with pyyaml --with jinja2 --with pyarrow --with pytest --with httpx pytest -v modules/local/aggregate_benchmark_report_data/tests/test_aggregate.py modules/local/normalize_benchmark_jsonl/tests/test_normalize.py modules/local/render_benchmark_report/tests/test_render.py bin/test_benchmark_report_fetch.py`
- **nf-test (pipeline integration tests):** `nf-test test --profile=+docker --verbose`
- **Lint:** `pre-commit run --all-files`

### Running on Apple Silicon (ARM64)

All pipeline containers are `linux/amd64` only (the Wave community image has no ARM64 variant). On ARM Macs, Docker runs these via QEMU/Rosetta emulation — tests and the pipeline work without any changes.

For explicit x86_64 emulation (recommended on ARM Macs to avoid Docker platform-mismatch warnings), combine the `arm` profile with `docker`:

```bash
# nf-test
nf-test test --profile=+docker,+arm --verbose

# direct nextflow run
nextflow run . --input workflows/nf_aggregate/assets/test_benchmark.csv \
  --generate_benchmark_report --outdir results -profile docker,arm
```

The `arm` profile adds `--platform=linux/amd64` to Docker run options so the container engine picks the correct image manifest instead of silently falling back.

Python unit tests (`pytest`) run natively on ARM — no `arm` profile needed for those.

### Agent quick verify (offline)

Run this exact sequence when validating split benchmark-report changes in Cursor Cloud:

1. `uv run --with typer --with pyyaml --with jinja2 --with pyarrow --with pytest --with httpx pytest -v modules/local/aggregate_benchmark_report_data/tests/test_aggregate.py modules/local/normalize_benchmark_jsonl/tests/test_normalize.py modules/local/render_benchmark_report/tests/test_render.py bin/test_benchmark_report_fetch.py`
2. `nf-test test --profile=+docker --verbose`
3. `nextflow run . --input workflows/nf_aggregate/assets/test_benchmark.csv --generate_benchmark_report --outdir /tmp/nf-aggregate-e2e-results -profile docker`
4. `pre-commit run --all-files` — **must pass before the final commit/push**. The `prettier` hook auto-fixes files in place; if it reports "files were modified by this hook", stage the changes (`git add -u`) and re-run until it passes. The `editorconfig-checker` hook only reports errors (no auto-fix) — fix those manually.

### Docker in Cloud VM (cgroupv2 workaround)

The Cloud VM runs inside a Firecracker VM where the root cgroupv2 hierarchy cannot delegate `memory`/`io` controllers. Docker containers that request resource limits (`--memory`, `--cpu-shares` — used by Nextflow's `process { memory; cpus }`) will fail with `"cannot enter cgroupv2 ... with domain controllers"`.

**Workaround:** A `runc` wrapper at `/usr/bin/runc` strips `linux.resources` from the OCI spec before passing to the real runtime at `/usr/bin/runc.real`. This is already set up in the VM snapshot. If Docker container launches fail with cgroup errors after a fresh setup, re-apply:

```bash
# Ensure /usr/bin/runc.real exists (backup of original runc)
sudo cp /usr/bin/runc /usr/bin/runc.real 2>/dev/null || true
# Install wrapper
cat > /tmp/runc-wrapper.sh << 'WRAPPER'
#!/bin/bash
for arg in "$@"; do
    if [ "$arg" = "create" ]; then
        bundle_dir=""
        next_is_bundle=false
        for a in "$@"; do
            if $next_is_bundle; then bundle_dir="$a"; break; fi
            if [ "$a" = "--bundle" ] || [ "$a" = "-b" ]; then next_is_bundle=true; fi
        done
        if [ -n "$bundle_dir" ] && [ -f "$bundle_dir/config.json" ]; then
            python3 -c "
import json
with open('$bundle_dir/config.json') as f: config = json.load(f)
if 'linux' in config and 'resources' in config['linux']: del config['linux']['resources']
with open('$bundle_dir/config.json', 'w') as f: json.dump(config, f)
" 2>/dev/null
        fi
        break
    fi
done
exec /usr/bin/runc.real "$@"
WRAPPER
chmod +x /tmp/runc-wrapper.sh
sudo cp /tmp/runc-wrapper.sh /usr/bin/runc
```

### Running the pipeline without TOWER_ACCESS_TOKEN

The default test profile CSV references API runs requiring `TOWER_ACCESS_TOKEN`. For offline testing, use the external tarball fixtures:

```bash
nextflow run . --input workflows/nf_aggregate/assets/test_benchmark.csv \
  --generate_benchmark_report --outdir results -profile docker
```

### Docker daemon startup

Docker must be started manually in the Cloud VM:

```bash
sudo dockerd &>/tmp/dockerd.log &
sleep 3
sudo chmod 666 /var/run/docker.sock
```
