import json
from pathlib import Path

from benchmark_report_render import render_report_from_json

IC_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "bin" / "benchmark_report_ic_template.html"
)

_RUN = {
    "run_id": "icRUN0000000001",
    "run_url": "https://cloud.example.test/orgs/myorg/workspaces/myworkspace/watch/icRUN0000000001",
    "run_name": "demo-ic-run", "pipeline": "example/demo-pipeline", "group": "ic",
    "compute_type": "intelligent_compute", "status": "SUCCEEDED",
    "compute_hours": 4.0, "memory_used_bytes": 12339093504, "memory_used_gb": 11.49,
    "run_cost_platform": 0.0053921835, "cost": None,
}


def _render(tmp_path, data):
    data_path = tmp_path / "report_data_ic.json"
    data_path.write_text(json.dumps(data))
    out = tmp_path / "ic_report.html"
    render_report_from_json(report_data_path=data_path, output=out, template_path=IC_TEMPLATE)
    return out.read_text()


def test_ic_report_is_interactive_and_embeds_data(tmp_path):
    html = _render(tmp_path, {
        "ic_overview": {"n_runs": 1, "n_intelligent_compute": 1, "n_batch": 0, "cost_source": None},
        "run_summary": [_RUN],
        "machine_usage": [],
    })
    # interactive engines loaded
    assert "tabulator" in html.lower()
    assert "echarts" in html.lower()
    # data embedded as a client-side blob (Tabulator/ECharts render from it)
    assert "const DATA =" in html
    assert '"run_id": "icRUN0000000001"' in html
    assert "watch/icRUN0000000001" in html          # run_url survives into the blob for the link formatter
    # table container + searchable input + compute-type badge formatter
    assert 'id="run-table"' in html
    assert 'id="run-search"' in html
    assert "Intelligent Compute" in html
    # overview tiles still server-rendered
    assert ">1</div>" in html


def test_ic_report_renders_machine_chart_section(tmp_path):
    html = _render(tmp_path, {
        "ic_overview": {"n_runs": 1, "n_intelligent_compute": 1, "n_batch": 0, "cost_source": None},
        "run_summary": [_RUN],
        "machine_usage": [{
            "run_id": "icRUN0000000001", "run_name": "demo-ic-run",
            "run_url": "https://cloud.example.test/orgs/myorg/workspaces/myworkspace/watch/icRUN0000000001",
            "compute_type": "intelligent_compute", "total_tasks": 3, "total_cpu_hours": 3.0,
            "machines": [
                {"machine_type": "t3.large", "task_count": 2, "task_pct": 66.7, "cpu_hours": 2.0, "color_idx": 0},
                {"machine_type": "unknown", "task_count": 1, "task_pct": 33.3, "cpu_hours": 1.0, "color_idx": 1},
            ],
        }],
    })
    assert "Machine types per run" in html         # section heading (Jinja-guarded on machine_usage)
    assert 'id="machine-chart"' in html            # ECharts mount point
    assert 'id="metric-toggle"' in html            # Tasks / CPU-hours toggle
    assert '"machine_type": "t3.large"' in html    # machine data in the blob feeding the chart
    assert '"machine_type": "unknown"' in html


def test_ic_report_no_machine_section_when_absent(tmp_path):
    html = _render(tmp_path, {
        "ic_overview": {"n_runs": 0, "n_intelligent_compute": 0, "n_batch": 0, "cost_source": None},
        "run_summary": [],
    })
    assert "Machine types per run" not in html
    # the table + engines are always present
    assert 'id="run-table"' in html
