---
name: prepare-benchmark-input-csv
description: >
  Prepare correct nf-aggregate input CSV files for API runs, external tarballs,
  external directories, or mixed-source benchmarks. Use when comparing live
  Seqera runs against exported logs or building reproducible benchmark fixtures.
---

# Prepare benchmark input CSV

Use this skill when the user needs the right `--input` CSV for nf-aggregate.

## Supported row shapes

### API rows

For live Seqera Platform runs:

```csv
id,workspace
ULVYH4G9KM9sP,seqeralabs/showcase
5HieFbNIsw59ul,seqeralabs/showcase
```

### Grouped API rows

When comparing cohorts:

```csv
id,workspace,group
3VcLMAI8wyy0Ld,community/showcase,group1
4VLRs7nuqbAhDy,community/showcase,group2
```

### External tarball rows

For pre-exported run dumps:

```csv
id,workspace,group,logs
15dvxY1LnZYrYe,external,g5,logs/15dvxY1LnZYrYe.tar.gz
5ymDk0hmgqv4L4,external,cpu,logs/5ymDk0hmgqv4L4.tar.gz
```

### Mixed live + external rows

```csv
id,workspace,group,logs
3VcLMAI8wyy0Ld,community/showcase,live,
1JI5B1avuj3o58,external,external,/path/to/run_dump.tar.gz
```

## Column meanings

- `id` — Seqera run ID or a stable identifier for the external row
- `workspace` — `org/workspace` for live API rows, `external` for tarball/dir rows
- `group` — optional comparison group label used in report output
- `logs` — required for `external` rows; path to tarball or extracted directory
- `platform` — optional per-row API endpoint override
- `token_env` — optional per-row bearer-token env var name

## Decision rules

- Use `workspace=external` only for rows backed by local log artifacts.
- Use `logs` only for external rows.
- Use `group` whenever the user wants side-by-side comparisons in the report.
- Keep live and external rows in the same CSV when comparing different environments.

## Repo-specific notes

- Test fixtures live under `workflows/nf_aggregate/assets/`.
- `test_benchmark.csv` demonstrates tarball-backed benchmark rows.
- `test_run_ids.csv` demonstrates API-backed rows.
- Mixed-source support is a first-class workflow pattern in this repo.

## Validation checklist

Before running the pipeline:

- every live row has a valid `org/workspace`
- every external row has a readable `logs` path
- group labels are intentional and consistent
- `--generate_benchmark_report` is enabled if live API rows should produce report output
