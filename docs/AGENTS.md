# docs/ — Design Documentation

## DESIGN.md

Full v2 architecture document. Covers:

- API-first data fetching (nf-boost `request()` replaces tower-cli)
- Legacy v1 DuckDB design history (now superseded by JSONL → report_data.json → HTML)
- eCharts HTML report structure (current renderer contract)
- Input CSV format (id, workspace, group columns)
- Migration plan from v1 → v2

Read this first when onboarding to the project.
