import json

from benchmark_report_render import REPORT_TEMPLATE, load_brand, render_html, render_report_from_json


def test_template_loaded():
    assert "<!DOCTYPE html>" in REPORT_TEMPLATE
    assert "echarts" in REPORT_TEMPLATE


def test_render_html(tmp_path, minimal_report_data):
    out = tmp_path / "report.html"
    render_html(minimal_report_data, out)
    text = out.read_text()
    assert "Pipeline benchmarking report" in text
    assert "run1" in text


def test_render_includes_combined_runtime_section(tmp_path, minimal_report_data):
    data = dict(minimal_report_data)
    data["combined_task_runtime"] = [
        {
            "pipeline": "rustqc",
            "group": "gpu",
            "panel_id": "rustqc::gpu",
            "total_runtime_ms": 180000,
            "total_tasks": 2,
            "unique_processes": 2,
            "segments": [
                {"process": "RUSTQC:ALIGN", "runtime_ms": 120000, "pct": 66.67, "highlight": False},
                {"process": "RUSTQC:QUALIMAP", "runtime_ms": 60000, "pct": 33.33, "highlight": True},
            ],
            "legend": [
                {"process": "RUSTQC:ALIGN", "runtime_ms": 120000, "pct": 66.67, "highlight": False},
                {"process": "RUSTQC:QUALIMAP", "runtime_ms": 60000, "pct": 33.33, "highlight": True},
            ],
            "highlight_totals": {"qc_runtime_ms": 60000, "other_runtime_ms": 120000},
        }
    ]
    out = tmp_path / "report.html"
    render_html(data, out)
    text = out.read_text()
    assert 'id="combined-task-runtime"' in text
    assert 'id="combined-runtime-panels"' in text
    assert "DATA.combined_task_runtime" in text
    assert "combined-runtime-chart" in text
    assert "runtime-detail-table" in text
    assert "runtime-summary-pill" in text
    assert "table.className = 'runtime-detail-table';" in text
    assert "buildChipGraphic" not in text
    assert "selectedMode: false" not in text


def test_render_backwards_compatible_without_combined_runtime_key(tmp_path, minimal_report_data):
    data = dict(minimal_report_data)
    data.pop("combined_task_runtime", None)
    out = tmp_path / "report.html"
    render_html(data, out)
    text = out.read_text()
    assert "Combined task runtime" in text
    assert "combined-runtime-panels" in text
    assert "const panels = DATA.combined_task_runtime || [];" in text


def test_combined_runtime_chart_init_after_attach(tmp_path, minimal_report_data):
    data = dict(minimal_report_data)
    data["combined_task_runtime"] = [
        {
            "pipeline": "rustqc",
            "group": "gpu",
            "panel_id": "rustqc::gpu",
            "total_runtime_ms": 180000,
            "total_tasks": 2,
            "unique_processes": 2,
            "segments": [
                {"process": "RUSTQC:ALIGN", "runtime_ms": 120000, "pct": 66.67, "highlight": False},
                {"process": "RUSTQC:QUALIMAP", "runtime_ms": 60000, "pct": 33.33, "highlight": True},
            ],
            "legend": [
                {"process": "RUSTQC:ALIGN", "runtime_ms": 120000, "pct": 66.67, "highlight": False},
                {"process": "RUSTQC:QUALIMAP", "runtime_ms": 60000, "pct": 33.33, "highlight": True},
            ],
            "highlight_totals": {"qc_runtime_ms": 60000, "other_runtime_ms": 120000},
        }
    ]
    out = tmp_path / "report.html"
    render_html(data, out)
    text = out.read_text()

    append_idx = text.find("container.appendChild(panelEl);")
    init_idx = text.find("const chart = echarts.init(chartEl, 'seqera');")
    assert append_idx != -1
    assert init_idx != -1
    assert append_idx < init_idx
    assert "window.requestAnimationFrame" in text
    assert "chartEl.getBoundingClientRect()" in text
    assert "initCombinedRuntimeChart(true)" in text


def test_render_report_from_json(tmp_path, minimal_report_data):
    data_path = tmp_path / "report_data.json"
    data_path.write_text(json.dumps(minimal_report_data))
    out = tmp_path / "report.html"
    render_report_from_json(data_path, out)
    assert out.is_file()


def test_load_brand_override(tmp_path):
    brand_path = tmp_path / "brand.yml"
    brand_path.write_text("""
colors:
  green_palette:
    deep_green:
      hex: '#112233'
""")
    brand = load_brand(brand_path)
    assert brand["accent"] == "#112233"
