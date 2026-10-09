"""
worker.py — Proceso de recolección de datos P2P en segundo plano.

Este script corre como daemon independiente de Streamlit.
Ciclo: Scrape Binance → Calcular métricas → Guardar en SQLite.
El dashboard (app.py) solo lee de la BD, sin bloqueos ni spinners.

Uso:
    python3 worker.py                  # Corre en primer plano (para debug)
    nohup python3 worker.py &          # Corre en segundo plano (producción)
"""

import sys
sys.dont_write_bytecode = True  # noqa: E402

import logging  # noqa: E402
import logging.handlers  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
import time  # noqa: E402
from typing import Optional  # noqa: E402

from .config import (  # noqa: E402
    SKIP_FIRST_N,
    NUM_PAGES,
    ROWS_PER_PAGE,
    now_venezuela,
    PRIMARY_BANKS_VES,
    OUTLIER_IQR_MULTIPLIER,
    MIN_GLOBAL_SNAPSHOT_ADS,
    MIN_BANK_SNAPSHOT_ADS,
    ZINLI_ASSET,
    ZINLI_FIAT,
    ZINLI_PAYTYPE,
)
from .database import init_db, insert_snapshot, insert_global_snapshot, insert_ads_snapshot, cleanup_old_data, upsert_worker_heartbeat, insert_zinli_snapshot  # noqa: E402
from .metrics import compute_all_metrics, compute_vwap, compute_accumulated_volume, filter_outliers_iqr  # noqa: E402
import asyncio  # noqa: E402
from .scraper import fetch_ads_global, fetch_ads_bank, fetch_ads_merchant  # noqa: E402
from .utils import _run_async  # noqa: E402

# ─── Configuración del Worker ────────────────────────────────────────────────
WORKER_INTERVAL_SECONDS: int = 120      # Intervalo entre ciclos (modo anti-bloqueo equilibrado)

# Usar paths centralizados desde config (respeta P2P_DATA_DIR env var)
from .config import DB_PATH, LOG_DIR  # noqa: E402
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            os.path.join(LOG_DIR, "worker.log"),
            maxBytes=10_485_760,  # 10 MB
            backupCount=5,
        ),
    ],
)
logger = logging.getLogger("p2p_worker")

# ─── Helpers ──────────────────────────────────────────────────────────────────
def _map_bank(name):
    if name in PRIMARY_BANKS_VES:
        return name
    return "Otros Bancos"


# ─── Señales para detención limpia ───────────────────────────────────────────
_running = True


def _handle_signal(signum, frame):
    global _running
    logger.info(f"Señal recibida ({signum}). Deteniendo worker...")
    _running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ─── Conexión a la DB (nueva por ciclo, SIN check_same_thread) ──────────────
# NOTA: worker es single-threaded → NO usar check_same_thread=False.
# Esa flag es solo para Streamlit (multi-threaded).
def _get_conn():
    return init_db(DB_PATH, cleanup=False, worker_mode=True)


