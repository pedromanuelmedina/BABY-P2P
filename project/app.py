"""
app.py — P2P Sentinel Pro Dashboard V3 Chart-First
===================================================
Dashboard analítico interactivo para el mercado P2P de Binance.
Prioriza el gráfico como elemento central del layout.
"""

import logging
import os
import warnings
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from .design.tokens import build_css_variables
from .assets.styles import inject_styles
import streamlit.components.v1 as components
from .components.ads_table import render_ads_table
from .components.chart_lwc import render_chart_lwc
from .components.indicator_panel import render_indicator_panel
from .components.kpi_card import render_kpi_row
from .components.watchlist import render_watchlist
from .config import HISTORY_LIMIT, TIME_RANGES
from .database import init_db, get_history, get_global_history, get_ads_by_trade_type, get_worker_heartbeat, get_distinct_banks, get_latest_volumes_by_bank, get_zinli_history
from . import config as _config_module

# Config del único mercado soportado (Venezuela / VES).
L = {
    "db_path": "p2p_sentinel.db",
    "locale": "Venezuela",
    "timezone_name": "VET",
    "label_sell": "Vendo",
    "label_buy": "Compro",
    "label_vwap_sell": "VWAP Vendo USDT",
    "label_vwap_buy": "VWAP Compro USDT",
    "label_vol_sell": "Vol Vendo",
    "label_vol_buy": "Vol Compro",
    "label_dev_sell": "Desviacion Vendo",
    "label_dev_buy": "Desviacion Compro",
}

# Config mercado Zinli (USDT/USD)
L_ZINLI = {
    "locale": "Zinli (USDT/USD)",
    "timezone_name": "VET",
    "label_sell": "Vendo USDT",
    "label_buy": "Compro USDT",
    "label_vwap_sell": "VWAP Vendo USDT",
    "label_vwap_buy": "VWAP Compro USDT",
    "label_vol_sell": "Vol Vendo USDT",
    "label_vol_buy": "Vol Compro USDT",
    "label_dev_sell": "Desv Vendo",
    "label_dev_buy": "Desv Compro",
    "currency_symbol": "USD",
}

BANKS = _config_module.BANKS
BANKS_FOR_SELECTOR = getattr(_config_module, "PRIMARY_BANKS_VES", None) or list(_config_module.BANKS)
REFRESH_OPTIONS = _config_module.REFRESH_OPTIONS
NUM_PAGES = _config_module.NUM_PAGES
now_fn = _config_module.now_venezuela
CURRENCY_SYMBOL = getattr(_config_module, "CURRENCY_SYMBOL", "")
FIAT_CURRENCY = getattr(_config_module, "FIAT_CURRENCY", "")
SKIP_FIRST_N = _config_module.SKIP_FIRST_N

warnings.filterwarnings("ignore", message=".*NotOpenSSLWarning.*")
warnings.filterwarnings("ignore", message=".*use_container_width.*")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("p2p_sentinel")


def filter_by_timerange(df: pd.DataFrame, range_str: str, now_fn) -> pd.DataFrame:
    if df.empty or range_str == "Todo" or range_str not in TIME_RANGES:
        return df
    hours = TIME_RANGES[range_str]
    cutoff = now_fn() - timedelta(hours=hours)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.replace(tzinfo=None)
    if df["timestamp"].dt.tz is not None:
        df = df.copy()
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    return df[df["timestamp"] >= cutoff].reset_index(drop=True)


# Conexiones efímeras: cada lectura abre/cierra su propia conexión read-only.
# Esto evita "database disk image is malformed" por concurrencia con el worker.
def _get_readonly_conn(db_path: str):
    return init_db(db_path, read_only=True)


@contextmanager
def _db_cursor(db_path: str):
    """Context manager que abre y cierra una conexión read-only automáticamente."""
    conn = _get_readonly_conn(db_path)
    try:
        yield conn
    finally:
        conn.close()


@st.cache_data(ttl=45)
def _cached_global_history(db_path: str, limit: int) -> pd.DataFrame:
    with _db_cursor(db_path) as conn:
        return get_global_history(conn, limit=limit)


