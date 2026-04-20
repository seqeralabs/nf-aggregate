# modules/local/ — Nextflow Processes

Each module should keep one clear responsibility and its own terse `AGENTS.md`.

| Module                             | Status     | Purpose                                       |
| ---------------------------------- | ---------- | --------------------------------------------- |
| `normalize_benchmark_jsonl/`       | **active** | Raw run JSON (+ optional CUR parquet) → JSONL |
| `aggregate_benchmark_report_data/` | **active** | JSONL bundle → `report_data.json`             |
| `render_benchmark_report/`         | **active** | `report_data.json` + branding → HTML          |
| `extract_tarball/`                 | active     | Extract run-data tarballs for external runs   |

Testing

- Keep stage-specific pytest tests beside the module under `tests/`.
- Keep pipeline routing/integration scenarios under top-level `tests/`.
