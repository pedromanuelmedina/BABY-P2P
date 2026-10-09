"""Wrapper de lightweight-charts v5 (TradingView) para Streamlit.
Carga el bundle LWC desde assets local, renderiza dos lineas (buy/sell)
y overlays toggleables (Mid, EMd).
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from ..design.tokens import Color

logger = logging.getLogger(__name__)

_BUNDLE_DIR = Path(__file__).resolve().parent.parent / "assets"
_LWC_BUNDLE: Optional[str] = None


def _get_chart_colors() -> Dict[str, str]:
    """Retorna colores del design system para inyectar en el chart LWC."""
    c = Color()
    return {
        "bg": c.CHART_BG,
        "text": c.CHART_TEXT,
        "textPrimary": c.TEXT_PRIMARY,
        "buy": c.BUY,
        "sell": c.SELL,
        "mid": c.MID_PRICE,
        "accent": c.ACCENT,
        "emaBuy": c.BUY_EMA,
        "emaSell": c.SELL_EMA,
        "emaMid": c.MID,
        "grid": c.CHART_GRID,
        "border": c.BORDER_SUBTLE,
        "hover": c.BG_SURFACE,
        "watermark": "rgba(255,255,255,0.03)",
        "volBuy": c.CHART_VOLUME_UP.replace("0.40", "0.85"),
        "volBuyFill": c.CHART_VOLUME_UP.replace("0.40", "0.25"),
        "volSell": c.CHART_VOLUME_DOWN.replace("0.40", "0.85"),
        "volSellFill": c.CHART_VOLUME_DOWN.replace("0.40", "0.08"),
    }


def _get_lwc_bundle() -> str:
    global _LWC_BUNDLE
    if _LWC_BUNDLE is None:
        bundle_path = _BUNDLE_DIR / "chart_lwc.js"
        if bundle_path.exists():
            _LWC_BUNDLE = bundle_path.read_text(encoding="utf-8")
        else:
            _LWC_BUNDLE = ""
            logger.warning("chart_lwc.js no encontrado en assets/")
    return _LWC_BUNDLE


def _build_timeseries(df, col: str) -> List[Dict[str, Any]]:
    """Construye una serie temporal para LWC.
    Si un valor es NULL/NaN, inserta un whitespace point {time} sin value
    para que LWC CORTE la línea en ese punto en vez de unir a través del hueco.
    """
    data: List[Dict[str, Any]] = []
    for ts, val in zip(df["timestamp"], df[col]):
        epoch = int(ts.timestamp())
        try:
            v = round(float(val), 4)
        except (ValueError, TypeError):
            data.append({"time": epoch})
            continue
        if pd.isna(v):
            data.append({"time": epoch})
        else:
            data.append({"time": epoch, "value": v})
    return data


def _build_chart_html(
    buy_data: list,
    sell_data: list,
    volume_buy: Optional[list] = None,
    volume_sell: Optional[list] = None,
    mid: Optional[list] = None,
    ema_mid: Optional[list] = None,
    ema_buy: Optional[list] = None,
    ema_sell: Optional[list] = None,
    show_buy: bool = True,
    show_sell: bool = True,
    show_mid: bool = True,
    show_ema_mid: bool = True,
    show_ema_buy: bool = False,
    show_ema_sell: bool = False,
    height: int = 480,
    pair: str = "USDT/VES",
    buy_col: str = "vwap_buy",
    sell_col: str = "vwap_sell",
    mid_col: str = "mid_price",
    vol_buy_col: str = "acc_vol_buy",
    vol_sell_col: str = "acc_vol_sell",
    ema_buy_span: int = 50,
    ema_sell_span: int = 50,
    ema_mid_span: int = 50,
) -> str:
    has_buy = show_buy and bool(buy_data)
    has_sell = show_sell and bool(sell_data)
    has_mid = show_mid and bool(mid)
    has_ema_mid = show_ema_mid and bool(ema_mid)
    has_ema_buy = show_ema_buy and bool(ema_buy)
    has_ema_sell = show_ema_sell and bool(ema_sell)
    has_vol_buy = bool(volume_buy)
    has_vol_sell = bool(volume_sell)

    buy_json = json.dumps(buy_data)
    sell_json = json.dumps(sell_data)
    volume_buy_json = json.dumps(volume_buy or [])
    volume_sell_json = json.dumps(volume_sell or [])
    mid_json = json.dumps(mid or [])
    ema_mid_json = json.dumps(ema_mid or [])
    ema_buy_json = json.dumps(ema_buy or [])
    ema_sell_json = json.dumps(ema_sell or [])

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--color-chart-bg, #0B0E14);
            font-family: 'Inter', sans-serif;
            overflow: hidden;
        }}
        #lwc-container {{
            width: 100%;
            height: {height}px;
            position: relative;
        }}
        #lwc-tooltip {{
            position: absolute; display: none;
            padding: 8px 12px;
            background: rgba(17, 21, 31, 0.95);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 6px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            color: #e0e0e0;
            pointer-events: none;
            z-index: 10;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
            white-space: nowrap;
        }}
        #lwc-tooltip .row {{ display: flex; justify-content: space-between; gap: 12px; }}
        #lwc-tooltip .label {{ color: {Color.TEXT_MUTED}; }}
        #lwc-tooltip .value {{ color: {Color.TEXT_PRIMARY}; }}
        #lwc-tooltip .value.buy {{ color: {Color.BUY}; }}
        #lwc-tooltip .value.sell {{ color: {Color.SELL}; }}
        #lwc-tooltip .value.mid {{ color: {Color.MID_PRICE}; }}
        #lwc-tooltip .value.emid {{ color: {Color.MID}; }}
        #lwc-tooltip .value.emab {{ color: {Color.BUY_EMA}; }}
        #lwc-tooltip .value.emas {{ color: {Color.SELL_EMA}; }}
        #lwc-fs-btn {{
            position: absolute; top: 8px; right: 8px; z-index: 20;
            width: 30px; height: 30px; background: rgba(17,21,31,0.85);
            border: 1px solid rgba(255,255,255,0.10); border-radius: 4px;
            color: rgba(255,255,255,0.4); cursor: pointer; display: flex;
            align-items: center; justify-content: center;
            font-size: 16px; font-family: 'Inter', sans-serif;
            transition: all 0.15s ease; outline: none;
        }}
        #lwc-fs-btn:hover {{
            color: #e0e0e0; border-color: rgba(255,255,255,0.22);
            background: rgba(17,21,31,0.95);
        }}
    </style>
</head>
<body>
    <div id="lwc-chart-wrapper" style="position:relative;width:100%;height:{height}px;">
        <div id="lwc-container"></div>
        <div id="lwc-tooltip"></div>
        <button id="lwc-fs-btn" title="Fullscreen (F)">\u26f6</button>
    </div>

    <script>{_get_lwc_bundle()}</script>
    <script>
    const C = {json.dumps(_get_chart_colors())};
    (function() {{
        const container = document.getElementById('lwc-container');
        const tooltip = document.getElementById('lwc-tooltip');

        let chart;
        try {{
            chart = LightweightCharts.createChart(container, {{
                localization: {{
                    timezone: 'America/Caracas',
                }},
                autoSize: true,
                layout: {{
                    background: {{ type: 'solid', color: C.bg }},
                    textColor: C.text,
                    fontFamily: "'Inter', sans-serif",
                    fontSize: 11,
                }},
                grid: {{
                    vertLines: {{ color: C.grid }},
                    horzLines: {{ color: C.grid }},
                }},
                crosshair: {{
                    mode: LightweightCharts.CrosshairMode.Normal,
                    vertLine: {{
                        color: C.text, width: 1,
                        style: LightweightCharts.LineStyle.Dashed,
                        labelBackgroundColor: C.hover,
                    }},
                    horzLine: {{
                        color: C.text, width: 1,
                        style: LightweightCharts.LineStyle.Dashed,
                        labelBackgroundColor: C.hover,
                    }},
                }},
                rightPriceScale: {{
                    borderColor: C.border,
                    scaleMargins: {{ top: 0.08, bottom: 0.18 }},
                }},
                timeScale: {{
                    borderColor: C.border,
                    timeVisible: true, secondsVisible: false,
                    rightOffset: 0,
                    fixLeftEdge: true,
                    fixRightEdge: true,
                }},
                watermark: {{
                    visible: true, fontSize: 24,
                    color: C.watermark,
                    text: {json.dumps(pair)},
                }},
                handleScroll: false,
                handleScale: {{ mouseWheel: false, pinch: false, axisPressedMouseMove: {{ time: true, price: true }}, axisDoubleClickReset: {{ time: true, price: true }} }},
            }});

            let buyLine = null;
            if ({str(has_buy).lower()}) {{
                buyLine = chart.addSeries(LightweightCharts.LineSeries, {{
                    color: C.buy, lineWidth: 2,
                    lineType: 2,
                    lastValueVisible: true, priceLineVisible: false,
                }});
                buyLine.setData({buy_json});
            }}

            let sellLine = null;
            if ({str(has_sell).lower()}) {{
                sellLine = chart.addSeries(LightweightCharts.LineSeries, {{
                    color: C.sell, lineWidth: 2,
                    lineType: 2,
                    lastValueVisible: true, priceLineVisible: false,
                }});
                sellLine.setData({sell_json});
            }}

            // Volume: AreaSeries con relleno opacado (buy verde / sell rojo)
            let volBuySeries = null;
            if ({str(has_vol_buy).lower()}) {{
                volBuySeries = chart.addSeries(LightweightCharts.AreaSeries, {{
                    lineColor: C.volBuy,
                    topColor: C.volBuyFill,
                    bottomColor: 'rgba(16,185,129,0.08)',
                    lineWidth: 1,
                    priceScaleId: 'volume',
                    lastValueVisible: false,
                    priceLineVisible: false,
                }});
                volBuySeries.priceScale().applyOptions({{
                    scaleMargins: {{ top: 0.82, bottom: 0.00 }},
                }});
                volBuySeries.setData({volume_buy_json});
            }}

            let volSellSeries = null;
            if ({str(has_vol_sell).lower()}) {{
                volSellSeries = chart.addSeries(LightweightCharts.AreaSeries, {{
                    lineColor: C.volSell,
                    topColor: C.volSellFill,
                    bottomColor: 'rgba(239,68,68,0.08)',
                    lineWidth: 1,
                    priceScaleId: 'volume',
                    lastValueVisible: false,
                    priceLineVisible: false,
                }});
                volSellSeries.priceScale().applyOptions({{
                    scaleMargins: {{ top: 0.82, bottom: 0.00 }},
                }});
                volSellSeries.setData({volume_sell_json});
            }}

            let midLine = null;
            if ({str(has_mid).lower()}) {{
                midLine = chart.addSeries(LightweightCharts.LineSeries, {{
                    color: C.mid, lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    lineType: 2,
                    priceLineVisible: false, lastValueVisible: false,
                }});
                midLine.setData({mid_json});
            }}

            let emaMidLine = null;
            if ({str(has_ema_mid).lower()}) {{
                emaMidLine = chart.addSeries(LightweightCharts.LineSeries, {{
                    color: C.emaMid, lineWidth: 1,
                    lineType: 2,
                    priceLineVisible: false, lastValueVisible: false,
                }});
                emaMidLine.setData({ema_mid_json});
            }}

            let emaBuyLine = null;
            if ({str(has_ema_buy).lower()}) {{
                emaBuyLine = chart.addSeries(LightweightCharts.LineSeries, {{
                    color: C.emaBuy,
                    lineWidth: 1, lineType: 2,
                    priceLineVisible: false, lastValueVisible: false,
                }});
                emaBuyLine.setData({ema_buy_json});
            }}

            let emaSellLine = null;
            if ({str(has_ema_sell).lower()}) {{
                emaSellLine = chart.addSeries(LightweightCharts.LineSeries, {{
                    color: C.emaSell,
                    lineWidth: 1, lineType: 2,
                    priceLineVisible: false, lastValueVisible: false,
                }});
                emaSellLine.setData({ema_sell_json});
            }}

            chart.subscribeCrosshairMove(function(param) {{
                if (!param.time) {{
                    tooltip.style.display = 'none';
                    return;
                }}
                const buyData = buyLine ? param.seriesData.get(buyLine) : null;
                const sellData = sellLine ? param.seriesData.get(sellLine) : null;
                const volBuy = volBuySeries ? param.seriesData.get(volBuySeries) : null;
                const volSell = volSellSeries ? param.seriesData.get(volSellSeries) : null;
                const midData = midLine ? param.seriesData.get(midLine) : null;
                const emaMidData = emaMidLine ? param.seriesData.get(emaMidLine) : null;
                const emaBuyData = emaBuyLine ? param.seriesData.get(emaBuyLine) : null;
                const emaSellData = emaSellLine ? param.seriesData.get(emaSellLine) : null;
                if (!buyData && !sellData) {{
                    tooltip.style.display = 'none';
                    return;
                }}
                const date = new Date(param.time * 1000);
                const timeStr = date.toLocaleTimeString('es-VE', {{ hour: '2-digit', minute: '2-digit', timeZone: 'America/Caracas' }});
                var html = '<div class="row"><span class="label">Hora</span><span class="value">' + timeStr + '</span></div>';
                if (buyData) {{
                    const prev = buyData.value;
                    html += '<div class="row"><span class="label">Compra</span><span class="value buy">' + prev.toFixed(2) + '</span></div>';
                }}
                if (sellData) {{
                    const val = sellData.value;
                    html += '<div class="row"><span class="label">Venta</span><span class="value sell">' + val.toFixed(2) + '</span></div>';
                }}
                if (midData) {{
                    html += '<div class="row"><span class="label">Mid</span><span class="value mid">' + midData.value.toFixed(2) + '</span></div>';
                }}
                if (emaMidData) {{
                    html += '<div class="row"><span class="label">EMd</span><span class="value emid">' + emaMidData.value.toFixed(2) + '</span></div>';
                }}
                if (emaBuyData) {{
                    html += '<div class="row"><span class="label">EM↑</span><span class="value emab">' + emaBuyData.value.toFixed(2) + '</span></div>';
                }}
                if (emaSellData) {{
                    html += '<div class="row"><span class="label">EM↓</span><span class="value emas">' + emaSellData.value.toFixed(2) + '</span></div>';
                }}
                var totalVol = 0;
                if (volBuy) totalVol += volBuy.value;
                if (volSell) totalVol += Math.abs(volSell.value);
                if (totalVol > 0) {{
                    html += '<div class="row"><span class="label">Vol</span><span class="value">' + totalVol.toLocaleString('en-US', {{maximumFractionDigits: 0}}) + '</span></div>';
                }}
                tooltip.innerHTML = html;
                const x = param.point ? param.point.x : 0;
                const y = param.point ? param.point.y : 0;
                var left = x + 12;
                if (left + 160 > container.clientWidth) left = x - 172;
                tooltip.style.left = left + 'px';
                tooltip.style.top = (y + 12) + 'px';
                tooltip.style.display = 'block';
            }});

            chart.timeScale().fitContent();

            const lastPriceEl = document.createElement('div');
            lastPriceEl.id = 'last-price-corner';
            lastPriceEl.style.cssText = 'position:absolute;top:6px;left:8px;font-family:JetBrains Mono;font-size:11px;color:#e0e0e0;z-index:5;pointer-events:none;';
            container.appendChild(lastPriceEl);
            const lastMidData = midLine ? midLine.data() : [];
            const lastBuyData = buyLine ? buyLine.data() : [];
            if (lastMidData.length > 0) {{
                lastPriceEl.textContent = 'Últ: ' + lastMidData[lastMidData.length - 1].value.toFixed(2);
                lastPriceEl.style.color = C.mid;
            }} else if (lastBuyData.length > 0) {{
                lastPriceEl.textContent = 'Últ: ' + lastBuyData[lastBuyData.length - 1].value.toFixed(2);
                lastPriceEl.style.color = C.buy;
            }}

            // ── Exponer updateChart para AJAX (ajax.js) ───────────────
            // Permite actualizar las series del chart sin recrear el iframe.
            window.updateChart = function(rows) {{
                if (!rows || !rows.length) return;
                var tsKey = 'timestamp';
                function toSeries(rows, col) {{
                    var out = [];
                    for (var i = 0; i < rows.length; i++) {{
                        var r = rows[i];
                        var ts = r[tsKey];
                        if (!ts) continue;
                        var isoTs = ts.replace(' ', 'T');
                        var d = new Date(isoTs);
                        if (isNaN(d.getTime())) d = new Date(ts + 'Z');
                        var epoch = Math.floor(d.getTime() / 1000);
                        var raw = r[col];
                        var val = parseFloat(raw);
                        if (raw === null || raw === undefined || isNaN(val)) {{
                            out.push({{time: epoch}});
                        }} else {{
                            out.push({{time: epoch, value: val}});
                        }}
                    }}
                    return out;
                }}
                function computeEMA(values, span) {{
                    if (!values.length) return [];
                    var alpha = 2 / (span + 1);
                    var ema = [];
                    var prev = values[0];
                    for (var i = 0; i < values.length; i++) {{
                        if (values[i] === null || values[i] === undefined || isNaN(values[i])) {{
                            ema.push(null);
                            continue;
                        }}
                        if (prev === null || prev === undefined || isNaN(prev)) {{
                            prev = values[i];
                        }} else {{
                            prev = alpha * values[i] + (1 - alpha) * prev;
                        }}
                        ema.push(prev);
                    }}
                    return ema;
                }}
                function toSeriesWithEMA(rows, valueCol, span) {{
                    var series = toSeries(rows, valueCol);
                    if (!series.length || !span) return [];
                    var vals = series.map(function(p) {{ return p.value !== undefined ? p.value : null; }});
                    var emas = computeEMA(vals, span);
                    var out = [];
                    for (var i = 0; i < series.length; i++) {{
                        if (emas[i] !== null && !isNaN(emas[i])) {{
                            out.push({{time: series[i].time, value: emas[i]}});
                        }}
                    }}
                    return out;
                }}
                // Safety: only setData if series has at least 1 point WITH a value
                function hasValues(series) {{
                    for (var i = 0; i < series.length; i++) {{
                        if (series[i].value !== undefined) return true;
                    }}
                    return false;
                }}
                try {{
                    var buySeries = toSeries(rows, '{buy_col}');
                    var sellSeries = toSeries(rows, '{sell_col}');
                    console.log('[updateChart] rows=' + rows.length + ' buy=' + buySeries.length + ' sell=' + sellSeries.length);
                    if (buyLine && hasValues(buySeries)) buyLine.setData(buySeries);
                    if (sellLine && hasValues(sellSeries)) sellLine.setData(sellSeries);
                    if (volBuySeries) {{
                        var vb = toSeries(rows, '{vol_buy_col}');
                        if (hasValues(vb)) volBuySeries.setData(vb);
                    }}
                    if (volSellSeries) {{
                        var vs = toSeries(rows, '{vol_sell_col}');
                        if (hasValues(vs)) volSellSeries.setData(vs);
                    }}
                    if (midLine) {{
                        var md = toSeries(rows, '{mid_col}');
                        if (hasValues(md)) midLine.setData(md);
                    }}
                    if (emaMidLine) emaMidLine.setData(toSeriesWithEMA(rows, '{mid_col}', {ema_mid_span}));
                    if (emaBuyLine) emaBuyLine.setData(toSeriesWithEMA(rows, '{buy_col}', {ema_buy_span}));
                    if (emaSellLine) emaSellLine.setData(toSeriesWithEMA(rows, '{sell_col}', {ema_sell_span}));
                    chart.timeScale().fitContent();

                    // Actualizar último precio
                    var lastRow = rows[rows.length - 1];
                    var lastVal = lastRow['{mid_col}'] || lastRow['{buy_col}'];
                    if (lastVal) {{
                        lastPriceEl.textContent = 'Últ: ' + parseFloat(lastVal).toFixed(2);
                    }}
                }} catch(e) {{
                    console.warn('updateChart error:', e);
                }}
            }};
        }} catch(e) {{
            container.innerHTML = '<div style="padding:20px;font-family:monospace;font-size:12px;color:#ff5252;border:1px solid #ff5252;border-radius:6px;margin:10px">Chart Error: ' + e.message + '<br><br><span style="color:rgba(255,255,255,0.4)">Reload the page or check console (F12) for details.</span></div>';
            console.error('Chart error:', e);
        }}
    }})();

    (function() {{
        function toggleFs() {{
            if (document.fullscreenElement) {{
                document.exitFullscreen();
            }} else {{
                document.documentElement.requestFullscreen();
            }}
        }}
        const btn = document.getElementById('lwc-fs-btn');
        if (btn) btn.addEventListener('click', toggleFs);
        document.addEventListener('keydown', function(e) {{
            if ((e.key === 'f' || e.key === 'F') && e.target.tagName !== 'INPUT') {{
                e.preventDefault();
                toggleFs();
            }}
        }});
    }})();
    </script>
</body>
</html>
    """
    return html


