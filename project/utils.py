"""
utils.py — Utilidades compartidas entre módulos de P2P Sentinel Pro.

Centraliza _run_async para scraper.py y worker.py, evitando código duplicado
y posibles circular imports.
"""

import asyncio
import concurrent.futures
import atexit
import logging
from typing import Optional, List

# ThreadPoolExecutor reutilizable para evitar crear uno nuevo en cada llamada
_async_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None


def _get_async_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Retorna un ThreadPoolExecutor singleton para ejecutar corutinas en hilos separados."""
    global _async_executor
    if _async_executor is None:
        _async_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        atexit.register(_async_executor.shutdown, wait=True)
    return _async_executor


def _run_async(coro, timeout: float = 60, fallback=None, name: str = "async_op"):
    """
    Ejecuta una coroutine de forma segura desde cualquier contexto.

    - Si NO hay un event loop corriendo (script normal, worker): usa asyncio.run().
    - Si YA hay un event loop corriendo (Streamlit, Jupyter, tests async):
      crea un thread separado con su propio loop para evitar bloqueos.

    Args:
        coro: Coroutine object a ejecutar.
        timeout: Timeout en segundos.
        fallback: Valor a retornar si timeout o error.
        name: Nombre para logging.

    Returns:
        El resultado de la coroutine, o fallback si timeout/error.

    Raises:
        Exception: Re-lanza cualquier excepción que ocurra dentro de la coroutine
                   (solo si no se especifica fallback).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop and loop.is_running():
            executor = _get_async_executor()
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=timeout)
        else:
            return asyncio.run(coro)
    except TimeoutError:  # I4.07: unificado en Py3.11+
        if name:
            logging.getLogger(__name__).warning(f"{name}: timeout de {timeout}s excedido")
        return fallback
    except Exception as e:
        if fallback is not None:
            if name:
                logging.getLogger(__name__).error(f"{name}: error crítico {e}")
            return fallback
        raise


def apply_ema_dataframe(df, column: str, span: int) -> List[float]:
    """
    Aplica EMA a una columna de DataFrame.

    Args:
        df: DataFrame con datos ordenados cronológicamente.
        column: Nombre de la columna a suavizar.
        span: Período del EMA.

    Returns:
        Lista con valores EMA, misma longitud que df.
    """
    if column not in df.columns or df.empty:
        return []

    # Usar pandas ewm nativo: preserva longitud del DataFrame y maneja NaN correctamente
    return df[column].ewm(span=span, adjust=False).mean().tolist()
