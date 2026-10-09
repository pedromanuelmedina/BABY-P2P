"""
scraper.py — Conexión ASÍNCRONA a la API P2P de Binance.

Mejoras v1.2c:
  - httpx.AsyncClient (conexiones HTTP/2 reutilizables, async nativo)
  - Concurrencia controlada con asyncio.Semaphore (max 2 simultáneas)
  - Delays entre lanzamientos para simular navegación humana
  - Rotación de User-Agent realista por sesión
  - Headers completos que imitan navegador real
  - Pausa escalada automática si recibe un 429 (rate limit)
  - Deduplicación de anuncios por precio+volumen entre páginas
  - Parámetros centralizados en config.py
  - Wrapper síncrono para compatibilidad con Streamlit/worker
"""

import asyncio
import random
import logging
from typing import Dict, List, Optional, Tuple

import httpx

from .utils import _run_async

from .config import (
    BASE_URL,
    build_payload,
    BANK_DISPLAY_MAP,
    PAYTYPE_TO_DISPLAY,
    get_random_user_agent,
    NUM_PAGES,
    ROWS_PER_PAGE,
    MERCHANT_AD_LIMIT,
    HTTP_MAX_RETRIES as MAX_RETRIES,
    BASE_DELAY,
    PAGE_DELAY_MIN,
    PAGE_DELAY_MAX,
    PAGE_DELAY_AFTER_429,
    GLOBAL_COOLDOWN_ON_429,
    MAX_CONCURRENT_REQUESTS,
    MIN_VOLUME_FILTER,
    BANK_FALLBACK_PAGES,
)

logger = logging.getLogger(__name__)

# ─── Concurrencia ────────────────────────────────────────────────────────────
# Importado desde config.py (modo equilibrado = 2)


from ._types import AdRecord, GlobalAdRecord, MerchantAdFull  # noqa: E402 (movidos a _types.py)
# Los aliases viven en types.py ahora; este import los re-exporta para
# no romper callers externos que hacen `from scraper import AdRecord`.


# ─── User-Agent persistente por sesión ──────────────────────────────────────
_PROCESS_USER_AGENT: str = get_random_user_agent()


def _build_headers() -> Dict[str, str]:
    """Headers que imitan un navegador real visitando p2p.binance.com.
    El User-Agent se genera una sola vez por sesión del proceso para reducir
    riesgo de detección por cambios bruscos de UA entre requests.
    """
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-419,es;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Content-Type": "application/json",
        "Origin": "https://p2p.binance.com",
        "Referer": "https://p2p.binance.com/",
        "User-Agent": _PROCESS_USER_AGENT,
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


# ─── Delay humano (async) ───────────────────────────────────────────────────
async def _human_delay(min_s: float = PAGE_DELAY_MIN, max_s: float = PAGE_DELAY_MAX) -> None:
    """Pausa async con distribución gaussiana (patrón humano)."""
    center = (min_s + max_s) / 2
    sigma = (max_s - min_s) / 4
    delay = max(min_s, min(max_s, random.gauss(center, sigma)))
    await asyncio.sleep(delay)



