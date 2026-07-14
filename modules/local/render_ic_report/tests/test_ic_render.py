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
    "started_at": "2026-07-12T22:29:38Z", "date_short": "2026-07-12",
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
    # start-time column present + timestamp carried into the blob
    assert 'title: "Started"' in html
    assert '"started_at": "2026-07-12T22:29:38Z"' in html
    # table height scales with rows (grows to content, caps + scrolls only when large)
    assert 'maxHeight' in html
    assert "pagination" not in html


def test_ic_report_renders_machine_chart_section(tmp_path):
    html = _render(tmp_path, {
        "ic_overview": {"n_runs": 1, "n_intelligent_compute": 1, "n_batch": 0, "cost_source": None},
        "run_summary": [_RUN],
        "machine_usage": [{
            "run_id": "icRUN0000000001", "run_name": "demo-ic-run",
            "run_url": "https://cloud.example.test/orgs/myorg/workspaces/myworkspace/watch/icRUN0000000001",
            "compute_type": "intelligent_compute", "started_at": "2026-07-12T22:29:38Z", "date_short": "2026-07-12",
            "total_tasks": 3, "total_cpu_hours": 3.0,
            "machines": [
                {"machine_type": "t3.large", "task_count": 2, "task_pct": 66.7, "cpu_hours": 2.0, "color_idx": 0},
                {"machine_type": "unknown", "task_count": 1, "task_pct": 33.3, "cpu_hours": 1.0, "color_idx": 1},
            ],
        }],
    })
    assert 'id="performance"' in html               # Performance section (Jinja-guarded on machine_usage)
    assert "Machine-type distribution" in html      # section description
    assert 'id="machine-facets"' in html            # faceted ECharts mount point (one chart per engine)
    assert 'id="metric-toggle"' in html             # Tasks / CPU-hours toggle
    assert '"compute_type": "intelligent_compute"' in html  # facet key in the blob
    assert '"machine_type": "t3.large"' in html     # machine data in the blob feeding the chart
    assert '"machine_type": "unknown"' in html
    # start date is available to the chart (compact y-axis label via dateById) and in the blob
    assert "dateById" in html
    assert '"date_short": "2026-07-12"' in html


def test_ic_report_no_machine_section_when_absent(tmp_path):
    html = _render(tmp_path, {
        "ic_overview": {"n_runs": 0, "n_intelligent_compute": 0, "n_batch": 0, "cost_source": None},
        "run_summary": [],
    })
    assert 'id="machine-facets"' not in html        # no faceted charts without machine data
    assert "No machine-type data available." in html  # empty-state placeholder instead
    # the table + engines are always present
    assert 'id="run-table"' in html
    # no cost report -> Performance stays above Cost (no promotion)
    assert 'class="content cost-first"' not in html
    assert 'class="content"' in html
    assert html.index('href="#performance"') < html.index('href="#cost"')


def test_ic_report_renders_cost_section_and_sidebar(tmp_path):
    """The Cost section + left-sidebar navigation are always present; cost charts are
    built client-side from run_summary, so the section is a mount point + the embedded blob."""
    ic = dict(_RUN, cost=0.42)
    batch = dict(
        _RUN, run_id="btchRUN00000001", run_name="demo-batch-run", group="batch",
        compute_type="batch", started_at="2026-07-01T10:00:00Z", date_short="2026-07-01",
        cost=0.90,
    )
    html = _render(tmp_path, {
        "ic_overview": {"n_runs": 2, "n_intelligent_compute": 1, "n_batch": 1, "cost_source": "aws_cur"},
        "run_summary": [ic, batch],
        "machine_usage": [],
    })
    # left sidebar navigation with the three topics
    assert 'class="sidebar"' in html
    for label in ("Overview", "Performance", "Cost"):
        assert ">" + label + "<" in html
    # cost section + client-side mount point + savings/hero machinery
    assert 'id="cost"' in html
    assert 'id="cost-facets"' in html
    assert "hero-signature" in html
    # three switchable cost views: over time / by run / by instance (per-process removed —
    # a cpu-hour allocation, not a faithful CUR attribution)
    assert 'id="cost-view-toggle"' in html
    assert 'data-view="run"' in html and 'data-view="instance"' in html
    assert 'data-view="process"' not in html
    assert 'id="cost-run-facets"' in html
    assert 'id="cost-process-facets"' not in html
    assert 'id="cost-instance-facets"' in html
    # overview: pipeline-name pills + cost-split-by-engine mount points (filled client-side)
    assert 'id="pipeline-pills"' in html
    assert 'id="cost-split"' in html
    # both engines' real CUR costs are carried into the blob that feeds the cost chart + split
    assert '"cost": 0.42' in html
    assert '"cost": 0.9' in html
    # a cost report promotes Cost above Performance (layout class + nav order flipped)
    assert 'class="content cost-first"' in html
    assert html.index('href="#cost"') < html.index('href="#performance"')
    # timing columns present; meaningful groups (ic/batch) -> Group column shown
    assert '"wall_time_ms"' in html
    assert '"total_run_time_ms"' in html
    assert '"total_staging_time_ms"' in html
    assert 'title: "Group"' in html


def test_ic_report_hides_group_column_when_undefined(tmp_path):
    """No group in the samplesheet -> group defaults to 'default'/'' -> Group column dropped."""
    runs = [dict(_RUN, group="default"), dict(_RUN, run_id="icRUN0000000002", group="")]
    html = _render(tmp_path, {
        "ic_overview": {"n_runs": 2, "n_intelligent_compute": 2, "n_batch": 0, "cost_source": None},
        "run_summary": runs, "machine_usage": [],
    })
    assert 'title: "Group"' not in html
    assert '"wall_time_ms"' in html              # timing columns still present
