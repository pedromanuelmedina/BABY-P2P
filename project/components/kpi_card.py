"""KPI Cards — metricas visuales con sparkline + delta + tooltip."""

import html

import streamlit as st

from .sparkline import sparkline_html


def _build_kpi_card_html(label: str, value: str, delta: float = 0.0,
                         delta_unit: str = "%", sparkline_values: list = None,
                         sparkline_color: str = "#00e676", tooltip: str = "",
                         value_id: str = "", value_color: str = ""):
    is_up = delta >= 0
    delta_class = "kpi-delta--up" if is_up else "kpi-delta--down"
    delta_sign = "+" if is_up else ""
    sh = sparkline_html(
        sparkline_values or [], color=sparkline_color, width=120, height=32, prefix="ks"
    )
    safe_tooltip = html.escape(tooltip, quote=True)
    id_attr = f'id="{value_id}"' if value_id else ""
    style_attr = f'style="color: {value_color}"' if value_color else ""
    return f"""
<div class="kpi-card" title="{safe_tooltip}">
    <span class="kpi-label">{label}</span>
    <span class="kpi-value" {id_attr} {style_attr}>{value}</span>
    <span class="kpi-delta {delta_class}">{delta_sign}{delta:.2f}{delta_unit}</span>
    <span class="kpi-sparkline">{sh}</span>
</div>
"""


def render_kpi_row(metrics: list):
    cards_html = "".join(
        _build_kpi_card_html(
            label=m["label"], value=m["value"],
            delta=m.get("delta", 0.0),
            delta_unit=m.get("delta_unit", "%"),
            sparkline_values=m.get("sparkline_values"),
            sparkline_color=m.get("sparkline_color", "#00e676"),
            tooltip=m.get("tooltip", ""),
            value_id=m.get("value_id", ""),
            value_color=m.get("value_color", ""),
        )
        for m in metrics
    )

    st.markdown(f'<div class="kpi-row">{cards_html}</div>', unsafe_allow_html=True)
