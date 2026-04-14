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
