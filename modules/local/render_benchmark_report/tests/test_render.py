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
    assert "Workflow status" in text
    assert "Workflow outcome" in text
    assert "Included in report" not in text
    assert "Included in downstream sections" not in text
    assert "Excluded from downstream sections" not in text
    assert "Benchmark overview" not in text
    assert 'id="benchmark-overview"' not in text
    assert 'id="overview-matrix"' not in text
    assert 'href="#benchmark-overview"' not in text
    assert "!r.report_included" in text
    assert "rgba(220, 53, 69, 0.14)" in text


def test_render_includes_combined_runtime_section(tmp_path, minimal_report_data):
    data = dict(minimal_report_data)
    data["combined_task_runtime"] = [
        {
            "pipeline": "rustqc",
            "group": "gpu",
            "panel_id": "rustqc::gpu",
            "total_runtime_ms": 180000,
            "scheduling_runtime_ms": 30000,
            "total_duration_ms": 210000,
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
        },
        {
            "pipeline": "nf-core/sarek",
            "group": "cpu",
            "panel_id": "nf-core/sarek::cpu",
            "total_runtime_ms": 300000,
            "scheduling_runtime_ms": 10000,
            "total_duration_ms": 310000,
            "total_tasks": 3,
            "unique_processes": 2,
            "segments": [
                {"process": "SAREK:MAIN", "runtime_ms": 200000, "pct": 66.67, "highlight": False},
                {"process": "SAREK:RSEQC", "runtime_ms": 100000, "pct": 33.33, "highlight": True},
            ],
            "legend": [
                {"process": "SAREK:MAIN", "runtime_ms": 200000, "pct": 66.67, "highlight": False},
                {"process": "SAREK:RSEQC", "runtime_ms": 100000, "pct": 33.33, "highlight": True},
            ],
            "highlight_totals": {"qc_runtime_ms": 100000, "other_runtime_ms": 200000},
        },
    ]
    out = tmp_path / "report.html"
    render_html(data, out)
    text = out.read_text()
    assert 'id="combined-task-runtime"' in text
    assert 'id="combined-runtime-panels"' in text
    assert "DATA.combined_task_runtime" in text
    assert "runtime-unified-chart" in text
    assert "border: none;" in text
    assert "maxTotalDurationMs" in text
    assert "const pipelineBreakdowns = rows.map((row) => {" in text
    assert "gridTop = 90 + (pipelineBreakdowns.length * breakdownLineHeight)" in text
    assert "labelText = `${line.label}:`;" in text
    assert "graphic: (function()" in text
    assert "runtime-comparison-table" in text
    assert "runtime-comparison-scroll" in text
    assert "comparisonTable.className = 'runtime-comparison-table';" in text
    assert "comparisonScroll.className = 'runtime-comparison-scroll';" in text
    assert "scheduling_runtime_ms" in text
    assert "total_duration_ms" in text
    assert "const yData = rows.map((row) => row.label);" in text
    assert "series.push({" in text
    assert "stack: `runtime-${rowIdx}`" in text
    assert "Combined Task Duration by Process" in text
    assert "comparing ${rows.length} configurations" in text
    assert "includes scheduling overhead" in text
    assert "chartEl.className = 'chart combined-runtime-chart';" not in text
    assert "panelEl.className = 'runtime-panel';" not in text
    assert "runtime-summary-row-head" not in text
    assert "summaryRowsEl.className = 'runtime-summary-rows';" not in text
    assert "rowSummaryEl.className = 'runtime-summary-row';" not in text
    assert "runtime-comparison-wrap" not in text
    assert "globalSchedulingMs" not in text
    assert "globalQcMs" not in text
    assert "globalOtherMs" not in text
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
            "scheduling_runtime_ms": 15000,
            "total_duration_ms": 195000,
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

    append_idx = text.find("container.appendChild(unifiedChartEl);")
    init_idx = text.find("const chart = echarts.init(unifiedChartEl, 'seqera');")
    assert append_idx != -1
    assert init_idx != -1
    assert append_idx < init_idx
    assert "window.requestAnimationFrame" in text
    assert "unifiedChartEl.getBoundingClientRect()" in text
    assert "initUnifiedRuntimeChart(true)" in text


def test_combined_runtime_fallback_without_duration_fields(tmp_path, minimal_report_data):
    data = dict(minimal_report_data)
    data["combined_task_runtime"] = [
        {
            "pipeline": "pipe",
            "group": "cpu",
            "panel_id": "pipe::cpu",
            "total_runtime_ms": 180000,
            "total_tasks": 2,
            "unique_processes": 2,
            "segments": [
                {"process": "PIPE:MAIN", "runtime_ms": 120000, "pct": 66.67, "highlight": False},
                {"process": "PIPE:QC", "runtime_ms": 60000, "pct": 33.33, "highlight": True},
            ],
            "legend": [
                {"process": "PIPE:MAIN", "runtime_ms": 120000, "pct": 66.67, "highlight": False},
                {"process": "PIPE:QC", "runtime_ms": 60000, "pct": 33.33, "highlight": True},
            ],
            "highlight_totals": {"qc_runtime_ms": 60000, "other_runtime_ms": 120000},
        }
    ]
    out = tmp_path / "report.html"
    render_html(data, out)
    text = out.read_text()
    assert "runtime-comparison-table" in text
    assert "panel.total_duration_ms || (totalRuntime + schedulingRuntime) || totalRuntime" in text
    assert "label: 'Scheduling'" in text
    assert "graphic: (function()" in text


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
