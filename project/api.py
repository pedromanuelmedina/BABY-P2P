"""
api.py — Servidor FastAPI para feed AJAX del dashboard.

Provee endpoints JSON que el frontend polla cada 60s sin recargar la página.
Lee SQLite en modo read-only. No afecta al worker.

Puerto: 8080
Uso:    python3 api.py  (o vía start_v2.sh --bg)
"""

import logging
import os
from typing import Any, Dict, List

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .database import (
    init_db,
    get_history,
    get_global_history,
    get_ads_by_trade_type,
    get_worker_heartbeat,
    get_distinct_banks,
    get_latest_volumes_by_bank,
)

from .config import DB_PATH as _CONFIG_DB_PATH  # noqa: E402

logger = logging.getLogger("p2p_api")

_VALID_TRADE_TYPES = {"BUY", "SELL"}

DB_PATH = _CONFIG_DB_PATH

app = FastAPI(title="P2P Sentinel API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _conn():
    return init_db(DB_PATH, read_only=True)


def _df_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    df = df.copy()
    if "timestamp" in df.columns:
        df["timestamp"] = df["timestamp"].astype(str)
    return df.to_dict("records")


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/heartbeat")
def heartbeat() -> Dict[str, Any]:
    with _conn() as conn:
        hb = get_worker_heartbeat(conn)
    if hb is None:
        return {"status": "no_data", "cycle_count": 0, "last_error": None, "timestamp": None}
    return hb


@app.get("/api/banks")
def banks() -> Dict[str, Any]:
    with _conn() as conn:
        return {"banks": get_distinct_banks(conn)}


@app.get("/api/latest")
def latest(
    bank: str = Query("Mercado Global", description="Nombre del banco o 'Mercado Global'"),
    limit: int = Query(1, ge=1, le=10),
) -> Dict[str, Any]:
    """Retorna las últimas N filas de historial para un banco o el mercado global."""
    with _conn() as conn:
        if bank == "Mercado Global":
            df = get_global_history(conn, limit=limit)
        else:
            df = get_history(conn, bank, limit=limit)
    records = _df_to_records(df)
    if not records:
        raise HTTPException(status_code=404, detail=f"No data for bank: {bank}")
    return {"bank": bank, "rows": records}


@app.get("/api/history")
def history(
    bank: str = Query("Mercado Global"),
    limit: int = Query(5000, ge=1, le=10000),
) -> Dict[str, Any]:
    """Historial completo para alimentar el gráfico LWC."""
    with _conn() as conn:
        if bank == "Mercado Global":
            df = get_global_history(conn, limit=limit)
        else:
            df = get_history(conn, bank, limit=limit)
    return {"bank": bank, "data": _df_to_records(df)}


@app.get("/api/ads")
def ads(
    trade_type: str = Query("BUY"),
    min_volume: float = Query(0.0, ge=0),
) -> Dict[str, Any]:
    trade_type = trade_type.upper()
    if trade_type not in _VALID_TRADE_TYPES:
        raise HTTPException(status_code=400, detail=f"trade_type must be one of {_VALID_TRADE_TYPES}")
    with _conn() as conn:
        rows = get_ads_by_trade_type(conn, trade_type, min_volume=min_volume)
    return {"trade_type": trade_type, "count": len(rows), "ads": rows}


@app.get("/api/watchlist")
def watchlist(limit: int = Query(20, ge=1, le=200)) -> Dict[str, Any]:
    """Datos para la watchlist: global + todos los bancos con su último precio."""
    with _conn() as conn:
        global_df = get_global_history(conn, limit=limit)
        bank_list = get_distinct_banks(conn)
        bank_data: Dict[str, Any] = {}
        for b in bank_list:
            bdf = get_history(conn, b, limit=limit)
            if not bdf.empty:
                last = bdf.iloc[-1]
                buy = last.get("vwap_buy")
                sell = last.get("vwap_sell")
                buy = buy if (buy is not None and not pd.isna(buy)) else 0
                sell = sell if (sell is not None and not pd.isna(sell)) else 0
                mid = (buy + sell) / 2 if (buy and sell) else (buy or sell)
                mid_values = bdf[["vwap_buy", "vwap_sell"]].mean(axis=1).dropna().tolist()
                bank_data[b] = {
                    "price": float(mid) if mid else 0.0,
                    "sparkline": mid_values[-10:],
                }
        global_price = 0.0
        global_spark: List[float] = []
        if not global_df.empty:
            gp = global_df.iloc[-1].get("vwap_sell_global")
            gp = gp if (gp is not None and not pd.isna(gp)) else 0.0
            global_price = float(gp)
            if "vwap_sell_global" in global_df.columns:
                global_spark = global_df["vwap_sell_global"].dropna().tolist()[-10:]
    return {
        "global": {"price": global_price, "sparkline": global_spark},
        "banks": bank_data,
    }


@app.get("/api/volumes")
def volumes() -> Dict[str, Any]:
    """Volumen latest por banco para el gráfico de barras."""
    with _conn() as conn:
        rows = get_latest_volumes_by_bank(conn)
    return {"banks": rows}


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", 8080))
    uvicorn.run(app, host=host, port=port, log_level="warning")
