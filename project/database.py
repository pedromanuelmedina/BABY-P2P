"""
database.py — Capa de persistencia SQLite.
"""

import re
import sqlite3
import logging
from datetime import timedelta
from typing import Dict

import pandas as pd

from .config import now_venezuela, now_venezuela_str

logger = logging.getLogger(__name__)

# ─── Tablas ──────────────────────────────────────────────────────────────────
P2P_ADS_TABLE_NAME: str = "p2p_ads"
P2P_ADS_COLUMNS: Dict[str, str] = {
    "trade_type": "TEXT NOT NULL",
    "nickname": "TEXT NOT NULL",
    "price": "REAL",
    "volume": "REAL",
    "bank": "TEXT",
    "min_amount": "REAL DEFAULT 0",
    "max_amount": "REAL DEFAULT 0",
    "month_finish": "REAL DEFAULT 0",
    "month_order": "INTEGER DEFAULT 0",
    "merchant_id": "INTEGER DEFAULT 0",
    "user_no": "INTEGER DEFAULT 0",
    "fiat": "TEXT DEFAULT ''",
    "fetched_at": "TEXT NOT NULL",
}

def _db_execute(conn: sqlite3.Connection, name: str, operation_fn, on_fail: str = 'raise'):
    """Ejecuta operation_fn con manejo de errores uniforme."""
    try:
        return operation_fn()
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        logger.warning(f"{name} falló: {e}")
        if on_fail == 'raise':
            raise
        return None


_VALID_IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

def _validate_identifier(name: str) -> str:
    if not name or not _VALID_IDENTIFIER.match(name):
        raise ValueError(f"Identificador SQL inválido: {name!r}")
    return name

# ─── Schema ──────────────────────────────────────────────────────────────────
REQUIRED_COLUMNS: Dict[str, str] = {
    "timestamp": "DATETIME",
    "bank": "TEXT",
    "best_buy": "REAL",
    "best_sell": "REAL",
    "true_best_buy": "REAL",
    "true_best_sell": "REAL",
    "spread": "REAL",
    "acc_vol_buy": "REAL",
    "acc_vol_sell": "REAL",
    "vwap_buy": "REAL",
    "vwap_sell": "REAL",
    "liq_dev_buy": "REAL",
    "liq_dev_sell": "REAL",
    "ad_count_buy": "INTEGER",
    "ad_count_sell": "INTEGER",
}

TABLE_NAME: str = "p2p_history"

GLOBAL_TABLE_NAME: str = "global_p2p_history"
GLOBAL_REQUIRED_COLUMNS: Dict[str, str] = {
    "timestamp": "DATETIME",
    "vwap_buy_global": "REAL",
    "vwap_sell_global": "REAL",
    "mid_price_global": "REAL",
    "total_vol_buy": "REAL",
    "total_vol_sell": "REAL",
}

# ─── Zinli (USDT/USD) ──────────────────────────────────────────────────────────
ZINLI_TABLE_NAME: str = "p2p_history_zinli"
ZINLI_REQUIRED_COLUMNS: Dict[str, str] = {
    "timestamp": "DATETIME",
    "best_buy": "REAL",
    "best_sell": "REAL",
    "true_best_buy": "REAL",
    "true_best_sell": "REAL",
    "spread": "REAL",
    "acc_vol_buy": "REAL",
    "acc_vol_sell": "REAL",
    "vwap_buy": "REAL",
    "vwap_sell": "REAL",
    "liq_dev_buy": "REAL",
    "liq_dev_sell": "REAL",
    "ad_count_buy": "INTEGER",
    "ad_count_sell": "INTEGER",
}

