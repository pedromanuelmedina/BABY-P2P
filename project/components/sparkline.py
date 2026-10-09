"""Sparkline SVG inline — usado por kpi_card y watchlist."""

import hashlib
from typing import List, Union


def sparkline_html(
    values: List[Union[int, float]],
    color: str = "#00e676",
    width: int = 120,
    height: int = 32,
    prefix: str = "sl",
) -> str:
    """Genera un SVG sparkline con relleno degradado.

    Args:
        values: Lista de valores numéricos.
        color: Color hex de la línea.
        width: Ancho del SVG en píxeles.
        height: Alto del SVG en píxeles.
        prefix: Prefijo para el ID del gradient (evita colisiones).
    """
    values = [v for v in values if isinstance(v, (int, float))]
    if len(values) < 2:
        return ""
    vmin, vmax = min(values), max(values)
    if vmax == vmin:
        return ""
    norm = [(v - vmin) / (vmax - vmin) for v in values]
    step_x = width / (len(norm) - 1)
    points = [(i * step_x, height - n * height) for i, n in enumerate(norm)]
    path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    fill_path = f"{path} L {width},{height} L 0,{height} Z"
    raw = f"{prefix}-{values[0]}-{values[-1]}-{color}".encode()
    gid = f"{prefix}-{hashlib.md5(raw).hexdigest()[:8]}"
    return f"""
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"
     xmlns="http://www.w3.org/2000/svg" style="display:block;overflow:visible;">
    <defs>
        <linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="{color}" stop-opacity="0.25"/>
            <stop offset="100%" stop-color="{color}" stop-opacity="0"/>
        </linearGradient>
    </defs>
    <path d="{fill_path}" fill="url(#{gid})"/>
    <path d="{path}" fill="none" stroke="{color}" stroke-width="1.5"
          stroke-linejoin="round" stroke-linecap="round"/>
</svg>
    """.strip()
