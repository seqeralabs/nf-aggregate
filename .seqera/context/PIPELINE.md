# PIPELINE.md — seqeralabs/nf-aggregate

## Overview

**nf-aggregate** aggregates task-level metrics from Seqera Platform pipeline runs and produces benchmark HTML reports. It fetches run data via the Platform API (or from pre-exported tarballs/directories), normalises it to JSONL, aggregates statistics, and renders a branded interactive HTML report with ECharts visualisations.

- **Repository:** [https://github.com/seqeralabs/nf-aggregate](https://github.com/seqeralabs/nf-aggregate)
- **Latest released version:** 0.7.0 (2025-05-05)
- **Current branch:** `edmundmiller/seqera-context` (active development)
- **Plugins:** `nf-core-utils@0.4.0` (Conda checks, params dump, software version helpers), `nf-schema@2.3.0` (param validation, samplesheet parsing)
- **Required env:** `TOWER_ACCESS_TOKEN` for API-mode runs

## Architecture

```
Input CSV (id, workspace, group, logs, platform, token_env)
  │
  ├─ branch: api  →  SeqeraApi.fetchRunData() [Groovy, in-process]
  │                    └── JSON file per run
  ├─ branch: external (tarball) → EXTRACT_TARBALL
  │                    └── JSON files from tar.gz
  └─ branch: external (dir) → direct JSON collection
         │
         ▼
     ch_data_dir (all JSON files merged)
         │
         ▼
     NORMALIZE_BENCHMARK_JSONL
         │  raw JSON → jsonl_bundle/ (runs.jsonl, tasks.jsonl, metrics.jsonl)
         ▼
     AGGREGATE_BENCHMARK_REPORT_DATA
         │  jsonl_bundle/ → report_data.json
         ▼
     RENDER_BENCHMARK_REPORT
         │  report_data.json + brand.yml + logo.svg → benchmark_report.html
         ▼
     results/benchmark_report/
```

## Entry Points

| File                             | Role                                                                             |
| -------------------------------- | -------------------------------------------------------------------------------- |
| `main.nf`                        | Pipeline entry — validates params, parses samplesheet, delegates to NF_AGGREGATE |
| `workflows/nf_aggregate/main.nf` | Core workflow — branching, API fetch, process chaining                           |
| `lib/SeqeraApi.groovy`           | Groovy API client — paginated task fetch, workspace resolution                   |
| `bin/benchmark_report.py`        | Typer CLI — normalize-jsonl, aggregate-report-data, render-html, fetch           |

## Processes (4 local modules)

| Process                           | Container                       | Input                                       | Output                      |
| --------------------------------- | ------------------------------- | ------------------------------------------- | --------------------------- |
| `EXTRACT_TARBALL`                 | ubuntu:22.04                    | `(meta, tarball)`                           | `(meta, dir)` of JSON files |
| `NORMALIZE_BENCHMARK_JSONL`       | wave python/duckdb/jinja2/typer | `data_dir`, `cur_parquet`, `cur_label_map` | `jsonl_bundle/`             |
| `AGGREGATE_BENCHMARK_REPORT_DATA` | wave python/duckdb/jinja2/typer | `jsonl_bundle/`                             | `report_data.json`          |
| `RENDER_BENCHMARK_REPORT`         | wave python/duckdb/jinja2/typer | `report_data.json`, `brand.yml`, `logo.svg` | `benchmark_report.html`     |

## Key Parameters

| Parameter                   | Default                       | Purpose                                     |
| --------------------------- | ----------------------------- | ------------------------------------------- |
| `input`                     | required                      | CSV samplesheet of run IDs / external paths |
| `outdir`                    | `results`                     | Output directory                            |
| `generate_benchmark_report` | `false`                       | Enable the benchmark pipeline               |
| `benchmark_aws_cur_report`  | `null`                        | AWS CUR parquet for cost analysis           |
| `benchmark_aws_cur_label_map` | `null`                      | Optional YAML alias map for CUR resource labels |
| `seqera_api_endpoint`       | `https://api.cloud.seqera.io` | Platform API base URL                       |
| `java_truststore_path`      | `null`                        | Custom Java truststore for private certs    |
| `java_truststore_password`  | `null`                        | Truststore password                         |

## Input Schema

CSV with columns: `id` (required), `workspace` (required, `org/name` or `external`), `group` (optional), `logs` (path to tarball/dir for external), `platform` (per-row API URL override), `token_env` (per-row env var name for bearer token).

## Publish Structure

```
results/
├── benchmark_report/
│   ├── benchmark_report.html
│   ├── report_data.json
│   └── jsonl_bundle/
│       ├── runs.jsonl
│       ├── tasks.jsonl
│       └── metrics.jsonl
└── pipeline_info/
    └── collated_software_versions.yml
```

## Data Flow Details

1. **API path:** `SeqeraApi.fetchRunData()` runs in Groovy process memory (not a Nextflow task). It resolves workspace name → ID, then fetches `/workflow/{id}`, `/workflow/{id}/metrics`, `/workflow/{id}/tasks` (paginated), and `/workflow/{id}/progress`. Results are written to temp JSON files.
2. **External path:** EXTRACT_TARBALL unpacks `.tar.gz` into a directory of JSON files. Directories are used directly.
3. **All JSON files** are collected into a single temp directory and passed to the 3-stage Python pipeline: normalize → aggregate → render.
4. The Python stages are separate Nextflow processes sharing one Wave container image (`python_duckdb_jinja2_typer_pruned`).
5. JSONL is the handoff format — streaming-friendly for large run datasets and Fusion FS compatible.