# ─── Índices ─────────────────────────────────────────────────────────────────
def _ensure_indexes(conn: sqlite3.Connection) -> None:
    safe_p2p = _validate_identifier(TABLE_NAME)
    safe_global = _validate_identifier(GLOBAL_TABLE_NAME)
    safe_zinli = _validate_identifier(ZINLI_TABLE_NAME)
    for idx in [
        f"CREATE INDEX IF NOT EXISTS idx_{safe_p2p}_bank ON {safe_p2p}(bank);",
        f"CREATE INDEX IF NOT EXISTS idx_{safe_p2p}_bank_ts ON {safe_p2p}(bank, timestamp);",
        f"CREATE INDEX IF NOT EXISTS idx_{safe_p2p}_ts ON {safe_p2p}(timestamp);",
        f"CREATE INDEX IF NOT EXISTS idx_{safe_global}_timestamp ON {safe_global}(timestamp);",
        f"CREATE INDEX IF NOT EXISTS idx_{safe_zinli}_ts ON {safe_zinli}(timestamp);",
    ]:
        conn.execute(idx)
    conn.commit()
    try:
        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{safe_p2p}_unique_ts_bank ON {safe_p2p}(timestamp, bank);")
    except Exception:
        conn.execute(f"DELETE FROM {safe_p2p} WHERE id NOT IN (SELECT MIN(id) FROM {safe_p2p} GROUP BY timestamp, bank)")
        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{safe_p2p}_unique_ts_bank ON {safe_p2p}(timestamp, bank);")
    try:
        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{safe_global}_unique_ts ON {safe_global}(timestamp);")
    except Exception:
        conn.execute(f"DELETE FROM {safe_global} WHERE id NOT IN (SELECT MIN(id) FROM {safe_global} GROUP BY timestamp)")
        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{safe_global}_unique_ts ON {safe_global}(timestamp);")
    try:
        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{safe_zinli}_unique_ts ON {safe_zinli}(timestamp);")
    except Exception:
        conn.execute(f"DELETE FROM {safe_zinli} WHERE id NOT IN (SELECT MIN(id) FROM {safe_zinli} GROUP BY timestamp)")
        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{safe_zinli}_unique_ts ON {safe_zinli}(timestamp);")
    conn.commit()


def _create_ads_table_if_not_exists(conn: sqlite3.Connection) -> None:
    safe_table = _validate_identifier(P2P_ADS_TABLE_NAME)
    columns_def = ", ".join(f"{_validate_identifier(col_name)} {col_type}" for col_name, col_type in P2P_ADS_COLUMNS.items())
    conn.execute(f"CREATE TABLE IF NOT EXISTS {safe_table} (id INTEGER PRIMARY KEY AUTOINCREMENT, {columns_def});")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{safe_table}_trade_type ON {safe_table}(trade_type);")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{safe_table}_fetched_at ON {safe_table}(fetched_at DESC);")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{safe_table}_trade_price ON {safe_table}(trade_type, price);")
    conn.commit()