# ─── Retry con backoff exponencial (async) ──────────────────────────────────
async def _retry_with_backoff(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    page: int,
    trade_type: str,
    parse_fn,
    name: str,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY,
    headers: Optional[Dict[str, str]] = None,
    cooldown: Optional["_GlobalCooldown"] = None,
) -> Tuple[List, Optional[str], bool, bool]:
    """Retry genérico con backoff exponencial para requests POST a la API P2P.
    Retorna: (ads, error_msg, success, got_429)
    Si se provee `cooldown`, dispara una pausa global al detectar un 429.
    """
    got_429 = False
    for attempt in range(max_retries):
        try:
            request_kwargs = {"json": payload, "timeout": 30.0}
            if headers:
                request_kwargs["headers"] = headers
            response = await client.post(url, **request_kwargs)

            if response.status_code == 429:
                got_429 = True
                # Disparar cooldown global para frenar a las demás páginas en vuelo
                if cooldown is not None:
                    cooldown.trigger()
                    logger.warning(
                        f"429 en pág.{page} {trade_type}: cooldown global activado "
                        f"({GLOBAL_COOLDOWN_ON_429:.0f}s)"
                    )
                wait = PAGE_DELAY_AFTER_429 * (2 ** attempt)
                logger.warning(
                    f"429 Rate Limit en pág.{page} {trade_type} (intento {attempt+1}/{max_retries}). "
                    f"Esperando {wait:.1f}s..."
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(wait)
                continue

            if response.status_code >= 400:
                logger.warning(f"HTTP {response.status_code} en pág.{page} {trade_type}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
                continue

            data = response.json()
            if not data.get("success", False):
                return [], data.get("message", "API error"), False, got_429

            return parse_fn(data, page, trade_type), None, True, got_429

        except (httpx.RequestError, httpx.TimeoutException) as e:
            logger.error(f"Error conexión pág.{page} {trade_type}: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(base_delay * (2 ** attempt))

    return [], "Fallo tras reintentos", False, got_429

# ─── Helpers de payType ──────────────────────────────────────────────────────
def _extract_pay_type(ad: Dict) -> str:
    trade_methods = ad.get("adv", {}).get("tradeMethods", [])
    if trade_methods:
        return trade_methods[0].get("payType", "")
    return ""


def _display_pay_type(pay_type: str) -> str:
    """Convierte un payType de Binance a nombre mostrable en el dashboard."""
    return PAYTYPE_TO_DISPLAY.get(pay_type, pay_type)


def _binance_pay_type(display_name: str) -> str:
    """Convierte un nombre mostrable del dashboard al payType de Binance."""
    return BANK_DISPLAY_MAP.get(display_name, display_name)


# ─── Parseo ──────────────────────────────────────────────────────────────────
def _parse_ads(response_json: Dict, bank: str, min_amount: float = 0.0) -> List[AdRecord]:
    ads_raw = response_json.get("data") or []
    # Nota: Binance ya filtra por payTypes en la API cuando se envia el parametro,
    # asi que no necesitamos _filter_by_bank aqui (y rompe nombres con espacios).
    ads: List[AdRecord] = []
    for ad in ads_raw:
        try:
            adv = ad["adv"]
            price = float(adv["price"])
            volume = float(adv["tradableQuantity"])
            if min_amount > 0 and volume < min_amount:
                continue
            ads.append({"price": price, "volume": volume})
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Ad parsing falló (banco={bank}): {e} — ad keys: {list(ad.get('adv', {}).keys())}")
            continue
    return ads


def _parse_ads_global(response_json: Dict, min_amount: float = 0.0) -> List[GlobalAdRecord]:
    ads_raw = response_json.get("data") or []
    ads: List[GlobalAdRecord] = []
    for ad in ads_raw:
        try:
            adv = ad["adv"]
            price = float(adv["price"])
            volume = float(adv["tradableQuantity"])
            bank_name = _display_pay_type(_extract_pay_type(ad))
            if min_amount > 0:
                min_single = adv.get("minSingleTransAmount")
                if min_single is not None and float(min_single) > min_amount:
                    continue
            ads.append({"price": price, "volume": volume, "bank": bank_name})
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Ad global parsing falló: {e} — ad keys: {list(ad.get('adv', {}).keys())}")
            continue
    return ads


# ─── Cooldown global tras 429 ───────────────────────────────────────────────
# Evento async compartido entre todas las páginas en vuelo de un mismo ciclo.
# Cuando una página recibe 429, se "set" el evento → las demás esperan antes
# de lanzar su próxima request, evando insistir mientras Binance nos limita.
class _GlobalCooldown:
    """Pausa global ligera: cuando una página ve un 429, bloquea a las demás
    durante GLOBAL_COOLDOWN_ON_429 segundos para no agravar el rate-limit."""
    def __init__(self) -> None:
        self._gate = asyncio.Event()
        self._gate.set()  # arranca abierto (no bloqueante)
        self._cooldown_deadline: float = 0.0

    async def wait_if_cooling(self) -> None:
        """Bloquea a la tarea llamadora mientras dure el cooldown global."""
        await self._gate.wait()

    def trigger(self) -> None:
        """Dispara/renueva el cooldown global."""
        self._cooldown_deadline = asyncio.get_event_loop().time() + GLOBAL_COOLDOWN_ON_429
        self._gate.clear()
        asyncio.get_event_loop().call_later(GLOBAL_COOLDOWN_ON_429, self._release)

    def _release(self) -> None:
        self._gate.set()


# ─── Fetch individual de una página (ASYNC) ─────────────────────────────────
async def _fetch_page_async(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    bank: str,
    trade_type: str,
    page: int,
    rows: int,
    min_amount: float,
    cooldown: _GlobalCooldown,
    asset: str = "USDT",
    fiat: str = "VES",
    pay_types: Optional[List[str]] = None,
) -> Tuple[List, Optional[str], bool, bool]:
    """Fetch una página con semáforo de concurrencia y respeto del cooldown global."""
    # Si se proveen pay_types explícitos, usarlos; sino derivar de bank
    final_pay_types = pay_types if pay_types is not None else ([_binance_pay_type(bank)] if bank else None)
    payload = build_payload(trade_type, page=page, rows=rows, pay_types=final_pay_types, asset=asset, fiat=fiat)
    headers = _build_headers()

    def _parse(data, _page, _trade_type):
        if bank:
            return _parse_ads(data, bank, min_amount)
        return _parse_ads_global(data, min_amount)

    # Delay pre-request a rango completo (anti-detección equilibrado)
    await _human_delay(PAGE_DELAY_MIN, PAGE_DELAY_MAX)
    # Respetar pausa global si otra página recibió 429
    await cooldown.wait_if_cooling()
    async with semaphore:
        return await _retry_with_backoff(
            client, BASE_URL, payload, page, trade_type, _parse, "p2p",
            headers=headers, cooldown=cooldown,
        )


# ─── Deduplicación ───────────────────────────────────────────────────────────
def _deduplicate_ads(ads: List[AdRecord], include_bank: bool = False) -> List:
    """Elimina anuncios duplicados por (price, volume) [+ bank opcional].
    Redondea a 6 decimales para evitar falsos duplicados por precision float."""
    seen = set()
    unique = []
    for ad in ads:
        if include_bank:
            key: Tuple = (round(ad["price"], 6), round(ad["volume"], 6), ad.get("bank", ""))
        else:
            key = (round(ad["price"], 6), round(ad["volume"], 6))
        if key not in seen:
            seen.add(key)
            unique.append(ad)
    return unique



# ─── Coordinador ASYNC (multi-page) ─────────────────────────────────────────
async def _fetch_pages_async(
    bank: str,
    trade_type: str,
    min_amount: float,
    num_pages: int = NUM_PAGES,
    asset: str = "USDT",
    fiat: str = "VES",
    pay_types: Optional[List[str]] = None,
) -> Tuple[List, Optional[str], bool]:
    """Coordina la obtención de num_pages páginas concurrentes."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        cooldown = _GlobalCooldown()
        tasks = [
            _fetch_page_async(client, semaphore, bank, trade_type, page, ROWS_PER_PAGE, min_amount, cooldown, asset, fiat, pay_types)
            for page in range(1, num_pages + 1)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_ads: List = []
        last_error: Optional[str] = None
        any_success = False
        for res in results:
            if isinstance(res, Exception):
                logger.warning(f"Page fetch falló: {res}")
                continue
            page_ads, err, ok, _ = res  # type: ignore[misc]
            if ok and page_ads:
                all_ads.extend(page_ads)
                any_success = True
            if err:
                last_error = err
        return all_ads, last_error, any_success


# ─── Funciones públicas (SYNC wrappers) ─────────────────────────────────────

def fetch_ads_global(
    trade_type: str,
    min_amount: float = 0.0,
    asset: str = "USDT",
    fiat: str = "VES",
    pay_types: Optional[List[str]] = None,
) -> Tuple[List[GlobalAdRecord], Optional[str], bool, int]:
    all_ads, last_error, any_success = _run_async(
        _fetch_pages_async("", trade_type, min_amount, asset=asset, fiat=fiat, pay_types=pay_types)
    )

    if not any_success and not all_ads:
        return [], last_error, False, 0

    all_ads = _deduplicate_ads(all_ads, include_bank=True)

    all_ads = [a for a in all_ads if a.get("volume", 0) >= MIN_VOLUME_FILTER]

    if trade_type == "BUY":
        all_ads.sort(key=lambda a: a["price"])
    else:
        all_ads.sort(key=lambda a: a["price"], reverse=True)

    return all_ads, last_error, True, len(all_ads)


def fetch_ads_bank(
    bank: str,
    trade_type: str,
    min_amount: float = 0.0,
    num_pages: int = BANK_FALLBACK_PAGES,
    asset: str = "USDT",
    fiat: str = "VES",
) -> Tuple[List, Optional[str], bool]:
    """Fetch de anuncios filtrados por banco (payTypes). Usado como fallback."""
    all_ads, last_error, any_success = _run_async(
        _fetch_pages_async(bank, trade_type, min_amount, num_pages=num_pages, asset=asset, fiat=fiat)
    )
    if not any_success and not all_ads:
        return [], last_error, False
    all_ads = _deduplicate_ads(all_ads)
    all_ads = [a for a in all_ads if a.get("volume", 0) >= MIN_VOLUME_FILTER]
    for a in all_ads:
        a["bank"] = bank
    return all_ads, last_error, True


def _is_verified_merchant(ad: Dict) -> bool:
    """Verifica si el merchant está verificado según campos de Binance."""
    advertiser = ad.get("advertiser", {})
    return (
        advertiser.get("merchantVerifyType", 0) > 0 or
        advertiser.get("isVerified", False) or
        advertiser.get("verifyType", 0) > 0
    )


def _parse_ads_merchant(response_json: Dict, trade_type: str, min_amount: float = 0.0) -> List[MerchantAdFull]:
    ads_raw = response_json.get("data") or []
    ads: List[Dict] = []
    for ad in ads_raw:
        try:
            adv = ad.get("adv", {})
            advertiser = ad.get("advertiser", {})
            price = float(adv["price"])
            volume = float(adv["tradableQuantity"])
            if min_amount > 0 and volume < min_amount:
                continue
            bank = _display_pay_type(_extract_pay_type(ad))
            merchant_verify_type = advertiser.get("merchantVerifyType", 0)
            user_grade = advertiser.get("userGrade", 0)
            vip_level = advertiser.get("vipLevel", 0)
            is_verified = advertiser.get("isVerified", False)
            verify_type = advertiser.get("verifyType", 0)
            ads.append({
                "price": price,
                "volume": volume,
                "bank": bank,
                "nickname": advertiser.get("nickName", ""),
                "trade_type": trade_type,
                "merchant_id": advertiser.get("merchantId", 0),
                "user_no": advertiser.get("userNo", 0),
                "month_finish": advertiser.get("monthFinishRate", 0),
                "month_order": advertiser.get("monthOrderCount", 0),
                "min_amount": float(adv.get("minSingleTransAmount") or 0),
                "max_amount": float(adv.get("maxSingleTransAmount") or 0),
                "fiat": adv.get("fiatSymbol", ""),
                "merchant_verify_type": merchant_verify_type,
                "user_grade": user_grade,
                "vip_level": vip_level,
                "is_verified": is_verified,
                "verify_type": verify_type,
                "is_verified_merchant": merchant_verify_type > 0,
            })
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Merchant ad parsing falló: {e}")
            continue
    return ads


async def _fetch_ads_merchant_async(
    trade_type: str,
    min_amount: float = 0.0,
    rows: int = 20,
    verified_only: bool = False,
) -> Tuple[List[MerchantAdFull], Optional[str], bool]:
    all_ads: List[Dict] = []
    last_error: Optional[str] = None
    any_success = False

    def _wrap_parse(data, page, tt):
        return _parse_ads_merchant(data, tt, min_amount)

    async def _fetch_one_page(client, semaphore, page, cooldown):
        # Delay pre-request a rango completo + respeto del cooldown global
        await _human_delay(PAGE_DELAY_MIN, PAGE_DELAY_MAX)
        await cooldown.wait_if_cooling()
        async with semaphore:
            payload = build_payload(trade_type, page=page, rows=rows)
            headers = _build_headers()
            # UA de sesión (no rotar por página: es sospechoso para Binance)
            return await _retry_with_backoff(
                client, BASE_URL, payload, page, trade_type,
                _wrap_parse, f"merchant_{trade_type}", headers=headers,
                cooldown=cooldown,
            )

    async with httpx.AsyncClient(timeout=30) as client:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        cooldown = _GlobalCooldown()
        tasks = [_fetch_one_page(client, semaphore, p, cooldown) for p in range(1, NUM_PAGES + 1)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                logger.warning(f"Merchant page fetch falló: {res}")
                continue
            parsed, error, success, _got_429 = res  # type: ignore[misc]
            if success and parsed:
                all_ads.extend(parsed)
                any_success = True
                if len(all_ads) >= MERCHANT_AD_LIMIT:
                    all_ads = all_ads[:MERCHANT_AD_LIMIT]
                    break
            elif error:
                last_error = error
    all_ads.sort(key=lambda a: a["price"], reverse=(trade_type == "SELL"))
    if verified_only:
        all_ads = [a for a in all_ads if a.get("is_verified_merchant", False)]
    return all_ads, last_error, any_success


def fetch_ads_merchant(
    trade_type: str,
    min_amount: float = 0.0,
    rows: int = 20,
    verified_only: bool = False,
) -> Tuple[List[MerchantAdFull], Optional[str], bool]:
    return _run_async(_fetch_ads_merchant_async(trade_type, min_amount, rows, verified_only))




