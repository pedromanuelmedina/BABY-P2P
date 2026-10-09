"""Watchlist — precios en vivo de multiples bancos.
Soporta modo vertical (sidebar) y horizontal (toolbar).
"""

from typing import Dict, Optional

import html

import pandas as pd
import streamlit as st
from ..design.tokens import Color
from .sparkline import sparkline_html


def _build_card(
    bank_name: str,
    price: float,
    delta: float,
    spark_values: list,
    active: bool,
    horizontal: bool,
) -> str:
    """Construye una tarjeta de watchlist (horizontal o vertical)."""
    dclass = "wl-card__delta--up" if delta >= 0 else "wl-card__delta--down"
    dsign = "+" if delta >= 0 else ""
    sc = Color.BUY if delta >= 0 else Color.SELL
    sh = sparkline_html(spark_values, color=sc, width=110, height=24, prefix="wl")
    safe_bank = html.escape(bank_name, quote=True)
    active_cls = "wl-card--active" if active else ""
    price_id = "wl-global-price" if bank_name == "Global" else f"wl-bank-{safe_bank}"

    if horizontal:
        return f"""<div class="wl-card {active_cls}" onclick="setBank('{safe_bank}')">
            <div class="wl-card__name">{safe_bank}</div>
            <div class="wl-card__price" id="{price_id}">{price:.2f}</div>
            <div class="wl-card__delta {dclass}">{dsign}{delta:.2f}%</div>
            <div class="wl-card__sparkline">{sh}</div></div>"""
    return f"""<div class="watchlist__row {'watchlist__row--active' if active else ''}" onclick="setBank('{safe_bank}')">
        <div class="watchlist__bank">{safe_bank}</div>
        <div class="watchlist__price" id="{price_id}">{price:.2f}</div>
        <div class="watchlist__delta {('watchlist__delta--up' if delta >= 0 else 'watchlist__delta--down')}">{dsign}{delta:.2f}%</div>
        <div class="watchlist__sparkline">{sh}</div>
    </div>"""


def render_watchlist(history_df: pd.DataFrame, banks: list,
                     current_bank: str = "Mercado Global",
                     bank_data: Optional[Dict[str, pd.DataFrame]] = None,
                     horizontal: bool = False,
                     kpi_cards: Optional[list] = None):

    if horizontal:
        rows = []
        # Global row
        if not history_df.empty:
            last_price = history_df.iloc[-1].get("vwap_sell_global")
            last_price = last_price if (last_price is not None and not pd.isna(last_price)) else history_df.iloc[-1].get("vwap_sell", 0)
            last_price = last_price if (last_price is not None and not pd.isna(last_price)) else 0.0
            recent = history_df.tail(10)
            if "vwap_sell_global" in recent.columns:
                spark_values = recent["vwap_sell_global"].dropna().tolist()
            else:
                spark_values = recent["vwap_sell"].dropna().tolist() if "vwap_sell" in recent.columns else []
            delta = 0.0
            if len(spark_values) >= 2 and spark_values[0] != 0:
                delta = ((spark_values[-1] - spark_values[0]) / spark_values[0]) * 100
            rows.append(_build_card("Global", last_price, delta, spark_values,
                                    current_bank == "Mercado Global", horizontal=True))

        for bank in banks:
            if bank_data and bank in bank_data:
                bdf = bank_data[bank]
                if bdf.empty:
                    continue
                last = bdf.iloc[-1]
                buy = last.get("vwap_buy")
                buy = buy if (buy is not None and not pd.isna(buy)) else 0
                sell = last.get("vwap_sell")
                sell = sell if (sell is not None and not pd.isna(sell)) else 0
                mid_price = (buy + sell) / 2 if (buy and sell) else (buy or sell)
                mid_values = bdf[["vwap_buy", "vwap_sell"]].mean(axis=1).dropna().tolist() if "vwap_buy" in bdf.columns and "vwap_sell" in bdf.columns else []
                if not mid_values and "vwap_buy" in bdf.columns:
                    mid_values = bdf["vwap_buy"].dropna().tolist()
                delta = 0.0
                if len(mid_values) >= 2 and mid_values[0] != 0:
                    delta = ((mid_values[-1] - mid_values[0]) / mid_values[0]) * 100
                rows.append(_build_card(bank, mid_price, delta, mid_values,
                                        current_bank == bank, horizontal=True))

        if kpi_cards:
            rows.append('<div class="wl-sep"></div>')
            for kpi in kpi_cards:
                label = html.escape(kpi.get("label", ""), quote=True)
                value = html.escape(str(kpi.get("value", "")), quote=True)
                color = kpi.get("sparkline_color", Color.ACCENT)
                spark_vals = kpi.get("sparkline_values", [])
                sh = sparkline_html(spark_vals, color=color, width=110, height=24, prefix="wl-kpi")
                rows.append(f"""<div class="wl-card wl-card--kpi">
                    <div class="wl-card__name">{label}</div>
                    <div class="wl-card__price">{value}</div>
                    <div class="wl-card__sparkline">{sh}</div></div>""")

        st.html(f'<div class="wl-h">{"".join(rows)}</div>')
    else:
        st.markdown('<div class="watchlist">', unsafe_allow_html=True)

        if not history_df.empty:
            last_price = history_df.iloc[-1].get("vwap_sell_global")
            last_price = last_price if (last_price is not None and not pd.isna(last_price)) else history_df.iloc[-1].get("vwap_sell", 0)
            last_price = last_price if (last_price is not None and not pd.isna(last_price)) else 0.0
            recent = history_df.tail(10)
            if "vwap_sell_global" in recent.columns:
                spark_values = recent["vwap_sell_global"].dropna().tolist()
            else:
                spark_values = recent["vwap_sell"].dropna().tolist() if "vwap_sell" in recent.columns else []
            delta = 0.0
            if len(spark_values) >= 2 and spark_values[0] != 0:
                delta = ((spark_values[-1] - spark_values[0]) / spark_values[0]) * 100
            st.html(_build_card("Global", last_price, delta, spark_values,
                                current_bank == "Mercado Global", horizontal=False))

        for bank in banks:
            if bank_data and bank in bank_data:
                bdf = bank_data[bank]
                if bdf.empty:
                    continue
                last = bdf.iloc[-1]
                buy = last.get("vwap_buy")
                buy = buy if (buy is not None and not pd.isna(buy)) else 0
                sell = last.get("vwap_sell")
                sell = sell if (sell is not None and not pd.isna(sell)) else 0
                mid_price = (buy + sell) / 2 if (buy and sell) else (buy or sell)

                mid_values = bdf[["vwap_buy", "vwap_sell"]].mean(axis=1).dropna().tolist() if "vwap_buy" in bdf.columns and "vwap_sell" in bdf.columns else []
                if not mid_values and "vwap_buy" in bdf.columns:
                    mid_values = bdf["vwap_buy"].dropna().tolist()

                delta = 0.0
                if len(mid_values) >= 2 and mid_values[0] != 0:
                    delta = ((mid_values[-1] - mid_values[0]) / mid_values[0]) * 100
                st.html(_build_card(bank, mid_price, delta, mid_values,
                                    current_bank == bank, horizontal=False))

        st.markdown('</div>', unsafe_allow_html=True)

    st.html("""
    <script>
    function setBank(bankName) {
        const url = new URL(window.parent.location);
        url.searchParams.set('bank', bankName);
        window.parent.location.href = url.toString();
    }
    </script>
    """)
