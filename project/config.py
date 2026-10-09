"""
config.py — Configuración centralizada para P2P Sentinel Pro.
"""

import os
import random
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

# ─── Zona horaria de Venezuela ───────────────────────────────────────────────
TZ_VENEZUELA = ZoneInfo("America/Caracas")

# ─── Directorio de datos (configurable para producción via env) ──────────────
# En local: usa el directorio del proyecto. En prod: apuntar a volumen persistente.
_PROJECT_DIR = os.path.dirname(__file__)
DATA_DIR: str = os.environ.get("P2P_DATA_DIR", _PROJECT_DIR)
DB_PATH: str = os.path.join(DATA_DIR, "p2p_sentinel.db")
LOG_DIR: str = os.path.join(DATA_DIR, "logs")


def now_venezuela() -> datetime:
    """Retorna la hora actual en Venezuela (UTC-4), timezone-aware."""
    return datetime.now(TZ_VENEZUELA)


def now_venezuela_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Retorna la hora actual en Venezuela como string formateado."""
    return now_venezuela().strftime(fmt)


# ─── Moneda ──────────────────────────────────────────────────────────────────
CURRENCY_SYMBOL: str = "Bs."
FIAT_CURRENCY: str = "VES"


# ─── Parámetros de la API P2P de Binance ────────────────────────────────────
BASE_URL: str = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

# ─── Métodos de pago disponibles en Binance P2P (USDT/VES) ──────────────────
# Mapeo entre nombres mostrados en el dashboard y payTypes reales de Binance.
BANK_DISPLAY_MAP: Dict[str, str] = {
    "Banesco": "Banesco",
    "Mercantil": "Mercantil",
    "Provincial": "Provincial",
    "BBVA": "BBVABank",
    "Banco de Venezuela": "BancoDeVenezuela",
    "Bancamiga": "Bancamiga",
    "BNC": "BNCBancoNacional",
    "Pago Móvil": "PagoMovil",
    "Transferencia Bancaria": "BANK",
    "Zinli": "Zinli",
}
BANKS: List[str] = list(BANK_DISPLAY_MAP.keys())

# Mapeo inverso: payType de Binance -> nombre mostrable
PAYTYPE_TO_DISPLAY: Dict[str, str] = {v: k for k, v in BANK_DISPLAY_MAP.items()}

# Bancos principales de Venezuela (los demás se agrupan como "Otros Bancos")
PRIMARY_BANKS_VES: List[str] = [
    "Banesco",
    "Mercantil",
    "Provincial",
    "Pago Móvil",
    "Banco de Venezuela",
]

# ─── Configuración mercado Zinli (USDT/USD) ───────────────────────────────────
ZINLI_ASSET: str = "USDT"
ZINLI_FIAT: str = "USD"
ZINLI_PAYTYPE: str = "Zinli"
ZINLI_DISPLAY_NAME: str = "Zinli (USDT/USD)"


# ─── Opciones de auto-refresh (label -> milisegundos) ────────────────────────
REFRESH_OPTIONS: Dict[str, int] = {
    "🔴 30s": 30000,
    "🟡 1min": 60000,
    "🟢 2min": 120000,
    "🔵 5min": 300000,
}

# ─── Parámetros de Scraping ──────────────────────────────────────────────────
NUM_PAGES: int = 15                 # Páginas a consultar por tipo (BUY/SELL)
BANK_FALLBACK_PAGES: int = 5        # Páginas para fetch por banco (fallback)
ROWS_PER_PAGE: int = 20             # Filas por página (max 20 en Binance)
SKIP_FIRST_N: int = 2               # Saltear los N mejores precios por banco
MERCHANT_AD_LIMIT: int = 300        # Maximo de anuncios merchant a coleccionar

# ─── Snapshot global mínimo ──────────────────────────────────────────────────
MIN_GLOBAL_SNAPSHOT_ADS: int = 5  # Mínimo de ads por lado (buy/sell) tras filtro para guardar snapshot global
MIN_BANK_SNAPSHOT_ADS: int = 5    # Mínimo de ads por lado para guardar snapshot por banco

# ─── Filtro de outliers (IQR) ───────────────────────────────────────────────
OUTLIER_IQR_MULTIPLIER: float = 1.5       # Multiplicador IQR (1.5 = Tukey, 3 = extremo)
MIN_VOLUME_FILTER: float = 1.0            # Volumen mínimo USDT para incluir en métricas

# ─── Constantes del Dashboard ─────────────────────────────────────────────────
HISTORY_LIMIT: int = 5000

# ─── Rangos temporales para gráficos (label → horas) ─────────────────────────
TIME_RANGES: dict = {
    "2h": 2, "3h": 3, "4h": 4, "5h": 5, "6h": 6, "7h": 7, "8h": 8, "9h": 9, "10h": 10, "12h": 12, "14h": 14,
    "1d": 24, "2d": 48, "3d": 72, "4d": 96, "5d": 120,
    "1w": 168, "2w": 336, "3w": 504,
    "1m": 720, "2m": 1440, "3m": 2160,
}

# ─── Parámetros de Reintentos ────────────────────────────────────────────────
HTTP_MAX_RETRIES: int = 3           # Reintentos HTTP con backoff exponencial
BASE_DELAY: float = 2.0             # Delay base para backoff exponencial (segundos)

# ─── Concurrencia anti-bloqueo ───────────────────────────────────────────────
# 1 = totalmente secuencial (humano), 2 = ligera concurrencia (modo equilibrado).
MAX_CONCURRENT_REQUESTS: int = 2

# ─── Delays entre páginas (anti-detección) ───────────────────────────────────
# Modo equilibrado: pacing suficiente para evadir rate-limit sin proxies.
PAGE_DELAY_MIN: float = 2.0         # Delay mínimo entre páginas (segundos)
PAGE_DELAY_MAX: float = 5.0         # Delay máximo entre páginas (segundos)
PAGE_DELAY_AFTER_429: float = 20.0  # Delay extra si recibimos un 429 (cooldown agresivo)
# Cooldown GLOBAL aplicado a TODO el ciclo de fetch cuando se detecta un 429:
# pausa las demás páginas en vuelo para no insistir mientras Binance nos limita.
GLOBAL_COOLDOWN_ON_429: float = 30.0  # segundos de pausa global tras 429

# ─── Pool de User-Agents reales (rotación aleatoria) ─────────────────────────
_USER_AGENTS: List[str] = [
    # Chrome (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Chrome (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Firefox (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    # Firefox (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.0; rv:131.0) Gecko/20100101 Firefox/131.0",
    # Safari (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    # Edge (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    # Chrome Mobile (Android)
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
]


def get_random_user_agent() -> str:
    """Devuelve un User-Agent aleatorio del pool."""
    return random.choice(_USER_AGENTS)


# ─── Payload factory ────────────────────────────────────────────────────────
def build_payload(
    trade_type: str,
    page: int = 1,
    rows: int = 20,
    pay_types: Optional[List[str]] = None,
    publisher_type: Optional[str] = "merchant",
    asset: str = "USDT",
    fiat: str = "VES",
) -> Dict:
    payload: Dict = {
        "asset": asset,
        "fiat": fiat,
        "merchantCheck": False,
        "page": page,
        "rows": rows,
        "tradeType": trade_type,
    }
    # Solo incluir publisherType si tiene un valor definido (no None).
    # None se usa para obtener TODOS los anuncios (no solo merchants).
    if publisher_type is not None:
        payload["publisherType"] = publisher_type
    if pay_types:
        payload["payTypes"] = pay_types
    return payload
