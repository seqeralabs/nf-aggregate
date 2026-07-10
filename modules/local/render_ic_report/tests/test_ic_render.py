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


def test_ic_template_renders_machine_usage(tmp_path):
    data = {
        "ic_overview": {"n_runs": 1, "n_intelligent_compute": 1, "n_batch": 0, "cost_source": None},
        "run_summary": [{
            "run_id": "icRUN0000000001", "run_url": "", "run_name": "demo-ic-run",
            "pipeline": "example/demo-pipeline", "group": "ic", "compute_type": "intelligent_compute",
            "status": "SUCCEEDED", "compute_hours": 0.35, "memory_used_bytes": 1, "memory_used_gb": 11.49,
            "run_cost_platform": 0.1, "cost": None,
        }],
        "machine_usage": [{
            "run_id": "icRUN0000000001", "run_name": "demo-ic-run",
            "run_url": "https://cloud.example.test/orgs/myorg/workspaces/myworkspace/watch/icRUN0000000001",
            "compute_type": "intelligent_compute", "total_tasks": 3, "total_cpu_hours": 3.0,
            "machines": [
                {"machine_type": "t3.large", "task_count": 2, "task_pct": 66.7, "cpu_hours": 2.0, "color_idx": 0},
                {"machine_type": "unknown", "task_count": 1, "task_pct": 33.3, "cpu_hours": 1.0, "color_idx": 1},
            ],
        }],
    }
    data_path = tmp_path / "report_data_ic.json"
    data_path.write_text(json.dumps(data))
    out = tmp_path / "ic_report.html"

    render_report_from_json(report_data_path=data_path, output=out, template_path=IC_TEMPLATE)
    html = out.read_text()

    assert "Machine types per run" in html          # section heading
    assert "t3.large" in html                        # machine type in legend
    assert "unknown" in html                          # empty bucket label
    assert "width: 66.7%" in html or "width:66.7%" in html   # stacked-bar segment sized by share
    assert "cpu-h" in html                            # cpu-hours shown in legend


def test_ic_template_no_machine_section_when_absent(tmp_path):
    # machine_usage missing entirely -> section is simply skipped (no error)
    data = {
        "ic_overview": {"n_runs": 0, "n_intelligent_compute": 0, "n_batch": 0, "cost_source": None},
        "run_summary": [],
    }
    data_path = tmp_path / "report_data_ic.json"
    data_path.write_text(json.dumps(data))
    out = tmp_path / "ic_report.html"
    render_report_from_json(report_data_path=data_path, output=out, template_path=IC_TEMPLATE)
    assert "Machine types per run" not in out.read_text()
