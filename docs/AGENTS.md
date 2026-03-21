# docs/ — Design Documentation

## DESIGN.md

Full v2 architecture document. Covers:

- API-first data fetching (nf-boost `request()` replaces tower-cli)
- DuckDB in-memory database schema (runs, tasks, metrics, costs tables)
- eCharts HTML report structure (5 sections matching old Quarto report)
- Input CSV format (id, workspace, group columns)
- Migration plan from v1 → v2

Read this first when onboarding to the project.
