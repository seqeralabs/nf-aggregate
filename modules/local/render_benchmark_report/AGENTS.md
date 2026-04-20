# render_benchmark_report

Purpose

- Render self-contained HTML from `report_data.json` plus branding assets.

Owns

- `RENDER_BENCHMARK_REPORT` in `main.nf`
- Module-local CLI entrypoint in `bin/benchmark_report.py`
- Module-local render logic in `bin/benchmark_report_render.py`
- Stage-scoped tests under `tests/`

Run directly

- `nextflow run modules/local/render_benchmark_report/main.nf -profile docker,arm --report_data_json <report_data.json> --brand_yml <brand.yml-or-NO_FILE> --logo_svg <logo.svg-or-NO_FILE>`
- The direct `nextflow run modules/local/...` path depends on the module-local `bin/benchmark_report.py` shim/CLI; keep that invocation shape working if you refactor the stage.

Inputs

- `report_data.json`
- optional `brand.yml`
- optional logo SVG

Outputs

- `benchmark_report.html`
- `versions.yml`

Invariants

- Rendering consumes precomputed report data only.
- No raw JSON normalization or report aggregation should happen here.
- Keep template input contract stable unless you also update the renderer tests and report template.

Edit guidance

- Prefer changing `report_data.json` upstream over adding data-massaging logic in the template.
- Branding/theme lookup should stay tolerant of missing optional assets.

Tests

- `pytest modules/local/render_benchmark_report/tests/test_render.py -q`
