from typer.testing import CliRunner

from benchmark_report import app
from benchmark_report_normalize import normalize_jsonl


runner = CliRunner()


def _combined_output(result) -> str:
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    output = getattr(result, "output", "") or ""
    return stdout + stderr + output


def test_build_db_rejects_duckdb_output(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data"
    write_run_json(data_dir, [make_run(tasks=[flat_task()])])

    output = tmp_path / "benchmark.duckdb"
    result = runner.invoke(app, ["build-db", "--data-dir", str(data_dir), "--output", str(output)])

    assert result.exit_code == 1
    assert "no longer creates DuckDB files" in _combined_output(result)
    assert not output.exists()


def test_report_accepts_db_alias_for_jsonl_dir(tmp_path, make_run, flat_task, write_run_json):
    data_dir = tmp_path / "data"
    jsonl_dir = tmp_path / "jsonl_bundle"
    write_run_json(data_dir, [make_run(tasks=[flat_task()])])
    normalize_jsonl(data_dir, jsonl_dir)

    report_html = tmp_path / "report.html"
    report_data = tmp_path / "report_data.json"

    result = runner.invoke(
        app,
        [
            "report",
            "--db",
            str(jsonl_dir),
            "--output",
            str(report_html),
            "--data-output",
            str(report_data),
        ],
    )

    assert result.exit_code == 0
    assert "--db is deprecated" in _combined_output(result)
    assert report_html.exists()
    assert report_data.exists()


def test_report_db_file_shows_migration_error(tmp_path):
    db_file = tmp_path / "benchmark.duckdb"
    db_file.write_text("not-a-db")

    result = runner.invoke(app, ["report", "--db", str(db_file)])

    assert result.exit_code == 1
    assert "DuckDB report input is no longer supported" in _combined_output(result)
