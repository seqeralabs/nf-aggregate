# GCP cost attribution design

- Status: accepted
- Date: 2026-09-18
- Scope: Google Cloud only. Azure is explicitly out of scope — see "Why not Azure".

## Summary

Teach the Intelligent Compute report to read real per-run costs from a Google Cloud
Billing BigQuery export, so a Google Batch run and a Seqera scheduler (SIC) run can be
compared on money as well as on time and resources.

The whole change lands *behind* `costs.jsonl`. That file is the seam between cost
extraction and everything that consumes cost: `_load_cost_pools`
(`bin/benchmark_report_aggregate.py:160`) joins it on `run_id`, and the IC aggregator and
template read only its output. A GCP source that emits the same row schema therefore
needs no downstream change at all.

## Findings from the real export

Measured against `tower-cloud-testing.all_billing_data.gcp_billing_export_v1_01F197_9D74B5_BC674D`
on 2026-09-18 (30 days of data, 368,714 rows, $414 MB).

### The export is the *standard* one, and it expires

The table has no `resource` field, so there is no per-VM instance id — only the
`labels` / `system_labels` repeated structs. `timePartitioning.expirationMs` is
`2592000000`, so **partitions expire after 30 days**. Any report covering older runs needs
a second, unexpired sink. The report must not silently present a truncated window as
complete.

### Two engines, two different label sets, no overlap

| Population | Rows | Cost | Run identifier |
| --- | ---: | ---: | --- |
| Scheduler (SIC) | 51,115 | $133.67 | `seqera-io-platform-workflowid`, `nextflow-io-sessionid` |
| Google Batch | 303,227 | $49.78 | **none** — only `batch-job-id` |
| Untagged | 7,921 | $85.31 | — (E2 dev VMs, unattached disks, external IPs) |

The scheduler tags the VMs it provisions itself (`managed-by: seqera-sched`,
`seqera-sched-cluster-id`), carrying the full `nextflow-io-*` / `seqera-io-platform-*` set.
This is *not* Nextflow's `ResourceLabelPolicy.GOOGLE`, which sanitises with underscores;
the scheduler uses dashes. So the GCP alias list is its own thing, never a transform of
the AWS one.

Google Batch rows carry `batch-job-id` only. Nextflow's job id is
`"nf-${task.hashLog.replace('/','')}-${currentTimeMillis()}"`
(`GoogleBatchTaskHandler.groovy:136`), e.g. `nf-5dbefa9a-1789649298737` — the embedded
8-hex string is exactly the task-hash grain `_normalize_cost_rows` already keys on. Batch
also stamps that label on every VM, disk and GPU it creates, so disks are attributed too.

`unique-run-id` / `pipeline-session-id` (the AWS Batch blog template, translated) exist on
177 rows totalling **$0.007** — configured once, essentially unused.

### Label values are lowercased

Workflow ids arrive as `nnjl9fvczoruf`, `5an9reqdq1wnnr` — 13–14 characters, all lowercase,
against mixed-case Platform ids. The join must be case-insensitive.

### Spot is measurable on both engines

`REGEXP_CONTAINS(sku.description, r"(?i)spot|preemptible")` splits cleanly:

| Engine | Spot | Non-spot |
| --- | ---: | ---: |
| Scheduler | $79.58 | $54.08 |
| Google Batch | $34.67 | $15.10 |

So the AWS `_purchase_option_split` IC-only gate does **not** carry over. On GCP the
purchase option is a property of the SKU, available for both engines.

The AWS *usage-type* gate does carry over, though, and for the same reason: the split must
count machine rental only. Disks and networking are labelled to the same run (~$20 of disk
across both engines in the export) and are not machine rental, so `spot_cost` and
`ondemand_cost` are summed over SKUs matching `instance (core|ram)` only. As on AWS,
`spot_cost + ondemand_cost < unblended_cost` is therefore expected, never a bug.

### `system_labels` carries the machine spec

`compute.googleapis.com/machine_spec` is present on 70,582 Compute Engine rows with 105
distinct values, alongside `cores` and `memory`. Not consumed by this design, but it means
the machine-type distribution could later be sourced from billing rather than from task
records.

## Design decisions

### D1 — One cost basis, no split/unused

GCP has no ECS split-cost-allocation analogue, so the double-count that forced
`unblended_cost` and `split_cost` apart on AWS cannot occur. A GCP cost row sets
`unblended_cost = cost = used_cost = SUM(billing.cost)` and leaves `split_cost`,
`unused_cost` and `split_cost_present` at zero.

The consequence is a *simplification* the report gets for free: on GCP both engines report
on the same VM-charge basis, so they are directly comparable and `comparable_cost` is
unnecessary. The IC template renders a blank `comparable_cost` cell, which it already does
for IC-on-VM runs, and which already means "this basis does not exist for this run".