def init_db(db_path: str = "p2p_sentinel.db", cleanup: bool = False, worker_mode: bool = False, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.execute("PRAGMA cache_size=-64000;")
        conn.row_factory = sqlite3.Row
        return conn

    if worker_mode:
        conn = sqlite3.connect(db_path, check_same_thread=True)
    else:
        conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA cache_size=-64000;")
    conn.row_factory = sqlite3.Row

    safe_table = _validate_identifier(TABLE_NAME)
    columns_def = ", ".join(f"{_validate_identifier(col_name)} {col_type}" for col_name, col_type in REQUIRED_COLUMNS.items())
    conn.execute(f"CREATE TABLE IF NOT EXISTS {safe_table} (id INTEGER PRIMARY KEY AUTOINCREMENT, {columns_def});")
    conn.commit()

    existing = [row["name"] for row in conn.execute(f"PRAGMA table_info({safe_table});").fetchall()]
    for col_name, col_type in REQUIRED_COLUMNS.items():
        if col_name not in existing:
            conn.execute(f"ALTER TABLE {safe_table} ADD COLUMN {_validate_identifier(col_name)} {col_type};")
    conn.commit()

    safe_global = _validate_identifier(GLOBAL_TABLE_NAME)
    gcols = ", ".join(f"{_validate_identifier(col_name)} {col_type}" for col_name, col_type in GLOBAL_REQUIRED_COLUMNS.items())
    conn.execute(f"CREATE TABLE IF NOT EXISTS {safe_global} (id INTEGER PRIMARY KEY AUTOINCREMENT, {gcols});")
    conn.commit()

    safe_zinli = _validate_identifier(ZINLI_TABLE_NAME)
    zcols = ", ".join(f"{_validate_identifier(col_name)} {col_type}" for col_name, col_type in ZINLI_REQUIRED_COLUMNS.items())
    conn.execute(f"CREATE TABLE IF NOT EXISTS {safe_zinli} (id INTEGER PRIMARY KEY AUTOINCREMENT, {zcols});")
    conn.commit()

    _create_ads_table_if_not_exists(conn)

    safe_hb = _validate_identifier("worker_heartbeat")
    conn.execute(f"CREATE TABLE IF NOT EXISTS {safe_hb} (id INTEGER PRIMARY KEY DEFAULT 1, timestamp DATETIME NOT NULL, status TEXT NOT NULL DEFAULT 'ok', cycle_count INTEGER DEFAULT 0, last_error TEXT, CHECK(id = 1));")
    conn.commit()
    _ensure_indexes(conn)

    if cleanup:
        cutoff = (now_venezuela() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
        safe_ads_tbl = _validate_identifier(P2P_ADS_TABLE_NAME)
        for t, ts_col in [(safe_table, "timestamp"), (safe_global, "timestamp"), (safe_ads_tbl, "fetched_at")]:
            conn.execute(f"DELETE FROM {t} WHERE {ts_col} < ?", (cutoff,))
        conn.commit()

    return conn


# ─── Operaciones ─────────────────────────────────────────────────────────────
def insert_snapshot(conn, bank, metrics, ad_count_buy=None, ad_count_sell=None, timestamp=None):
    if timestamp is None:
        timestamp = now_venezuela_str()
    values = {
        "timestamp": timestamp, "bank": bank,
        "best_buy": metrics.get("best_buy"), "best_sell": metrics.get("best_sell"),
        "true_best_buy": metrics.get("true_best_buy"), "true_best_sell": metrics.get("true_best_sell"),
        "spread": metrics.get("spread"),
        "acc_vol_buy": metrics.get("acc_vol_buy"), "acc_vol_sell": metrics.get("acc_vol_sell"),
        "vwap_buy": metrics.get("vwap_buy"), "vwap_sell": metrics.get("vwap_sell"),
        "liq_dev_buy": metrics.get("liq_dev_buy"), "liq_dev_sell": metrics.get("liq_dev_sell"),
        "ad_count_buy": ad_count_buy, "ad_count_sell": ad_count_sell,
    }
    safe = _validate_identifier(TABLE_NAME)
    cols = ", ".join(_validate_identifier(k) for k in values)
    ph = ", ".join("?" for _ in values)
    def _do():
        conn.execute(f"INSERT OR REPLACE INTO {safe} ({cols}) VALUES ({ph})", list(values.values()))
        conn.commit()
    _db_execute(conn, "insert_snapshot", _do)


def get_history(conn, bank, limit=200):
    safe = _validate_identifier(TABLE_NAME)
    result = _db_execute(conn, "get_history", lambda: pd.read_sql_query(f"SELECT * FROM {safe} WHERE bank=? ORDER BY timestamp DESC LIMIT ?", conn, params=(bank, limit)))
    if result is None:
        return pd.DataFrame()
    df = result
    if df.empty:
        return df
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    ts = pd.to_datetime(df["timestamp"])
    try:
        df["timestamp"] = ts.dt.tz_localize("America/Caracas")
    except TypeError:
        df["timestamp"] = ts.dt.tz_convert("America/Caracas")
    return df


def insert_global_snapshot(conn, vwap_buy_global, vwap_sell_global, mid_price_global, total_vol_buy, total_vol_sell, timestamp=None):
    if timestamp is None:
        timestamp = now_venezuela_str()
    values = {"timestamp": timestamp, "vwap_buy_global": vwap_buy_global, "vwap_sell_global": vwap_sell_global, "mid_price_global": mid_price_global, "total_vol_buy": total_vol_buy, "total_vol_sell": total_vol_sell}
    safe = _validate_identifier(GLOBAL_TABLE_NAME)
    cols = ", ".join(_validate_identifier(k) for k in values)
    ph = ", ".join("?" for _ in values)
    def _do():
        conn.execute(f"INSERT OR REPLACE INTO {safe} ({cols}) VALUES ({ph})", list(values.values()))
        conn.commit()
    _db_execute(conn, "insert_global_snapshot", _do)


def get_global_history(conn, limit=200):
    safe = _validate_identifier(GLOBAL_TABLE_NAME)
    result = _db_execute(conn, "get_global_history", lambda: pd.read_sql_query(f"SELECT * FROM {safe} ORDER BY timestamp DESC LIMIT ?", conn, params=(limit,)))
    if result is None:
        return pd.DataFrame()
    df = result
    if df.empty:
        return df
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    ts = pd.to_datetime(df["timestamp"])
    try:
        df["timestamp"] = ts.dt.tz_localize("America/Caracas")
    except TypeError:
        df["timestamp"] = ts.dt.tz_convert("America/Caracas")
    return df


# ─── Zinli Operations ───────────────────────────────────────────────────────────
def insert_zinli_snapshot(conn, metrics, ad_count_buy=None, ad_count_sell=None, timestamp=None):
    if timestamp is None:
        timestamp = now_venezuela_str()
    values = {
        "timestamp": timestamp,
        "best_buy": metrics.get("best_buy"), "best_sell": metrics.get("best_sell"),
        "true_best_buy": metrics.get("true_best_buy"), "true_best_sell": metrics.get("true_best_sell"),
        "spread": metrics.get("spread"),
        "acc_vol_buy": metrics.get("acc_vol_buy"), "acc_vol_sell": metrics.get("acc_vol_sell"),
        "vwap_buy": metrics.get("vwap_buy"), "vwap_sell": metrics.get("vwap_sell"),
        "liq_dev_buy": metrics.get("liq_dev_buy"), "liq_dev_sell": metrics.get("liq_dev_sell"),
        "ad_count_buy": ad_count_buy, "ad_count_sell": ad_count_sell,
    }
    safe = _validate_identifier(ZINLI_TABLE_NAME)
    cols = ", ".join(_validate_identifier(k) for k in values)
    ph = ", ".join("?" for _ in values)
    def _do():
        conn.execute(f"INSERT OR REPLACE INTO {safe} ({cols}) VALUES ({ph})", list(values.values()))
        conn.commit()
    _db_execute(conn, "insert_zinli_snapshot", _do)


def get_zinli_history(conn, limit=200):
    safe = _validate_identifier(ZINLI_TABLE_NAME)
    result = _db_execute(conn, "get_zinli_history", lambda: pd.read_sql_query(f"SELECT * FROM {safe} ORDER BY timestamp DESC LIMIT ?", conn, params=(limit,)))
    if result is None:
        return pd.DataFrame()
    df = result
    if df.empty:
        return df
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    ts = pd.to_datetime(df["timestamp"])
    try:
        df["timestamp"] = ts.dt.tz_localize("America/Caracas")
    except TypeError:
        df["timestamp"] = ts.dt.tz_convert("America/Caracas")
    return df


def insert_ads_snapshot(conn, trade_type, ads):
    safe = _validate_identifier(P2P_ADS_TABLE_NAME)
    fetched_at = now_venezuela_str()
    columns = ["trade_type", "nickname", "price", "volume", "bank", "min_amount", "max_amount", "month_finish", "month_order", "merchant_id", "user_no", "fiat", "fetched_at"]
    safe_cols = ", ".join(_validate_identifier(c) for c in columns)
    ph = ", ".join("?" for _ in columns)
    def _do():
        conn.execute(f"DELETE FROM {safe} WHERE trade_type=?", (trade_type,))
        rows = [(trade_type, a.get("nickname",""), a.get("price"), a.get("volume"), a.get("bank"), a.get("min_amount",0), a.get("max_amount",0), a.get("month_finish",0), a.get("month_order",0), a.get("merchant_id",0), a.get("user_no",0), a.get("fiat",""), fetched_at) for a in ads]
        conn.executemany(f"INSERT INTO {safe} ({safe_cols}) VALUES ({ph})", rows)
        conn.commit()
        return len(ads)
    return _db_execute(conn, "insert_ads_snapshot", _do) or 0


def get_ads_by_trade_type(conn, trade_type, min_volume=0.0):
    safe = _validate_identifier(P2P_ADS_TABLE_NAME)
    def _do():
        order = "ASC" if trade_type == "BUY" else "DESC"
        if min_volume > 0:
            df = pd.read_sql_query(f"SELECT * FROM {safe} WHERE trade_type=? AND volume>=? ORDER BY price {order}", conn, params=(trade_type, min_volume))
        else:
            df = pd.read_sql_query(f"SELECT * FROM {safe} WHERE trade_type=? ORDER BY price {order}", conn, params=(trade_type,))
        return [] if df.empty else df.to_dict("records")
    return _db_execute(conn, "get_ads_by_trade_type", _do) or []


def upsert_worker_heartbeat(conn, status="ok", cycle_count=0, last_error=None):
    safe = _validate_identifier("worker_heartbeat")
    ts = now_venezuela_str()
    def _do():
        conn.execute(f"INSERT OR REPLACE INTO {safe} (id, timestamp, status, cycle_count, last_error) VALUES (1,?,?,?,?)", (ts, status, cycle_count, last_error))
        conn.commit()
    _db_execute(conn, "upsert_worker_heartbeat", _do)


def get_worker_heartbeat(conn):
    safe = _validate_identifier("worker_heartbeat")
    def _do():
        r = conn.execute(f"SELECT * FROM {safe} WHERE id=1").fetchone()
        return dict(r) if r else None
    return _db_execute(conn, "get_worker_heartbeat", _do)


def get_distinct_banks(conn):
    safe = _validate_identifier(TABLE_NAME)
    def _do():
        return [r["bank"] for r in conn.execute(f"SELECT DISTINCT bank FROM {safe} ORDER BY bank").fetchall()]
    return _db_execute(conn, "get_distinct_banks", _do) or []


def get_latest_volumes_by_bank(conn):
    safe = _validate_identifier(TABLE_NAME)
    def _do():
        return [dict(r) for r in conn.execute(f'SELECT bank, acc_vol_buy as "buy_vol", acc_vol_sell as "sell_vol" FROM {safe} WHERE id IN (SELECT MAX(id) FROM {safe} GROUP BY bank)').fetchall()]
    return _db_execute(conn, "get_latest_volumes_by_bank", _do) or []


def cleanup_old_data(conn, days_to_keep=90):
    safe_p2p = _validate_identifier(TABLE_NAME)
    safe_global = _validate_identifier(GLOBAL_TABLE_NAME)
    safe_ads = _validate_identifier(P2P_ADS_TABLE_NAME)
    safe_zinli = _validate_identifier(ZINLI_TABLE_NAME)
    cutoff = (now_venezuela() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d %H:%M:%S")
    total = 0
    for t, ts_col in [(safe_p2p, "timestamp"), (safe_global, "timestamp"), (safe_ads, "fetched_at"), (safe_zinli, "timestamp")]:
        c = conn.execute(f"DELETE FROM {t} WHERE {ts_col} < ?", (cutoff,)).rowcount
        total += c
    if total:
        conn.commit()
    return total