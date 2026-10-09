"""
metrics.py — Cálculos cuantitativos: VWAP, Spread, Volumen Acumulado, Desviación de Liquidez.
"""

from typing import Dict, List, Optional

import numpy as np  # nuevo (I4.04: cuartiles con interpolacion lineal)
from ._types import AdRecord  # antes: from scraper import AdRecord (acoplamiento)
from .config import OUTLIER_IQR_MULTIPLIER


def compute_accumulated_volume(ads: List[AdRecord]) -> float:
    return sum(ad["volume"] for ad in ads)


def compute_vwap(ads: List[AdRecord]) -> Optional[float]:
    if not ads:
        return None
    total_volume = sum(ad["volume"] for ad in ads)
    if total_volume == 0.0:
        return None
    price_times_volume = sum(ad["price"] * ad["volume"] for ad in ads)
    return price_times_volume / total_volume


def compute_spread(best_buy: float, best_sell: float) -> float:
    """Calcula el spread como la diferencia entre el precio de venta y el de compra.
    En el contexto de USDT, el spread representa cuánto más caro es vender USDT
    respecto a comprarlo (SELL - BUY). No se usa valor absoluto para preservar
    la dirección del spread."""
    return best_sell - best_buy


def compute_liquidity_deviation(best_price: float, vwap: Optional[float]) -> Optional[float]:
    if vwap is None or best_price == 0.0:
        return None
    return abs(best_price - vwap) / best_price * 100.0


def filter_outliers_iqr(
    ads: List[AdRecord],
    key: str = "price",
    multiplier: float = OUTLIER_IQR_MULTIPLIER,
    side: str = "buy",
) -> List[AdRecord]:
    """Elimina outliers usando IQR.
    
    Args:
        ads: Lista de anuncios.
        key: Campo a filtrar (default "price").
        multiplier: Multiplicador IQR (default OUTLIER_IQR_MULTIPLIER).
        side: "buy" → elimina outliers BAJOS (precios anómalamente bajos, likely bait).
              "sell" → elimina outliers ALTOS (precios anómalamente altos, likely bait).
    
    Returns:
        Lista filtrada sin outliers en el lado indicado.
    """
    if len(ads) < 4:
        return ads

    prices = [a[key] for a in ads]
    # I4.04: numpy.percentile usa interpolacion lineal (Tukey estandar).
    # Antes: prices_sorted[n // 4] era una aproximacion burda.
    quartiles: List[float] = [float(x) for x in np.percentile(prices, [25, 75])]  # type: ignore[attr-defined]
    q1: float = quartiles[0]
    q3: float = quartiles[1]
    iqr = q3 - q1

    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr

    if side == "buy":
        return [a for a in ads if a[key] >= lower]
    return [a for a in ads if a[key] <= upper]


def compute_all_metrics(
    buy_ads: List[AdRecord],
    sell_ads: List[AdRecord],
    true_best_buy: Optional[float] = None,
    true_best_sell: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    best_buy: Optional[float] = buy_ads[0]["price"] if buy_ads else None
    best_sell: Optional[float] = sell_ads[0]["price"] if sell_ads else None
    vwap_buy: Optional[float] = compute_vwap(buy_ads)
    vwap_sell: Optional[float] = compute_vwap(sell_ads)
    acc_vol_buy: float = compute_accumulated_volume(buy_ads)
    acc_vol_sell: float = compute_accumulated_volume(sell_ads)
    spread: Optional[float] = None
    if best_buy is not None and best_sell is not None:
        spread = compute_spread(best_buy, best_sell)
    liq_dev_buy: Optional[float] = None
    liq_dev_sell: Optional[float] = None
    if best_buy is not None:
        liq_dev_buy = compute_liquidity_deviation(best_buy, vwap_buy)
    if best_sell is not None:
        liq_dev_sell = compute_liquidity_deviation(best_sell, vwap_sell)

    # true_best_* captura el mejor precio ANTES de skip/IQR
    if true_best_buy is None:
        true_best_buy = best_buy
    if true_best_sell is None:
        true_best_sell = best_sell

    return {
        "best_buy": best_buy, "best_sell": best_sell,
        "true_best_buy": true_best_buy, "true_best_sell": true_best_sell,
        "vwap_buy": vwap_buy, "vwap_sell": vwap_sell,
        "spread": spread,
        "acc_vol_buy": acc_vol_buy, "acc_vol_sell": acc_vol_sell,
        "liq_dev_buy": liq_dev_buy, "liq_dev_sell": liq_dev_sell,
    }
