#!/usr/bin/env python3
"""Benchmark report HTML rendering helpers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from jinja2 import BaseLoader, Environment


def load_brand(brand_path: Path | None = None) -> dict[str, Any]:
    defaults = {
        "accent": "#087F68",
        "accent_light": "#31C9AC",
        "accent_surface": "#E2F7F3",
        "heading": "#201637",
        "border": "#CFD0D1",
        "neutral": "#F7F7F7",
        "white": "#ffffff",
        "palette": [
            "#065647",
            "#45a1bf",
            "#201637",
            "#f4b548",
            "#31C9AC",
            "#8f3d56",
            "#85c7c6",
            "#a5cdee",
            "#d2c6ac",
            "#46a485",
        ],
    }

    if brand_path and brand_path.exists():
        with brand_path.open() as f:
            raw = yaml.safe_load(f) or {}
        colors = raw.get("colors", {})
        gp = colors.get("green_palette", {})
        ns = colors.get("neutrals", {})

        if h := gp.get("deep_green", {}).get("hex"):
            defaults["accent"] = h
        if h := gp.get("seqera_green", {}).get("hex"):
            defaults["accent_light"] = h
        if h := gp.get("soft_green", {}).get("hex"):
            defaults["accent_surface"] = h
        if h := ns.get("brand_dark", {}).get("hex"):
            defaults["heading"] = h
        if h := ns.get("border_layout", {}).get("hex"):
            defaults["border"] = h
        if h := ns.get("neutral", {}).get("hex"):
            defaults["neutral"] = h

    return defaults


def _load_report_template() -> str:
    template_path = Path(__file__).resolve().parent / "benchmark_report_template.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Report template not found at {template_path}")
    return template_path.read_text()


def load_echarts_theme(theme_path: Path | None = None) -> str:
    candidates = [
        theme_path,
        Path(__file__).resolve().parent.parent / "assets" / "seqera-echarts-theme.json",
        Path("assets/seqera-echarts-theme.json"),
    ]
    for p in candidates:
        if p and p.exists():
            return p.read_text()
    return "{}"


def render_html(
    data: dict[str, Any],
    output_path: Path,
    brand: dict[str, Any] | None = None,
    logo_svg: str | None = None,
    theme_path: Path | None = None,
) -> None:
    brand = brand or load_brand()
    template = Environment(loader=BaseLoader()).from_string(REPORT_TEMPLATE)
    run_metrics = data.get("run_metrics") or []
    has_performance_gains = any((row or {}).get("vmCpuH") for row in run_metrics)
    html = template.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data_json=json.dumps(data, default=str),
        echarts_theme_json=load_echarts_theme(theme_path),
        brand_accent=brand["accent"],
        brand_accent_light=brand["accent_light"],
        brand_accent_surface=brand["accent_surface"],
        brand_heading=brand["heading"],
        brand_border=brand["border"],
        brand_neutral=brand["neutral"],
        brand_white=brand["white"],
        brand_palette=brand["palette"],
        logo_svg=logo_svg or "",
        has_performance_gains=has_performance_gains,
        **data,
    )
    output_path.write_text(html)


def render_report_from_json(
    report_data_path: Path,
    output: Path,
    brand_path: Path | None = None,
    logo_path: Path | None = None,
) -> None:
    data = json.loads(report_data_path.read_text())
    brand = load_brand(brand_path)
    logo_svg = logo_path.read_text() if logo_path and logo_path.exists() else None
    render_html(data, output_path=output, brand=brand, logo_svg=logo_svg)


REPORT_TEMPLATE = _load_report_template()
_TEMPLATE_LOADED = True
