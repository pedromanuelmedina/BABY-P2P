"""Panel de indicadores tecnicos — RSI y VWAP."""

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from ..design.tokens import Color

c = Color()


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(100)


def _chart_layout(height: int = 200) -> dict:
    return dict(
        height=height, margin=dict(t=12, b=8, l=12, r=52),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", size=12, color=c.CHART_TEXT),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
            bgcolor="rgba(0,0,0,0)",
            itemclick="toggle",
            itemdoubleclick="toggleothers",
        ),
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=True, gridcolor=c.CHART_GRID, side="right", zeroline=False),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(17, 21, 31, 0.95)",
            bordercolor=c.BORDER_DEFAULT,
            font=dict(family="Inter", size=11, color=c.TEXT_PRIMARY),
        ),
    )


def _render_rsi(df: pd.DataFrame, price_col: str, period: int = 14):
    rsi = _compute_rsi(df[price_col], period=period)

    fig = go.Figure()
    # RSI line with gradient fill
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=rsi, mode="lines",
        line=dict(color=c.ACCENT, width=2.5),
        fill="tozeroy",
        fillcolor="rgba(59, 130, 246, 0.15)",
        name=f"RSI({period})",
        hovertemplate="<b>RSI</b>: %{y:.1f}<br><b>Hora</b>: %{x|%H:%M}<extra></extra>",
    ))
    # overbought zone
    fig.add_hrect(y0=70, y1=100,
                  fillcolor=c.BUY_BG, line_width=0, layer="below")
    # oversold zone
    fig.add_hrect(y0=0, y1=30,
                  fillcolor=c.SELL_BG, line_width=0, layer="below")
    # reference lines
    fig.add_hline(y=70, line=dict(color=c.BUY, width=1, dash="dot"))
    fig.add_hline(y=30, line=dict(color=c.SELL, width=1, dash="dot"))
    fig.add_hline(y=50, line=dict(color=c.BORDER_STRONG, width=0.5, dash="dash"))

    fig.update_layout(**_chart_layout())
    fig.update_yaxes(range=[0, 100], tickformat=".0f")
    fig.update_xaxes(range=[df["timestamp"].min(), df["timestamp"].max()], autorange=False)

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_indicator_panel(df: pd.DataFrame, price_col: str,
                           vol_col: Optional[str] = None,
                           vwap_buy_col: Optional[str] = None,
                           vwap_sell_col: Optional[str] = None):
    if df is None or df.empty:
        st.caption("Sin datos para indicadores.")
        return

    with st.expander("📊 RSI (14) — Relative Strength Index", expanded=True):
        _render_rsi(df, price_col, period=14)
