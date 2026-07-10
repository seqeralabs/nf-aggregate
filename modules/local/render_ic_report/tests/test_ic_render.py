import json
from pathlib import Path

from benchmark_report_render import render_report_from_json

IC_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "bin" / "benchmark_report_ic_template.html"
)


def test_ic_template_renders_table(tmp_path):
    data = {
        "ic_overview": {"n_runs": 1, "n_intelligent_compute": 1, "n_batch": 0, "cost_source": None},
        "run_summary": [{
            "run_id": "icRUN0000000001",
            "run_url": "https://cloud.example.test/orgs/myorg/workspaces/myworkspace/watch/icRUN0000000001",
            "run_name": "demo-ic-run", "pipeline": "example/demo-pipeline", "group": "ic",
            "compute_type": "intelligent_compute", "status": "SUCCEEDED",
            "compute_hours": 0.35, "memory_used_bytes": 12339093504, "memory_used_gb": 11.49,
            "run_cost_platform": 0.0053921835, "cost": None,
        }],
    }
    data_path = tmp_path / "report_data_ic.json"
    data_path.write_text(json.dumps(data))
    out = tmp_path / "ic_report.html"

    render_report_from_json(report_data_path=data_path, output=out, template_path=IC_TEMPLATE)
    html = out.read_text()

    assert 'href="https://cloud.example.test/orgs/myorg/workspaces/myworkspace/watch/icRUN0000000001"' in html
    assert "icRUN0000000001" in html
    assert "0.35" in html
    assert "11.49" in html
    assert "&mdash;" in html
    assert "Intelligent Compute" in html