# ─── Ciclo principal ────────────────────────────────────────────────────────
def run_collection_cycle(min_amount: float = 0.0) -> bool:
    """
    Ejecuta un ciclo completo de recolección:
      1. Fetch global BUY y SELL
      2. Agrupar por banco, calcular métricas
      3. Guardar snapshots individuales + global
    Retorna True si se obtuvieron datos, False si falló.
    """
    cycle_start = time.time()
    now = now_venezuela()
    logger.info(f"═══ Ciclo de recolección: {now.strftime('%H:%M:%S')} VET ═══")

    conn = _get_conn()
    try:
        # 1. Fetch global paralelo: BUY + SELL + merchant en asyncio.gather
        async def _fetch_all():
            buy_task = asyncio.to_thread(fetch_ads_global, "BUY", min_amount)
            sell_task = asyncio.to_thread(fetch_ads_global, "SELL", min_amount)
            merch_task = asyncio.to_thread(fetch_ads_merchant, "BUY")
            results = await asyncio.gather(buy_task, sell_task, merch_task, return_exceptions=True)
            return results

        fetch_results = _run_async(_fetch_all())
        buy_res, sell_res, merch_res = fetch_results[0], fetch_results[1], fetch_results[2]

        if isinstance(buy_res, Exception):
            buy_ads, buy_err, buy_ok, buy_ad_count = [], str(buy_res), False, 0
        else:
            buy_ads, buy_err, buy_ok, buy_ad_count = buy_res
        if isinstance(sell_res, Exception):
            sell_ads, sell_err, sell_ok, sell_ad_count = [], str(sell_res), False, 0
        else:
            sell_ads, sell_err, sell_ok, sell_ad_count = sell_res
        merch_ok = False
        merch_ads = []
        merch_err = None
        if not isinstance(merch_res, Exception):
            merch_ads, merch_err, merch_ok = merch_res

        if not buy_ok and not sell_ok:
            logger.error(
                f"Fallo en ambos lados. Buy: {buy_err or 'desconocido'}, "
                f"Sell: {sell_err or 'desconocido'}"
            )
            return False

        if not buy_ok:
            logger.warning(f"BUY fetch falló: {buy_err} — procesando solo SELL")
        if not sell_ok:
            logger.warning(f"SELL fetch falló: {sell_err} — procesando solo BUY")

        logger.info(f"Anuncios obtenidos: BUY={len(buy_ads)}, SELL={len(sell_ads)} (raw: {buy_ad_count}/{sell_ad_count})")

        # 2. Agrupar por banco

        banks_found: set = set()
        for ad in buy_ads + sell_ads:
            bank_name = _map_bank(ad.get("bank", ""))
            ad["bank"] = bank_name
            if bank_name:
                banks_found.add(bank_name)

        # Asegurar que todos los PRIMARY_BANKS_VES se procesen (incluso si no aparecen en datos globales)
        for bank in PRIMARY_BANKS_VES:
            banks_found.add(bank)

        snapshot_count = 0
        for bank in sorted(banks_found):
            bank_buy = [a for a in buy_ads if a.get("bank") == bank]
            bank_sell = [a for a in sell_ads if a.get("bank") == bank]

            # Fallback: si no hay datos de este banco en los datos globales, hacer fetch directo
            if not bank_sell and bank in PRIMARY_BANKS_VES:
                extra, err, ok = fetch_ads_bank(bank, "SELL", min_amount)
                if ok and extra:
                    bank_sell = extra
                    logger.info(f"Fallback SELL {bank}: +{len(extra)} ads")
            if not bank_buy and bank in PRIMARY_BANKS_VES:
                extra, err, ok = fetch_ads_bank(bank, "BUY", min_amount)
                if ok and extra:
                    bank_buy = extra
                    logger.info(f"Fallback BUY {bank}: +{len(extra)} ads")

            # Saltar si no hay datos después del fallback
            if not bank_buy and not bank_sell:
                continue

            # Ordenar: BUY → DESC (mejor precio para vendedor = más alto), SELL → ASC (mejor precio para comprador = más bajo)
            bank_buy.sort(key=lambda a: a["price"], reverse=True)
            bank_sell.sort(key=lambda a: a["price"])

            # Capturar TRUE best antes de cualquier filtro (precio real del mercado)
            true_best_buy = bank_buy[0]["price"] if bank_buy else None
            true_best_sell = bank_sell[0]["price"] if bank_sell else None

            # Aplicar SKIP_FIRST_N por banco (eliminar los N mejores, potenciales outliers)
            bank_buy = bank_buy[SKIP_FIRST_N:] if len(bank_buy) > SKIP_FIRST_N else bank_buy
            bank_sell = bank_sell[SKIP_FIRST_N:] if len(bank_sell) > SKIP_FIRST_N else bank_sell

            # Aplicar filtro IQR: BUY → elimina outliers bajos, SELL → elimina outliers altos
            bank_buy = filter_outliers_iqr(bank_buy, key="price", multiplier=OUTLIER_IQR_MULTIPLIER, side="buy")
            bank_sell = filter_outliers_iqr(bank_sell, key="price", multiplier=OUTLIER_IQR_MULTIPLIER, side="sell")

            metrics = compute_all_metrics(bank_buy, bank_sell,
                                           true_best_buy=true_best_buy,
                                           true_best_sell=true_best_sell)
            ad_count_buy = len(bank_buy)
            ad_count_sell = len(bank_sell)
            # Las cuentas se pasan como kwargs a insert_snapshot;
            # no se anaden al dict metrics (insert_snapshot no las lee de ahi).

            # Filtrar bancos con pocos ads (datos poco confiables, ej: precio 37 de Banesco)
            if ad_count_buy < MIN_BANK_SNAPSHOT_ADS or ad_count_sell < MIN_BANK_SNAPSHOT_ADS:
                logger.warning(
                    f"Snapshot {bank}: pocos ads "
                    f"(buy={ad_count_buy}, sell={ad_count_sell}), "
                    f"mínimo {MIN_BANK_SNAPSHOT_ADS}, omitido"
                )
                continue

            if metrics["best_buy"] is None or metrics["best_sell"] is None:
                logger.warning(
                    f"Snapshot incompleto para {bank} "
                    f"(buy={metrics['best_buy']}, sell={metrics['best_sell']}), omitido"
                )
                continue

            try:
                insert_snapshot(conn, bank, metrics, ad_count_buy=ad_count_buy, ad_count_sell=ad_count_sell)
                snapshot_count += 1
            except Exception as e:
                logger.error(f"Error guardando snapshot para {bank}: {e}")

        logger.info(f"Snapshots guardados: {snapshot_count} bancos")

        # Snapshot global (filtrando outliers antes del VWAP)
        buy_ads_clean = filter_outliers_iqr(buy_ads, side="buy") if buy_ads else []
        sell_ads_clean = filter_outliers_iqr(sell_ads, side="sell") if sell_ads else []
        if len(buy_ads_clean) < MIN_GLOBAL_SNAPSHOT_ADS or len(sell_ads_clean) < MIN_GLOBAL_SNAPSHOT_ADS:
            logger.warning(
                f"Snapshot global: pocos ads tras filtro "
                f"(buy={len(buy_ads_clean)}, sell={len(sell_ads_clean)}), "
                f"no se guarda snapshot global este ciclo"
            )
        else:
            g_vwap_buy = compute_vwap(buy_ads_clean)
            g_vwap_sell = compute_vwap(sell_ads_clean)
            g_acc_buy = compute_accumulated_volume(buy_ads_clean)
            g_acc_sell = compute_accumulated_volume(sell_ads_clean)

            if g_vwap_buy is not None and g_vwap_sell is not None:
                g_mid_price = (g_vwap_buy + g_vwap_sell) / 2
                try:
                    insert_global_snapshot(
                        conn, g_vwap_buy, g_vwap_sell,
                        g_mid_price, g_acc_buy, g_acc_sell,
                    )
                    logger.info(
                        f"Global: VWAP Buy={g_vwap_buy:.2f}, VWAP Sell={g_vwap_sell:.2f}, "
                        f"Mid={g_mid_price:.2f}, Vol={g_acc_buy+g_acc_sell:.0f} USDT"
                    )
                except Exception as e:
                    logger.error(f"Error guardando snapshot global: {e}")

        # 3. Merchant ads (ya fetcheado en paralelo arriba)
        if isinstance(merch_res, Exception):
            logger.warning(f"Merchant ads falló (no crítico): {merch_res}")
        elif merch_ok and merch_ads:
            try:
                insert_ads_snapshot(conn, "BUY", merch_ads)
                logger.info(f"Anuncios merchant guardados: {len(merch_ads)}")
            except Exception as e:
                logger.warning(f"Insert merchant ads falló: {e}")
        elif merch_err:
            logger.warning(f"Merchant ads fetch: {merch_err}")

        elapsed = time.time() - cycle_start
        logger.info(f"Ciclo completado en {elapsed:.1f}s")
        return True
    except Exception as e:
        logger.error(f"Error en ciclo: {e}")
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ─── Ciclo Zinli (USDT/USD) ───────────────────────────────────────────────────
def run_zinli_cycle(min_amount: float = 0.0) -> bool:
    """
    Ejecuta ciclo de recolección para mercado Zinli (USDT/USD).
    Fetch BUY + SELL con payType=Zinli, calcula métricas, guarda en p2p_history_zinli.
    """
    cycle_start = time.time()
    now = now_venezuela()
    logger.info(f"═══ Ciclo Zinli: {now.strftime('%H:%M:%S')} VET ═══")

    conn = _get_conn()
    try:
        # Fetch Zinli BUY y SELL
        async def _fetch_zinli():
            buy_task = asyncio.to_thread(fetch_ads_global, "BUY", min_amount, asset=ZINLI_ASSET, fiat=ZINLI_FIAT, pay_types=[ZINLI_PAYTYPE])
            sell_task = asyncio.to_thread(fetch_ads_global, "SELL", min_amount, asset=ZINLI_ASSET, fiat=ZINLI_FIAT, pay_types=[ZINLI_PAYTYPE])
            results = await asyncio.gather(buy_task, sell_task, return_exceptions=True)
            return results

        fetch_results = _run_async(_fetch_zinli())
        buy_res, sell_res = fetch_results[0], fetch_results[1]

        if isinstance(buy_res, Exception):
            buy_ads, buy_err, buy_ok, buy_ad_count = [], str(buy_res), False, 0
        else:
            buy_ads, buy_err, buy_ok, buy_ad_count = buy_res
        if isinstance(sell_res, Exception):
            sell_ads, sell_err, sell_ok, sell_ad_count = [], str(sell_res), False, 0
        else:
            sell_ads, sell_err, sell_ok, sell_ad_count = sell_res

        if not buy_ok and not sell_ok:
            logger.error(f"Zinli fallo ambos lados. Buy: {buy_err or 'desconocido'}, Sell: {sell_err or 'desconocido'}")
            return False

        if not buy_ok:
            logger.warning(f"Zinli BUY falló: {buy_err}")
        if not sell_ok:
            logger.warning(f"Zinli SELL falló: {sell_err}")

        logger.info(f"Zinli anuncios: BUY={len(buy_ads)}, SELL={len(sell_ads)} (raw: {buy_ad_count}/{sell_ad_count})")

        if not buy_ads and not sell_ads:
            logger.warning("Zinli: sin datos, omitiendo snapshot")
            return False

        # Marcar banco como Zinli para consistencia
        for ad in buy_ads + sell_ads:
            ad["bank"] = "Zinli"

        # Ordenar
        buy_ads.sort(key=lambda a: a["price"], reverse=True)
        sell_ads.sort(key=lambda a: a["price"])

        # True best antes de filtros
        true_best_buy = buy_ads[0]["price"] if buy_ads else None
        true_best_sell = sell_ads[0]["price"] if sell_ads else None

        # SKIP_FIRST_N
        buy_ads = buy_ads[SKIP_FIRST_N:] if len(buy_ads) > SKIP_FIRST_N else buy_ads
        sell_ads = sell_ads[SKIP_FIRST_N:] if len(sell_ads) > SKIP_FIRST_N else sell_ads

        # IQR filter
        buy_ads = filter_outliers_iqr(buy_ads, key="price", multiplier=OUTLIER_IQR_MULTIPLIER, side="buy")
        sell_ads = filter_outliers_iqr(sell_ads, key="price", multiplier=OUTLIER_IQR_MULTIPLIER, side="sell")

        # Métricas
        metrics = compute_all_metrics(buy_ads, sell_ads,
                                       true_best_buy=true_best_buy,
                                       true_best_sell=true_best_sell)
        ad_count_buy = len(buy_ads)
        ad_count_sell = len(sell_ads)

        # Validar mínimo
        if ad_count_buy < MIN_BANK_SNAPSHOT_ADS or ad_count_sell < MIN_BANK_SNAPSHOT_ADS:
            logger.warning(f"Zinli: pocos ads (buy={ad_count_buy}, sell={ad_count_sell}), mínimo {MIN_BANK_SNAPSHOT_ADS}, omitido")
            return False

        if metrics["best_buy"] is None or metrics["best_sell"] is None:
            logger.warning(f"Zinli: snapshot incompleto (buy={metrics['best_buy']}, sell={metrics['best_sell']}), omitido")
            return False

        try:
            insert_zinli_snapshot(conn, metrics, ad_count_buy=ad_count_buy, ad_count_sell=ad_count_sell)
            logger.info(f"Zinli: snapshot guardado — Buy={metrics['best_buy']:.4f}, Sell={metrics['best_sell']:.4f}, VWAP Buy={metrics['vwap_buy']:.4f}, VWAP Sell={metrics['vwap_sell']:.4f}, Spread={metrics['spread']:.4f}")
        except Exception as e:
            logger.error(f"Zinli error guardando snapshot: {e}")
            return False

        elapsed = time.time() - cycle_start
        logger.info(f"Ciclo Zinli completado en {elapsed:.1f}s")
        return True
    except Exception as e:
        logger.error(f"Zinli error en ciclo: {e}")
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    logger.info("╔══════════════════════════════════════════╗")
    logger.info("║   P2P Sentinel Pro — Worker iniciado     ║")
    logger.info(f"║   Intervalo: {WORKER_INTERVAL_SECONDS}s | DB: {DB_PATH}     ║")
    logger.info(f"║   Páginas: {NUM_PAGES} x {ROWS_PER_PAGE}                            ║")
    logger.info("╚══════════════════════════════════════════╝")

    consecutive_failures = 0
    max_failures = 5
    cycle_count = 0
    last_cycle_error: Optional[str] = None

    while _running:
        cycle_start = time.time()
        last_cycle_error = None
        try:
            success = run_collection_cycle()
            zinli_success = run_zinli_cycle()
            if success and zinli_success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    extra_sleep = int(WORKER_INTERVAL_SECONDS * (2 ** min(consecutive_failures - max_failures + 1, 4)))
                    logger.warning(
                        f"⚠ {consecutive_failures} fallos consecutivos. "
                        f"Esperando {extra_sleep}s extra..."
                    )
                    deadline = time.time() + extra_sleep
                    while time.time() < deadline:
                        if not _running:
                            break
                        time.sleep(min(5, deadline - time.time()))

        except Exception as e:
            logger.exception(f"Error inesperado en ciclo: {e}")
            consecutive_failures += 1
            last_cycle_error = str(e)

        # Incrementar ANTES del heartbeat para que el conteo sea consistente
        cycle_count += 1

        # Heartbeat: insertar timestamp cada ciclo
        hb_conn = None
        try:
            hb_conn = init_db(DB_PATH)
            upsert_worker_heartbeat(
                hb_conn, status="error" if consecutive_failures > 0 else "ok",
                cycle_count=cycle_count,
                last_error=last_cycle_error,
            )
        except Exception as hb_err:
            logger.warning(f"Heartbeat falló: {hb_err}")
        finally:
            if hb_conn is not None:
                try:
                    hb_conn.close()
                except Exception:
                    pass

        # WAL checkpoint cada ~60 ciclos (~1 hora) para evitar crecimiento infinito
        if cycle_count % 60 == 0:
            ck_conn = None
            try:
                ck_conn = _get_conn()
                _checkpoint_wal(ck_conn)
            except Exception as e:
                logger.warning(f"WAL checkpoint falló: {e}")
            finally:
                if ck_conn is not None:
                    try:
                        ck_conn.close()
                    except Exception:
                        pass

        # Limpieza de datos antiguos cada ~1440 ciclos (~24 horas)
        if cycle_count % 1440 == 0:
            cl_conn = None
            try:
                cl_conn = _get_conn()
                deleted = cleanup_old_data(cl_conn)
                if deleted:
                    logger.info(f"Cleanup completado: {deleted} filas eliminadas")
            except Exception as e:
                logger.warning(f"Cleanup falló: {e}")
            finally:
                if cl_conn is not None:
                    try:
                        cl_conn.close()
                    except Exception:
                        pass

        # Esperar el intervalo (descontando lo que ya tomó el ciclo), verificando _running
        elapsed = time.time() - cycle_start
        remaining = max(1, WORKER_INTERVAL_SECONDS - int(elapsed))
        for _ in range(remaining):
            if not _running:
                break
            time.sleep(1)



def _checkpoint_wal(conn):
    """Hace WAL checkpoint cada hora (cada ~60 ciclos) para evitar crecimiento infinito."""
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as e:
        logger.warning(f"WAL checkpoint falló: {e}")


if __name__ == "__main__":
    main()