@st.cache_data(ttl=45)
def _cached_bank_history(db_path: str, bank: str, limit: int) -> pd.DataFrame:
    with _db_cursor(db_path) as conn:
        return get_history(conn, bank, limit=limit)


@st.cache_data(ttl=45)
def _cached_zinli_history(db_path: str, limit: int) -> pd.DataFrame:
    with _db_cursor(db_path) as conn:
        return get_zinli_history(conn, limit=limit)


# ============================================================================
#  PAGINA: Configuracion inicial
# ============================================================================
st.set_page_config(
    page_title="BABY P2P",
    page_icon="\U0001f4ca",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(f"<style>{build_css_variables()}</style>", unsafe_allow_html=True)
inject_styles()

# ── Inyectar AJAX para actualización sin parpadeo ────────────────────────────
_ajax_path = Path(__file__).parent / "assets" / "ajax.js"
_ajax_js = _ajax_path.read_text(encoding="utf-8")
_api_url = os.environ.get("P2P_API_URL", "")
if _api_url:
    _safe_api_url = _api_url.replace("\\", "\\\\").replace("'", "\\'")
    components.html(f"<script>window.parent.__p2p_api_url = '{_safe_api_url}';{_ajax_js}</script>", height=0, width=0)
else:
    # Sin URL explícita: ajax.js detecta automáticamente según hostname
    components.html(f"<script>{_ajax_js}</script>", height=0, width=0)

# ── DB + Bank setup (nivel modulo) ──────────────────────────────────────────
from .config import DB_PATH as _CONFIG_DB_PATH
DB_PATH = _CONFIG_DB_PATH
PAIR_VES = f"USDT/{FIAT_CURRENCY}"
PAIR_ZINLI = "USDT/USD"

db_banks = set()
try:
    with _db_cursor(DB_PATH) as conn:
        db_banks = set(get_distinct_banks(conn))
except Exception:
    logger.warning("No se pudieron obtener bancos desde p2p_history", exc_info=True)
all_banks = sorted(db_banks | set(BANKS_FOR_SELECTOR))
banks_sorted = all_banks
bank_options = ["Mercado Global"] + all_banks + ["Zinli (USDT/USD)"]
bank_options_ads = all_banks


@st.cache_data(ttl=45)
def _cached_fetch_ads(trade_type: str, min_amount: float, db_path: str):
    with _db_cursor(db_path) as conn:
        ads = get_ads_by_trade_type(conn, trade_type, min_volume=min_amount)
        return ads, bool(ads)


# ============================================================================
#  FRAGMENTO: Toolbar + Tabs + contenido (sin auto-refresh, AJAX actualiza)
# ============================================================================
@st.fragment
def _render_content():
    # ═══════════════════════════════════════════════════════════════
    #  ROW 0: Header — titulo + LIVE + timestamp
    # ═══════════════════════════════════════════════════════════════
    st.markdown("""
    <div class="app-header">
        <div class="app-header-left">
            <svg class="app-logo" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#00e676" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
            <div>
                <div class="app-title">BABY P2P</div>
                <div class="app-subtitle">Monitoreo de precios P2P USDT/Bs.</div>
            </div>
        </div>
        <div class="app-header-right">
            <span class="live-indicator"><span class="live-dot"></span>LIVE</span>
            <span class="app-timestamp" id="app-timestamp">--:--:--</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════════
    #  SECCION EXPANDIBLE: Ajustes (mercado, tiempo, controles gráfico)
    # ═══════════════════════════════════════════════════════════════
    with st.expander("⚙️ Ajustes", expanded=False):
        # Fila 1: Mercado · Rango · Resample · Altura · Escala Y · Refresh
        ac1, ac2, ac3, ac4, ac5, ac6 = st.columns(6)
        with ac1:
            selected_bank = st.selectbox(
                "Mercado", options=bank_options, index=0, key="bank_selector",
            label_visibility="collapsed",
            )
        with ac2:
            st.selectbox("Rango", options=list(TIME_RANGES.keys()) + ["Todo"],
                         index=2, key="chart3_range", label_visibility="collapsed")
        with ac3:
            st.selectbox("Resample", ["raw", "1min", "5min", "10min", "15min", "30min"],
                         index=0, key="tab3_resample", label_visibility="collapsed")
        with ac4:
            st.selectbox("Altura", [300, 400, 480, 600, 700, 800],
                         index=2, key="chart_height", label_visibility="collapsed")
        with ac5:
            st.selectbox("Escala Y", ["auto", "fija"],
                         index=0, key="chart_yscale", label_visibility="collapsed")
        with ac6:
            force_refresh = st.button("\u21bb", type="primary", use_container_width=True,
                                      key="toolbar_refresh")
        # Fila 2: Toggles + Spans + Auto
        ct1, ct2, ct3, ct4, ct5, ct6, ct7, ct8, ct9, ct10 = st.columns(
            [0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 1, 1, 1, 0.8])
        with ct1:
            st.checkbox("VW↓", True, key="tab3_vwap_sell")
        with ct2:
            st.checkbox("VW↑", True, key="tab3_vwap_buy")
        with ct3:
            st.checkbox("Mid", False, key="tab3_mid")
        with ct4:
            st.checkbox("EM↑", False, key="tab3_ema_buy")
        with ct5:
            st.checkbox("EM↓", False, key="tab3_ema_sell")
        with ct6:
            st.checkbox("EMd", False, key="tab3_ema_mid")
        with ct7:
            st.number_input("↑span", 5, 200, 50, key="tab3_ema_buy_span",
                            label_visibility="collapsed")
        with ct8:
            st.number_input("↓span", 5, 200, 50, key="tab3_ema_sell_span",
                            label_visibility="collapsed")
        with ct9:
            st.number_input("Mdsp", 5, 200, 50, key="tab3_ema_mid_span",
                            label_visibility="collapsed")
        with ct10:
            st.selectbox(
                "Auto", options=list(REFRESH_OPTIONS.keys()), index=1,
                key="refresh_selector", label_visibility="collapsed",
            )
        if force_refresh:
            st.cache_data.clear()
            st.rerun()

    # ── Load data ──────────────────────────────────────────────────────────
    is_global = selected_bank == "Mercado Global"
    is_zinli = selected_bank == "Zinli (USDT/USD)"
    chart3_range_val = st.session_state.get("chart3_range", "4h")
    st.html(f"<script>window.parent.__p2p_selected_bank = {repr(selected_bank)}; window.parent.__p2p_selected_range = {repr(chart3_range_val)};</script>")

    if is_global:
        df_vwap = _cached_global_history(DB_PATH, HISTORY_LIMIT)
        buy_col = "vwap_buy_global"
        sell_col = "vwap_sell_global"
        mid_col = "mid_price_global"
        vol_buy_col = "total_vol_buy"
        vol_sell_col = "total_vol_sell"
        L_CUR = L
        PAIR = PAIR_VES
    elif is_zinli:
        df_vwap = _cached_zinli_history(DB_PATH, HISTORY_LIMIT)
        buy_col = "vwap_buy"
        sell_col = "vwap_sell"
        mid_col = "mid_price"
        vol_buy_col = "acc_vol_buy"
        vol_sell_col = "acc_vol_sell"
        if not df_vwap.empty and mid_col not in df_vwap.columns:
            df_vwap[mid_col] = (df_vwap[buy_col] + df_vwap[sell_col]) / 2
        L_CUR = L_ZINLI
        PAIR = PAIR_ZINLI
    else:
        df_vwap = _cached_bank_history(DB_PATH, selected_bank, HISTORY_LIMIT)
        buy_col = "vwap_buy"
        sell_col = "vwap_sell"
        mid_col = "mid_price"
        vol_buy_col = "acc_vol_buy"
        vol_sell_col = "acc_vol_sell"
        if not df_vwap.empty and mid_col not in df_vwap.columns:
            df_vwap[mid_col] = (df_vwap[buy_col] + df_vwap[sell_col]) / 2
        L_CUR = L
        PAIR = PAIR_VES

    last_ts = df_vwap.iloc[-1]["timestamp"] if not df_vwap.empty else None

    # ═══════════════════════════════════════════════════════════════
    #  ROW: Status bar (compacto)
    # ═══════════════════════════════════════════════════════════════
    h1, h2 = st.columns([3, 1])
    with h1:
        badge_html = f"{PAIR} \xb7 {L_CUR['timezone_name']}"
        if last_ts:
            badge_html += f" \xb7 \u00daltimo: {last_ts}"
        else:
            badge_html += f" \xb7 {now_fn().strftime('%H:%M')}"
        st.markdown(f"<span class='app-badge'>{badge_html}</span>", unsafe_allow_html=True)
    with h2:
        try:
            with _db_cursor(DB_PATH) as conn:
                hb = get_worker_heartbeat(conn)
                if hb:
                    icon = "\u2705" if hb["status"] == "ok" else "\u274c"
                    st.markdown(f"<span id='worker-status' class='caption'>{icon} {hb.get('cycle_count', '?')} ciclos</span>", unsafe_allow_html=True)
                else:
                    st.caption("\u23f3 Worker: sin datos")
        except Exception:
            st.caption("\u274c N/A")

    chart3_range = st.session_state.get("chart3_range", "4h")
    df_vwap_graph = filter_by_timerange(df_vwap, chart3_range, now_fn)

    # ═══════════════════════════════════════════════════════════════
    #  WATCHLIST HORIZONTAL (con bancos, precio y sparkline)
    # ═══════════════════════════════════════════════════════════════
    wl_df = _cached_global_history(DB_PATH, 100)
    if not wl_df.empty:
        bank_data = {}
        for bank in banks_sorted:
            bank_data[bank] = _cached_bank_history(DB_PATH, bank, 20)
        render_watchlist(wl_df, banks=banks_sorted, current_bank=selected_bank,
                         bank_data=bank_data, horizontal=True)
    else:
        st.caption("Watchlist: esperando datos del worker...")

    # ═══════════════════════════════════════════════════════════════
    #  TABS
    # ═══════════════════════════════════════════════════════════════
    tab_global_market, tab_anuncios = st.tabs([
        "Global + Mercado",
        "Anuncios",
    ])

    # ── TAB 1: Global —─
    with tab_global_market:

        if df_vwap.empty:
            st.error(f"No hay datos disponibles para {selected_bank}. Esperando al worker...")
        else:
            last_row = df_vwap.iloc[-1]

            if not df_vwap_graph.empty:
                # Por defecto: solo Compra y Venta visibles
                show_buy = st.session_state.get("tab3_vwap_buy", True)
                show_sell = st.session_state.get("tab3_vwap_sell", True)
                show_mid = st.session_state.get("tab3_mid", False)
                show_ema_buy = st.session_state.get("tab3_ema_buy", False)
                show_ema_sell = st.session_state.get("tab3_ema_sell", False)
                show_ema_mid = st.session_state.get("tab3_ema_mid", False)
                ema_buy_span = st.session_state.get("tab3_ema_buy_span", 50)
                ema_sell_span = st.session_state.get("tab3_ema_sell_span", 50)
                ema_mid_span = st.session_state.get("tab3_ema_mid_span", 50)

                render_chart_lwc(
                    df=df_vwap_graph,
                    buy_col=buy_col,
                    sell_col=sell_col,
                    mid_col=mid_col,
                    vol_buy_col=vol_buy_col,
                    vol_sell_col=vol_sell_col,
                    show_buy=show_buy,
                    show_sell=show_sell,
                    show_mid=show_mid,
                    show_ema_buy=show_ema_buy,
                    show_ema_sell=show_ema_sell,
                    show_ema_mid=show_ema_mid,
                    ema_buy_span=ema_buy_span,
                    ema_sell_span=ema_sell_span,
                    ema_mid_span=ema_mid_span,
                    height=st.session_state.get("chart_height", 480),
                    pair=PAIR,
                )

                render_indicator_panel(df_vwap_graph, price_col=mid_col, vol_col=vol_buy_col)

                if is_global:
                    vwap_buy_val = last_row.get(buy_col)
                    vwap_sell_val = last_row.get(sell_col)
                    acc_buy = last_row.get(vol_buy_col, 0)
                    acc_sell = last_row.get(vol_sell_col, 0)

                    buy_sl = df_vwap[buy_col].dropna().tolist()[-20:]
                    sell_sl = df_vwap[sell_col].dropna().tolist()[-20:]
                    vol_buy_sl = df_vwap[vol_buy_col].dropna().tolist()[-20:]
                    vol_sell_sl = df_vwap[vol_sell_col].dropna().tolist()[-20:]

                    render_kpi_row([
                        {"label": "COMPRA VWAP", "value": f"{vwap_buy_val:.2f} {CURRENCY_SYMBOL}" if vwap_buy_val else "N/A",
                         "delta": 0, "sparkline_values": buy_sl, "sparkline_color": "#00e676",
                         "tooltip": "VWAP ponderado por volumen lado compra", "value_id": "kpi-vwap-buy", "value_color": "#00e676"},
                        {"label": "VENTA VWAP", "value": f"{vwap_sell_val:.2f} {CURRENCY_SYMBOL}" if vwap_sell_val else "N/A",
                         "delta": 0, "sparkline_values": sell_sl, "sparkline_color": "#ff5252",
                         "tooltip": "VWAP ponderado por volumen lado venta", "value_id": "kpi-vwap-sell", "value_color": "#ff5252"},
                        {"label": "VOL. COMPRA", "value": f"{acc_buy / 1000:.1f}K USDT" if acc_buy else "N/A",
                         "delta": 0, "sparkline_values": vol_buy_sl, "sparkline_color": "#00e676",
                         "tooltip": "Volumen acumulado compra USDT", "value_id": "kpi-vol-buy", "value_color": "#00e676"},
                        {"label": "VOL. VENTA", "value": f"{acc_sell / 1000:.1f}K USDT" if acc_sell else "N/A",
                         "delta": 0, "sparkline_values": vol_sell_sl, "sparkline_color": "#ff5252",
                         "tooltip": "Volumen acumulado venta USDT", "value_id": "kpi-vol-sell", "value_color": "#ff5252"},
                    ])
                elif is_zinli:
                    vwap_buy_val = last_row.get(buy_col)
                    vwap_sell_val = last_row.get(sell_col)
                    best_buy = last_row.get("best_buy")
                    best_sell = last_row.get("best_sell")
                    ad_buy = last_row.get("ad_count_buy", 0)
                    ad_sell = last_row.get("ad_count_sell", 0)
                    acc_buy = last_row.get(vol_buy_col, 0)
                    acc_sell = last_row.get(vol_sell_col, 0)

                    buy_sl = df_vwap[buy_col].dropna().tolist()[-20:]
                    sell_sl = df_vwap[sell_col].dropna().tolist()[-20:]
                    best_buy_sl = df_vwap["best_buy"].dropna().tolist()[-20:] if "best_buy" in df_vwap else []
                    best_sell_sl = df_vwap["best_sell"].dropna().tolist()[-20:] if "best_sell" in df_vwap else []
                    vol_buy_sl = df_vwap[vol_buy_col].dropna().tolist()[-20:]
                    vol_sell_sl = df_vwap[vol_sell_col].dropna().tolist()[-20:]
                    ad_buy_sl = df_vwap["ad_count_buy"].dropna().tolist()[-20:] if "ad_count_buy" in df_vwap else []

                    render_kpi_row([
                        {"label": "COMPRA VWAP", "value": f"{vwap_buy_val:.4f} USD" if vwap_buy_val else "N/A",
                         "delta": 0, "sparkline_values": buy_sl, "sparkline_color": "#00e676",
                         "tooltip": "VWAP ponderado por volumen lado compra", "value_id": "kpi-vwap-buy", "value_color": "#00e676"},
                        {"label": "VENTA VWAP", "value": f"{vwap_sell_val:.4f} USD" if vwap_sell_val else "N/A",
                         "delta": 0, "sparkline_values": sell_sl, "sparkline_color": "#ff5252",
                         "tooltip": "VWAP ponderado por volumen lado venta", "value_id": "kpi-vwap-sell", "value_color": "#ff5252"},
                        {"label": "BEST COMPRA", "value": f"{best_buy:.4f} USD" if best_buy else "N/A",
                         "delta": 0, "sparkline_values": best_buy_sl, "sparkline_color": "#00e676",
                         "tooltip": "Mejor precio de compra disponible", "value_id": "kpi-best-buy", "value_color": "#00e676"},
                        {"label": "BEST VENTA", "value": f"{best_sell:.4f} USD" if best_sell else "N/A",
                         "delta": 0, "sparkline_values": best_sell_sl, "sparkline_color": "#ff5252",
                         "tooltip": "Mejor precio de venta disponible", "value_id": "kpi-best-sell", "value_color": "#ff5252"},
                        {"label": "VOL COMPRA", "value": f"{acc_buy:,.0f} USDT" if acc_buy else "N/A",
                         "delta": 0, "sparkline_values": vol_buy_sl, "sparkline_color": "#00e676",
                         "tooltip": "Volumen compra USDT", "value_id": "kpi-vol-buy", "value_color": "#00e676"},
                        {"label": "VOL VENTA", "value": f"{acc_sell:,.0f} USDT" if acc_sell else "N/A",
                         "delta": 0, "sparkline_values": vol_sell_sl, "sparkline_color": "#ff5252",
                         "tooltip": "Volumen venta USDT", "value_id": "kpi-vol-sell", "value_color": "#ff5252"},
                        {"label": "ANUNCIOS", "value": f"{ad_sell}V / {ad_buy}C",
                         "delta": 0, "sparkline_values": ad_buy_sl, "sparkline_color": "#ffab40",
                         "tooltip": "Cantidad de anuncios Vendo / Compro", "value_id": "kpi-ads", "value_color": "#ffab40"},
                    ])
                else:
                    best_buy = last_row.get("best_buy")
                    best_sell = last_row.get("best_sell")
                    ad_buy = last_row.get("ad_count_buy", 0)
                    ad_sell = last_row.get("ad_count_sell", 0)

                    best_buy_sl = df_vwap["best_buy"].dropna().tolist()[-20:] if "best_buy" in df_vwap else []
                    best_sell_sl = df_vwap["best_sell"].dropna().tolist()[-20:] if "best_sell" in df_vwap else []
                    ad_buy_sl = df_vwap["ad_count_buy"].dropna().tolist()[-20:] if "ad_count_buy" in df_vwap else []

                    render_kpi_row([
                        {"label": "COMPRA", "value": f"{best_buy:.2f} {CURRENCY_SYMBOL}" if best_buy else "N/A",
                         "delta": 0, "sparkline_values": best_buy_sl, "sparkline_color": "#00e676",
                         "tooltip": "Mejor precio de compra disponible", "value_id": "kpi-best-buy", "value_color": "#00e676"},
                        {"label": "VENTA", "value": f"{best_sell:.2f} {CURRENCY_SYMBOL}" if best_sell else "N/A",
                         "delta": 0, "sparkline_values": best_sell_sl, "sparkline_color": "#ff5252",
                         "tooltip": "Mejor precio de venta disponible", "value_id": "kpi-best-sell", "value_color": "#ff5252"},
                        {"label": "VOL. COMPRA", "value": f"{last_row.get('acc_vol_buy', 0) / 1000:.1f}K" if last_row.get('acc_vol_buy') else "N/A",
                         "delta": 0, "sparkline_values": [], "sparkline_color": "#00e676",
                         "tooltip": "Volumen compra USDT", "value_id": "kpi-vol-buy", "value_color": "#00e676"},
                        {"label": "ANUNCIOS", "value": f"{ad_sell}V / {ad_buy}C",
                         "delta": 0, "sparkline_values": ad_buy_sl, "sparkline_color": "#ffab40",
                         "tooltip": "Cantidad de anuncios Vendo / Compro", "value_id": "kpi-ads", "value_color": "#ffab40"},
                    ])

            if is_global:
                try:
                    with _db_cursor(DB_PATH) as conn:
                        latest_vols = get_latest_volumes_by_bank(conn)

                    if latest_vols:
                        df_latest = pd.DataFrame(latest_vols)
                        df_vol_melt = df_latest.melt(
                            id_vars=["bank"], value_vars=["sell_vol", "buy_vol"],
                            var_name="Tipo", value_name="Volumen",
                        )
                        df_vol_melt["Tipo"] = df_vol_melt["Tipo"].map({
                            "sell_vol": f"{L['label_sell']} USDT",
                            "buy_vol": f"{L['label_buy']} USDT",
                        })

                        bank_vol_total = df_vol_melt.groupby("bank")["Volumen"].sum().sort_values(ascending=False)
                        top_banks_vol = bank_vol_total.head(4).index.tolist()
                        keep_banks = list(set(top_banks_vol + BANKS))

                        df_vol_melt["Banco_agrupado"] = df_vol_melt["bank"].apply(
                            lambda b: b if b in keep_banks else "Otros",
                        )
                        df_vol_top = df_vol_melt.groupby(["Banco_agrupado", "Tipo"])["Volumen"].sum().reset_index()

                        fig_bar = go.Figure()
                        for tipo, color_label, color_val in [
                            (f"{L['label_buy']} USDT", f"{L['label_buy']} USDT", "#00e676"),
                            (f"{L['label_sell']} USDT", f"{L['label_sell']} USDT", "#ff5252"),
                        ]:
                            subset = df_vol_top[df_vol_top["Tipo"] == tipo]
                            if not subset.empty:
                                fig_bar.add_trace(go.Bar(
                                    name=color_label,
                                    y=subset["Banco_agrupado"],
                                    x=subset["Volumen"],
                                    orientation="h",
                                    marker_color=color_val,
                                    text=subset["Volumen"].apply(lambda v: f"{v:,.0f}" if v > 0 else ""),
                                    textposition="outside",
                                    hovertemplate="%{y}<br>%{x:,.2f} USDT<extra></extra>",
                                ))

                        fig_bar.update_layout(
                            barmode="group", height=300, template="plotly_dark",
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                                        font=dict(size=11, color="rgba(255,255,255,0.5)")),
                            margin=dict(t=20, b=5, l=5, r=5),
                            xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.04)", zeroline=False,
                                       tickfont=dict(size=10, color="rgba(255,255,255,0.3)")),
                            yaxis=dict(showgrid=False, zeroline=False,
                                       tickfont=dict(size=11, color="rgba(255,255,255,0.5)")),
                        )
                        st.plotly_chart(fig_bar, use_container_width=True)

                        other_banks = sorted(set(bank_vol_total.index) - set(keep_banks))
                        st.caption(
                            f"Bancos: {', '.join(sorted(keep_banks))} | "
                            f"Otros: {', '.join(other_banks) if other_banks else '(ninguno)'}"
                        )
                except Exception as e:
                    logger.error(f"Error generando grafica de volumen: {e}")
                    st.warning("No se pudo cargar el volumen por metodo de pago.")

            with st.expander("Historial"):
                if is_global:
                    col_config = {
                        "timestamp": "Timestamp",
                        buy_col: st.column_config.NumberColumn("VWAP Sell", format="%.2f"),
                        sell_col: st.column_config.NumberColumn("VWAP Buy", format="%.2f"),
                        mid_col: st.column_config.NumberColumn("Mid Price", format="%.2f"),
                        vol_buy_col: st.column_config.NumberColumn("Vol Buy (USDT)", format="%.2f"),
                        vol_sell_col: st.column_config.NumberColumn("Vol Sell (USDT)", format="%.2f"),
                    }
                elif is_zinli:
                    col_config = {
                        "timestamp": "Timestamp",
                        "best_buy": st.column_config.NumberColumn("Best Buy", format="%.4f"),
                        "best_sell": st.column_config.NumberColumn("Best Sell", format="%.4f"),
                        buy_col: st.column_config.NumberColumn("VWAP Buy", format="%.4f"),
                        sell_col: st.column_config.NumberColumn("VWAP Sell", format="%.4f"),
                        "spread": st.column_config.NumberColumn("Spread", format="%.4f"),
                        vol_buy_col: st.column_config.NumberColumn("Vol Buy (USDT)", format="%.2f"),
                        vol_sell_col: st.column_config.NumberColumn("Vol Sell (USDT)", format="%.2f"),
                        "ad_count_buy": "Ads Buy",
                        "ad_count_sell": "Ads Sell",
                    }
                else:
                    col_config = {
                        "timestamp": "Timestamp",
                        "best_buy": st.column_config.NumberColumn("Best Buy", format="%.2f"),
                        "best_sell": st.column_config.NumberColumn("Best Sell", format="%.2f"),
                        buy_col: st.column_config.NumberColumn("VWAP Buy", format="%.2f"),
                        sell_col: st.column_config.NumberColumn("VWAP Sell", format="%.2f"),
                        "spread": st.column_config.NumberColumn("Spread", format="%.2f"),
                        vol_buy_col: st.column_config.NumberColumn("Vol Buy", format="%.2f"),
                        vol_sell_col: st.column_config.NumberColumn("Vol Sell", format="%.2f"),
                        "ad_count_buy": "Ads Buy",
                        "ad_count_sell": "Ads Sell",
                    }
                st.dataframe(
                    df_vwap.tail(20), use_container_width=True, hide_index=True,
                    column_config=col_config,
                )

    # ── TAB 2: Anuncios ──
    with tab_anuncios:
        st.markdown("**Anuncios P2P en vivo** \u2014 merchants verificados \xb7 comparador de bancos \xb7 solo compra")

        col1, col2, col3 = st.columns(3)
        with col1:
            min_vol_ads = st.number_input("Vol. minimo USDT", min_value=0, value=0, step=10, key="min_vol_ads")
        with col2:
            banco_a = st.selectbox("Banco A", options=bank_options_ads or list(BANKS_FOR_SELECTOR), index=0, key="banco_a_selector")
        with col3:
            banks_b = bank_options_ads or list(BANKS_FOR_SELECTOR)
            bancos_para_b = [b for b in banks_b if b != banco_a] if len(banks_b) > 1 else banks_b
            banco_b = st.selectbox("Banco B", options=bancos_para_b, index=0, key="banco_b_selector")

        with st.spinner("Cargando anuncios..."):
            ads_raw, success = _cached_fetch_ads("BUY", min_vol_ads, DB_PATH)
            buy_ads = ads_raw if success else []

        ads_a = [a for a in buy_ads if a.get("bank", "") == banco_a]
        ads_b = [a for a in buy_ads if a.get("bank", "") == banco_b]
        ads_a.sort(key=lambda a: float(a.get("price", 0)))
        ads_b.sort(key=lambda a: float(a.get("price", 0)))
        prices_a = [a["price"] for a in ads_a if a.get("price")]
        prices_b = [a["price"] for a in ads_b if a.get("price")]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(f"Mejor {banco_a}", f"{prices_a[0]:.3f} {CURRENCY_SYMBOL}" if prices_a else "N/A")
        m2.metric(f"Mejor {banco_b}", f"{prices_b[0]:.3f} {CURRENCY_SYMBOL}" if prices_b else "N/A")
        total_vol = sum(a.get("volume", 0) or 0 for a in buy_ads)
        m3.metric("Vol. Total USDT", f"{total_vol:,.0f}")
        m4.metric("Merchants", str(len(set(a.get("nickname", "") for a in buy_ads if a.get("nickname")))))

        st.markdown("")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"##### \U0001f7e2 Compra \u2014 {banco_a}")
            render_ads_table(ads_a, page_size=10, title=f"Anuncios {banco_a}")
        with col_b:
            st.markdown(f"##### \U0001f7e2 Compra \u2014 {banco_b}")
            render_ads_table(ads_b, page_size=10, title=f"Anuncios {banco_b}")


_render_content()