### D2 — Gross cost, credits excluded

`cost` is taken gross. Credits are not subtracted.

The rationale is comparability: a negotiated discount that happens to apply to one engine
and not the other would taint a Batch-vs-SIC comparison, and the report's job is to compare
engines, not to reproduce an invoice.

**Known consequence, accepted.** The only credit type present on run-labelled rows in the
real export is `SUSTAINED_USAGE_DISCOUNT`: −$5.365 on the scheduler (4.0% of its spend) and
−$0.094 on Google Batch (0.19%). SUD is automatic rather than negotiated, and it accrues to
long-running on-demand VMs — structurally what the scheduler does and Batch does not. So
excluding it costs the scheduler about 4% in the comparison. This is a deliberate trade of
a small known bias for freedom from an unbounded unknown one. The credit filter is
isolated in one function so the decision can be revisited without touching anything else.

### D3 — Run id is remapped to its canonical case in the extractor

Downstream joins on an exact `run_id` string (`_load_cost_pools`), and the report's run ids
come from the Platform API in mixed case. Rather than make every consumer
case-insensitive — a change to shared AWS code paths for a GCP-only problem — the GCP
extractor receives the set of known run ids and maps each lowercased billing value back to
its canonical spelling. Unknown ids pass through as-is, so an id absent from the samplesheet
is still visible as unattributed spend rather than silently renamed.

### D4 — Run id stays a required join key; the task hash is a diagnostic, not a fallback

Rows with no run id are dropped, exactly as on AWS. Attributing Google Batch spend by task
hash alone is unsafe: Nextflow hashes are content-addressed, so two nightly runs of the
same pipeline on the same inputs share hashes and would cross-attribute.

But dropping them silently is worse, because today that is *all* Google Batch spend. The
extractor therefore counts what it dropped and reports it: rows that carry a `batch-job-id`
but no run id are summed and surfaced as `unattributed_gcp_batch_cost` so the operator sees
"$49.78 of Google Batch spend carries no run label — set `resourceLabels`" instead of a
confident zero.

### D5 — Aggregation is pushed into BigQuery

The extractor issues one `GROUP BY` query and receives at most a few thousand rows. It
never downloads the export. This is strictly better than the AWS path, which scans
multi-GB parquet inside the task.

## Row schema produced

Identical to the AWS `costs.jsonl` contract, so nothing downstream changes:

| Field | GCP value |
| --- | --- |
| `run_id` | canonical-cased Platform workflow id |
| `session_id` | `nextflow-io-sessionid` / `pipeline-session-id`, else `""` |
| `process` | `""` — no process label exists on GCP |
| `hash` | 8-hex task hash from `batch-job-id`, else `""` |
| `unblended_cost` | `SUM(cost)`, gross |
| `split_cost`, `unused_cost` | `0.0` |
| `split_cost_present` | `0` |
| `spot_cost` | `SUM(cost)` over *machine* SKUs where the SKU is spot |
| `ondemand_cost` | `SUM(cost)` over *machine* SKUs where it is not |
| `cost`, `used_cost` | `= unblended_cost` |

## Why not Azure

Nextflow writes `resourceLabels` into Azure Batch **pool metadata**
(`AzBatchService.groovy:759`, applied at `:941`), and Microsoft states tags cannot be
associated with Batch pools. Pool metadata is a Batch data-plane concept that never reaches
Cost Management, so there is no path from `resourceLabels` to an Azure cost row.
Attribution there is pool-grain at best, via a `nf-pool-<hash>-<vmType>` id that must be
mapped back through the task's queue.

Given the scheduler demonstrably tags its own VMs on GCP, the **Azure Cloud** compute
environment is the likelier Azure path — the same sched-side mechanism should apply ARM
tags. That needs verification against a real Azure export before any Azure design work, and
is not attempted here.

## Labels a pipeline needs

- **SIC / Cloud compute environments: nothing.** The scheduler tags the machines itself.
- **Google Batch: a run id and session id**, via `process.resourceLabels` or Platform
  dynamic resource labels (`${workflowId}`, `${sessionId}`) set once at workspace level.
  The task hash comes free via `batch-job-id`.
- `tower.autoLabels` (Nextflow PR #7528, merged 2026-09-16) would standardise this but
  lands in 26.09.0-edge; this repo requires ≥25.10.0, so it is not yet an option.
- Google constraints when writing labels: lowercase keys and values, 63 characters, 61
  custom labels per VM.

Until Google Batch runs carry a run id, the Batch side of any Batch-vs-SIC comparison is
not trustworthy. D4's diagnostic exists to make that visible rather than silent.
