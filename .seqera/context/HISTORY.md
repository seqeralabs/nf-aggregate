# HISTORY.md — Recent Runs Analysed

## Seqera Platform Runs (unified-compute/sched-testing)

### Run 1: `maniac_celsius` (1cF65l2PDvxNd5)

- **Pipeline:** nf-core/rnaseq
- **Status:** RUNNING (as of 2026-04-17T18:45)
- **Submitted:** 2026-04-17T17:51:26Z
- **Started:** 2026-04-17T17:53:20Z
- **User:** edmund-miller
- **Executor:** seqera/aws (AWS Batch, eu-west-1)
- **Price model:** spot instances
- **Workspace:** unified-compute/sched-testing (ID: 224344613053615)
- **Work dir:** s3://nextflow-ci-dev/scratch/1cF65l2PDvxNd5/

**Task Summary (30 tasks captured from API fetch):**

- 21 tasks COMPLETED, 9 tasks RUNNING, 0 FAILED
- Completed early-stage tasks include `SAMTOOLS_FAIDX`, `GTF_FILTER`, `FQ_LINT`, and `GTF2BED`
- Active work is mostly `TRIMGALORE` fan-out across samples plus `SALMON_INDEX`
- `STAR_GENOMEGENERATE_IGENOMES` is defined in the run graph but was not yet observed as running/completed in the fetched task set

**Scheduling overhead:** Tasks show 4–8 min gap between submit and start (spot instance spin-up).

### Run 2: `clever_kalman` (5VGC0gjEmghOaz)

- **Pipeline:** nf-core/rnaseq
- **Status:** RUNNING (as of 2026-04-17T18:45)
- **Submitted:** 2026-04-17T17:50:14Z
- **Started:** 2026-04-17T17:52:09Z
- **User:** edmund-miller
- **Executor:** seqera/aws (AWS Batch, eu-west-1)
- **Price model:** spot instances
- **Workspace:** unified-compute/sched-testing (ID: 224344613053615)
- **Work dir:** s3://nextflow-ci-dev/scratch/5VGC0gjEmghOaz/

**Task Summary (30 tasks captured from API fetch):**

- 22 tasks COMPLETED, 8 tasks RUNNING, 0 FAILED
- Completed early-stage tasks include `SAMTOOLS_FAIDX`, `GTF_FILTER`, `FQ_LINT`, and `GTF2BED`
- Active work is mostly `TRIMGALORE` fan-out across samples
- `STAR_GENOMEGENERATE_IGENOMES` is defined in the run graph but was not yet observed as running/completed in the fetched task set

**Scheduling overhead:** Similar 5–6 min submit-to-start gaps.

## Comparison Notes

Both runs are concurrent nf-core/rnaseq executions on the same workspace with identical test data (GM12878_REP1, GM12878_REP2). Key differences:


| Metric                  | 1cF65l2PDvxNd5                       | 5VGC0gjEmghOaz             |
| ----------------------- | ------------------------------------ | -------------------------- |
| Submit time             | 17:51:26Z                            | 17:50:14Z                  |
| Machine types           | mix of m5d.large + c5d.large         | mostly c5d.large           |
| SAMTOOLS_FAIDX realtime | 28s                                  | 62s                        |
| GTF_FILTER realtime     | 58s                                  | 109s                       |
| FQ_LINT avg realtime    | ~605s                                | ~613s                      |
| Cost pattern            | Slightly higher per-task (m5d.large) | Lower per-task (c5d.large) |


The timing variance in short tasks (SAMTOOLS_FAIDX: 28s vs 62s) likely reflects spot instance variability and S3 staging latency rather than algorithmic differences. Both runs are still in progress — STAR genome generation and alignment phases are pending.

## Local Development History (git log)

Recent development has focused on the **benchmark report rendering pipeline**:

1. **Split architecture** (df2232e): Refactored monolithic benchmark report into 3 stages — normalize JSONL → aggregate → render
2. **Combined runtime charts** (18a64f4 → a49a9a4): Added combined task runtime visualisation with scheduling overhead, per-pipeline breakdowns, and ECharts integration
3. **CUR cost streaming** (b96ecfd): Optimised AWS CUR parquet processing with batch streaming
4. **Test colocation** (96b8b81): Moved benchmark tests to live alongside their modules

