# ERRORS.md — Known Errors and Failure Modes

## Current Runs — No Errors Observed

Both runs `1cF65l2PDvxNd5` (maniac_celsius) and `5VGC0gjEmghOaz` (clever_kalman) are **RUNNING** with all observed tasks COMPLETED with exit code 0. No task failures, retries, or OOM kills detected in the first 20 tasks of each run.

## Historical / Known Failure Modes

### 1. TOWER_ACCESS_TOKEN Missing

**When:** API-mode runs (non-external workspace entries) without the token set.

**Error:** `RuntimeException: Environment variable 'TOWER_ACCESS_TOKEN' is not set (required for run <id>)`

**Fix:** Export `TOWER_ACCESS_TOKEN` before running the pipeline. The env var name can be overridden per-row via the `token_env` CSV column.

### 2. Workspace Resolution Failure

**When:** The `workspace` column value (e.g., `org/workspace`) doesn't match any accessible workspace.

**Error:** `RuntimeException: Organization '<name>' not found` or `Workspace '<name>' not found in org '<name>'`

**Fix:** Verify the org/workspace names in the input CSV match the Platform exactly (case-sensitive).

### 3. API Rate Limiting / Transient Failures

**When:** Fetching data from busy Platform instances with many concurrent runs.

**Mitigation:** Built-in retry with exponential backoff (3 attempts, 1s/2s/4s delays). After 3 failures, the pipeline aborts with the original error.

### 4. Wave Container Build Failures

**When:** Using `wave` profile with `spack` strategy.

**Error:** Wave freeze builds fail with spack.

**Fix:** The wave profile explicitly uses `strategy = ['conda', 'container', 'dockerfile']` — no spack. Don't add spack to the strategy list.

### 5. CGROUPv2 Docker Failures (Cloud VM / Firecracker)

**When:** Running with Docker in Cloud VMs where cgroup resource delegation is restricted.

**Error:** `cannot enter cgroupv2 ... with domain controllers`

**Fix:** Apply the runc wrapper documented in AGENTS.md that strips `linux.resources` from the OCI spec.

### 6. Empty Benchmark Report

**When:** API runs are provided but `--generate_benchmark_report` is not set.

**Warning:** `Found N API run(s) but --generate_benchmark_report is not enabled. API runs will not produce any output.`

**Fix:** Add `--generate_benchmark_report` to the run command.

### 7. Scheduling Overhead (Observed Pattern)

**Not an error per se**, but both current runs show 4–8 minute gaps between task submit and task start times. This is expected with AWS Batch spot instances — EC2 instances must be provisioned and containers pulled before execution begins. Not actionable unless overhead exceeds ~15 minutes consistently.

## Data Gaps

- **No failed runs analysed:** Both Platform runs are currently successful. To populate this section with real failure analysis, re-run context generation after a failure occurs or provide historical failed run IDs.
- **No STAR/alignment task data yet:** Both runs are still in early stages (QC/trim). Resource pressure and potential OOM failures during STAR genome generation and alignment are not yet observable.
- **No cost data:** Neither run has completed, so total run cost is unavailable. Individual task costs are in the $0.001–$0.007 range for early QC tasks.