def render_chart_lwc(
    df,
    buy_col: str,
    sell_col: str,
    vol_buy_col: str,
    vol_sell_col: str,
    mid_col: str = "mid_price",
    show_buy: bool = True,
    show_sell: bool = True,
    show_mid: bool = True,
    show_ema_mid: bool = True,
    show_ema_buy: bool = False,
    show_ema_sell: bool = False,
    ema_buy_span: int = 50,
    ema_sell_span: int = 50,
    ema_mid_span: int = 50,
    height: int = 480,
    pair: str = "USDT/VES",
):
    if df is None or df.empty:
        st.warning("Sin datos para mostrar en el chart.")
        return

    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("America/Caracas")

    buy_data = _build_timeseries(df, buy_col) if buy_col in df.columns else []
    sell_data = _build_timeseries(df, sell_col) if sell_col in df.columns else []

    volume_buy = []
    volume_sell = []
    if vol_buy_col in df.columns and vol_sell_col in df.columns:
        timestamps = [int(ts.timestamp()) for ts in df["timestamp"]]
        buy_vals = df[vol_buy_col].fillna(0).round(2).tolist()
        sell_vals = df[vol_sell_col].fillna(0).round(2).tolist()
        volume_buy = [{"time": ts, "value": b} for ts, b in zip(timestamps, buy_vals)]
        volume_sell = [{"time": ts, "value": s} for ts, s in zip(timestamps, sell_vals)]

    mid_data = []
    ema_mid_data = []
    ema_buy_data = []
    ema_sell_data = []

    if mid_col in df.columns:
        if show_mid:
            mid_data = _build_timeseries(df, mid_col)
        if show_ema_mid:
            ema = df[mid_col].ewm(span=ema_mid_span, adjust=False).mean()
            for ts, val in zip(df["timestamp"], ema):
                if not pd.isna(val):
                    ema_mid_data.append({
                        "time": int(ts.timestamp()),
                        "value": float(val),
                    })

    if show_ema_buy and buy_col in df.columns:
        ema = df[buy_col].ewm(span=ema_buy_span, adjust=False).mean()
        for ts, val in zip(df["timestamp"], ema):
            if not pd.isna(val):
                ema_buy_data.append({
                    "time": int(ts.timestamp()),
                    "value": float(val),
                })

    if show_ema_sell and sell_col in df.columns:
        ema = df[sell_col].ewm(span=ema_sell_span, adjust=False).mean()
        for ts, val in zip(df["timestamp"], ema):
            if not pd.isna(val):
                ema_sell_data.append({
                    "time": int(ts.timestamp()),
                    "value": float(val),
                })

    html = _build_chart_html(
        buy_data=buy_data,
        sell_data=sell_data,
        volume_buy=volume_buy,
        volume_sell=volume_sell,
        mid=mid_data,
        ema_mid=ema_mid_data,
        ema_buy=ema_buy_data,
        ema_sell=ema_sell_data,
        show_buy=show_buy,
        show_sell=show_sell,
        show_mid=show_mid,
        show_ema_mid=show_ema_mid,
        show_ema_buy=show_ema_buy,
        show_ema_sell=show_ema_sell,
        height=height,
        pair=pair,
        buy_col=buy_col,
        sell_col=sell_col,
        mid_col=mid_col,
        vol_buy_col=vol_buy_col,
        vol_sell_col=vol_sell_col,
        ema_buy_span=ema_buy_span,
        ema_sell_span=ema_sell_span,
        ema_mid_span=ema_mid_span,
    )

    components.html(html, height=height + 20, scrolling=False, width="stretch")
