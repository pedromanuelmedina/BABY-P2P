/**
 * ajax.js — Polling asíncrono para actualizar el dashboard sin recargar.
 *
 * Hace fetch() a la API FastAPI cada POLL_INTERVAL ms y actualiza:
 *  - KPI cards (valores numéricos)
 *  - Watchlist (precios y sparklines)
 *  - Status bar (heartbeat del worker + timestamp)
 *  - Chart LWC (si window.updateChart existe)
 *
 * Filtra el historial por el rango temporal seleccionado en el dashboard.
 */

(function() {
    'use strict';

    // Streamlit ejecuta este JS dentro de un iframe.
    // Acceder al documento principal via window.parent.
    var doc;
    var win;
    try {
        win = window.parent;
        doc = win.document;
    } catch(e) {
        win = window;
        doc = document;
    }

    // Detectar URL base de la API dinámicamente.
    // Prioridad: 1) URL inyectada desde Streamlit/env, 2) misma origin, 3) fallback relativo.
    var apiBase;
    try {
        apiBase = win.__p2p_api_url || null;
    } catch(e) { apiBase = null; }

    if (!apiBase) {
        try {
            var host = win.location.hostname;
            if (host === 'localhost' || host === '127.0.0.1') {
                var apiPort = win.__p2p_api_port || '8080';
                apiBase = win.location.protocol + '//127.0.0.1:' + apiPort + '/api';
            } else {
                // Producción: usar URL relativa (requiere reverse proxy) o mismo origin
                apiBase = win.location.protocol + '//' + host + '/api';
            }
        } catch(e) {
            apiBase = '/api';
        }
    }
    var API_BASE = apiBase;
    var POLL_INTERVAL = 60000; // 60 segundos

    // Rangos temporales (deben coincidir con config.py TIME_RANGES)
    var TIME_RANGES = {
        '2h': 2, '3h': 3, '4h': 4, '5h': 5, '6h': 6, '7h': 7, '8h': 8, '9h': 9, '10h': 10, '12h': 12, '14h': 14,
        '1d': 24, '2d': 48, '3d': 72, '4d': 96, '5d': 120,
        '1w': 168, '2w': 336, '3w': 504,
        '1m': 720, '2m': 1440, '3m': 2160
    };

    var pollTimer = null;
    var reconnectVisible = false;

    // ── Helpers ────────────────────────────────────────────────────

    function fetchData(endpoint) {
        return fetch(API_BASE + endpoint, { signal: AbortSignal.timeout(10000) })
            .then(function(r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            });
    }

    function showReconnecting(show) {
        if (show === reconnectVisible) return;
        reconnectVisible = show;
        var el = doc.getElementById('ajax-reconnect');
        if (!el) {
            el = doc.createElement('div');
            el.id = 'ajax-reconnect';
            el.style.cssText = 'position:fixed;top:0;right:0;z-index:9999;' +
                'background:rgba(239,68,68,0.9);color:#fff;padding:4px 12px;' +
                'font-family:Inter,sans-serif;font-size:12px;border-radius:0 0 0 6px;';
            doc.body.appendChild(el);
        }
        el.textContent = show ? 'Reconectando...' : '';
        el.style.display = show ? 'block' : 'none';
    }

    function safeFloat(v, decimals) {
        decimals = decimals || 2;
        var n = parseFloat(v);
        if (isNaN(n) || n === null) return 'N/A';
        return n.toFixed(decimals);
    }

    function getSelectedRange() {
        try {
            // Leer directamente del selectbox en el DOM (no depender de Streamlit)
            var labels = doc.querySelectorAll('[data-testid="stWidgetLabel"]');
            for (var i = 0; i < labels.length; i++) {
                if (labels[i].textContent.trim() === 'Rango') {
                    var wrapper = labels[i].closest('[data-testid="stVerticalBlockBorderWrapper"]')
                        || labels[i].parentElement;
                    if (wrapper) {
                        var selectDiv = wrapper.querySelector('[data-baseweb="select"]');
                        if (selectDiv) {
                            var spans = selectDiv.querySelectorAll('div');
                            for (var j = 0; j < spans.length; j++) {
                                var txt = spans[j].textContent.trim();
                                if (txt in TIME_RANGES || txt === 'Todo') return txt;
                            }
                        }
                    }
                    break;
                }
            }
        } catch(e) { /* fallback */ }
        // Fallback: variable inyectada por Streamlit (solo en primer load)
        try {
            var s = win.__p2p_selected_range || '4h';
            return s;
        } catch(e) {
            return '4h';
        }
    }

    function filterHistoryByRange(rows, rangeStr) {
        if (!rows || !rows.length) return rows;
        if (rangeStr === 'Todo' || !(rangeStr in TIME_RANGES)) return rows;
        var hours = TIME_RANGES[rangeStr];
        var cutoff = new Date();
        cutoff.setHours(cutoff.getHours() - hours);
        var cutoffEpoch = cutoff.getTime() / 1000;
        var filtered = [];
        for (var i = 0; i < rows.length; i++) {
            var ts = rows[i].timestamp;
            if (!ts) continue;
            // Normalizar timestamp a ISO 8601
            var isoTs = ts.replace(' ', 'T');
            var d = new Date(isoTs);
            if (isNaN(d.getTime())) d = new Date(ts + 'Z');
            var epoch = d.getTime() / 1000;
            if (epoch >= cutoffEpoch) {
                filtered.push(rows[i]);
            }
        }
        return filtered;
    }

    function updateTextById(id, text) {
        var el = doc.getElementById(id);
        if (!el || el.textContent === text) return;
        // Flash verde si sube, rojo si baja (solo para valores numericos)
        var oldVal = parseFloat(el.textContent.replace(/[^0-9.-]/g, ''));
        var newVal = parseFloat(text.replace(/[^0-9.-]/g, ''));
        if (!isNaN(oldVal) && !isNaN(newVal) && oldVal !== newVal) {
            el.classList.remove('flash-green', 'flash-red');
            void el.offsetWidth; // reflow para reiniciar animacion
            el.classList.add(newVal > oldVal ? 'flash-green' : 'flash-red');
            setTimeout(function() {
                el.classList.remove('flash-green', 'flash-red');
            }, 500);
        }
        el.textContent = text;
    }

    // ── Actualizadores específicos ──────────────────────────────────

    function updateHeartbeat(data) {
        if (!data) return;
        var el = doc.getElementById('worker-status');
        if (!el) return;
        var icon = data.status === 'ok' ? '\u2705' : '\u274c';
        var cycles = data.cycle_count || '?';
        el.textContent = icon + ' ' + cycles + ' ciclos';
    }

    function updateKPIs(data, isGlobal) {
        if (!data || !data.rows || data.rows.length === 0) return;
        var row = data.rows[0];

        if (isGlobal) {
            updateTextById('kpi-vwap-buy', safeFloat(row.vwap_buy_global));
            updateTextById('kpi-vwap-sell', safeFloat(row.vwap_sell_global));
            updateTextById('kpi-vol-buy', parseFloat(row.total_vol_buy || 0).toLocaleString('en-US', {maximumFractionDigits: 2}));
            updateTextById('kpi-vol-sell', parseFloat(row.total_vol_sell || 0).toLocaleString('en-US', {maximumFractionDigits: 2}));
        } else {
            updateTextById('kpi-best-buy', safeFloat(row.best_buy));
            updateTextById('kpi-best-sell', safeFloat(row.best_sell));
            updateTextById('kpi-vol-buy', safeFloat(row.acc_vol_buy));
            updateTextById('kpi-ads', (row.ad_count_sell || 0) + 'V / ' + (row.ad_count_buy || 0) + 'C');
        }
    }

    function updateWatchlist(data) {
        if (!data) return;
        // Global
        var gEl = doc.getElementById('wl-global-price');
        if (gEl) gEl.textContent = safeFloat(data.global.price);

        // Bancos
        if (data.banks) {
            Object.keys(data.banks).forEach(function(bank) {
                var safeId = 'wl-bank-' + bank.replace(/[^a-zA-Z0-9]/g, '');
                var el = doc.getElementById(safeId);
                if (el) el.textContent = safeFloat(data.banks[bank].price);
            });
        }
    }

    function updateChartIfReady(historyData) {
        if (!historyData || !historyData.data) return;
        // Filtrar por rango temporal seleccionado
        var rangeStr = getSelectedRange();
        var filtered = filterHistoryByRange(historyData.data, rangeStr);
        console.log('[AJAX] history: ' + historyData.data.length + ' rows, filtered(' + rangeStr + '): ' + filtered.length + ' rows');
        if (filtered.length === 0) return;

        // Buscar el iframe del chart LWC en el documento principal
        var iframes = doc.querySelectorAll('iframe');
        var found = false;
        for (var i = 0; i < iframes.length; i++) {
            try {
                var cw = iframes[i].contentWindow;
                if (cw && cw.updateChart) {
                    cw.updateChart(filtered);
                    found = true;
                    return;
                }
            } catch(e) { /* cross-origin, skip */ }
        }
        if (!found) console.warn('[AJAX] No se encontró iframe con updateChart');
    }

    // ── Ciclo principal de polling ──────────────────────────────────

    function poll() {
        var selectedBank = win.__p2p_selected_bank || 'Mercado Global';
        var isGlobal = selectedBank === 'Mercado Global';

        Promise.all([
            fetchData('/heartbeat').catch(function() { return null; }),
            fetchData('/latest?bank=' + encodeURIComponent(selectedBank) + '&limit=1').catch(function() { return null; }),
            fetchData('/history?bank=' + encodeURIComponent(selectedBank) + '&limit=5000').catch(function() { return null; }),
            fetchData('/watchlist?limit=20').catch(function() { return null; }),
        ]).then(function(results) {
            showReconnecting(false);
            var hb = results[0];
            var latest = results[1];
            var history = results[2];
            var wl = results[3];

            if (hb) {
                updateHeartbeat(hb);
                var tsEl = doc.getElementById('app-timestamp');
                if (tsEl && hb.timestamp) {
                    var d = new Date(hb.timestamp);
                    if (isNaN(d.getTime())) d = new Date(hb.timestamp + 'Z');
                    tsEl.textContent = d.toLocaleTimeString('es-VE', {hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'America/Caracas'});
                }
            }
            if (latest) updateKPIs(latest, isGlobal);
            if (wl) updateWatchlist(wl);
            if (history) updateChartIfReady(history);
        }).catch(function(err) {
            console.warn('AJAX poll error:', err);
            showReconnecting(true);
        });
    }

    function start() {
        if (pollTimer) return;
        poll(); // inmediato
        pollTimer = setInterval(poll, POLL_INTERVAL);
    }

    function stop() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    // Exponer para control externo
    win.__p2p_ajax = { start: start, stop: stop, poll: poll };

    // Auto-arranque cuando el DOM está listo
    if (doc.readyState === 'loading') {
        doc.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }

    // Re-conectar si la pestaña vuelve a estar visible
    doc.addEventListener('visibilitychange', function() {
        if (!doc.hidden && pollTimer) poll();
    });
})();