"""shared_types.py — Type aliases compartidos sin dependencias.
Extraidos de scraper.py para desacoplar metrics.py y otros modulos.
No llamarse types.py para evitar colision con stdlib 'types'.
"""
from typing import Dict

AdRecord = Dict[str, float]            # {"price": float, "volume": float}
GlobalAdRecord = Dict[str, object]     # {"price", "volume", "bank"}
MerchantAdFull = Dict[str, object]     # {"nickName", "price", "volume", "bank", ...}
