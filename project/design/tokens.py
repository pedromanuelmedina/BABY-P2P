"""Design tokens centralizados para P2P Sentinel Pro v3.0.
Single source of truth: colores, tipografía, espaciado, sombras, radios.
Todos los componentes deben leer de aquí — NUNCA hardcodear hex.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Color:
    BG_BASE: str = "#0a0a0f"
    BG_ELEVATED: str = "#12121a"
    BG_SURFACE: str = "#1a1a2e"
    BG_HOVER: str = "#1C2330"
    BG_INPUT: str = "#0F131B"

    BORDER_SUBTLE: str = "rgba(255, 255, 255, 0.06)"
    BORDER_DEFAULT: str = "rgba(255, 255, 255, 0.08)"
    BORDER_STRONG: str = "rgba(255, 255, 255, 0.12)"
    BORDER_FOCUS: str = "#00e676"

    TEXT_PRIMARY: str = "#e0e0e0"
    TEXT_SECONDARY: str = "#94A3B8"
    TEXT_MUTED: str = "rgba(255, 255, 255, 0.4)"
    TEXT_DISABLED: str = "#475569"

    BUY: str = "#00e676"
    BUY_GLOW: str = "rgba(0, 230, 118, 0.20)"
    BUY_BG: str = "rgba(0, 230, 118, 0.10)"

    SELL: str = "#ff5252"
    SELL_GLOW: str = "rgba(255, 82, 82, 0.20)"
    SELL_BG: str = "rgba(255, 82, 82, 0.10)"

    ACCENT: str = "#00e676"
    ACCENT_HOVER: str = "#00c853"
    ACCENT_GLOW: str = "rgba(0, 230, 118, 0.25)"

    PURPLE: str = "#ffab40"
    PURPLE_GLOW: str = "rgba(255, 171, 64, 0.25)"

    MID: str = "#ffab40"
    MID_PRICE: str = "#e0e0e0"
    BUY_EMA: str = "rgba(0, 230, 118, 0.45)"
    SELL_EMA: str = "rgba(255, 82, 82, 0.45)"

    WARNING: str = "#ffab40"
    WARNING_BG: str = "rgba(255, 171, 64, 0.10)"

    INFO: str = "#ffab40"
    INFO_BG: str = "rgba(255, 171, 64, 0.10)"

    GLASS_BG: str = "rgba(26, 26, 46, 0.55)"
    GLASS_BG_HOVER: str = "rgba(26, 26, 46, 0.70)"
    GLASS_BLUR: str = "8px"

    CHART_BG: str = "#0a0a0f"
    CHART_GRID: str = "rgba(255, 255, 255, 0.04)"
    CHART_GRID_STRONG: str = "rgba(255, 255, 255, 0.08)"
    CHART_TEXT: str = "rgba(255, 255, 255, 0.3)"
    CHART_TEXT_MUTED: str = "rgba(255, 255, 255, 0.3)"
    CHART_CROSSHAIR: str = "rgba(255, 255, 255, 0.4)"
    CHART_WICK_UP: str = "#00e676"
    CHART_WICK_DOWN: str = "#ff5252"
    CHART_VOLUME_UP: str = "rgba(0, 230, 118, 0.40)"
    CHART_VOLUME_DOWN: str = "rgba(255, 82, 82, 0.40)"

    DEPTH_BID: str = "rgba(0, 230, 118, 0.30)"
    DEPTH_BID_LINE: str = "#00e676"
    DEPTH_ASK: str = "rgba(255, 82, 82, 0.30)"
    DEPTH_ASK_LINE: str = "#ff5252"


@dataclass(frozen=True)
class Typography:
    FONT_UI: str = "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"
    FONT_MONO: str = "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace"

    DISPLAY: dict = None
    H1: dict = None
    H2: dict = None
    H3: dict = None
    BODY_LG: dict = None
    BODY: dict = None
    BODY_SM: dict = None
    CAPTION: dict = None
    LABEL: dict = None
    MONO_LG: dict = None
    MONO: dict = None
    MONO_SM: dict = None


Typography.DISPLAY = {"size": 32, "weight": 700, "tracking": -0.02, "leading": 1.1}
Typography.H1 = {"size": 24, "weight": 700, "tracking": -0.02, "leading": 1.2}
Typography.H2 = {"size": 20, "weight": 600, "tracking": -0.01, "leading": 1.3}
Typography.H3 = {"size": 16, "weight": 600, "tracking": 0, "leading": 1.4}
Typography.BODY_LG = {"size": 14, "weight": 400, "tracking": 0, "leading": 1.5}
Typography.BODY = {"size": 14, "weight": 400, "tracking": 0, "leading": 1.5}
Typography.BODY_SM = {"size": 12, "weight": 400, "tracking": 0.01, "leading": 1.4}
Typography.CAPTION = {"size": 11, "weight": 500, "tracking": 0.04, "leading": 1.3}
Typography.LABEL = {"size": 10, "weight": 600, "tracking": 0.08, "leading": 1.2}
Typography.MONO_LG = {"size": 20, "weight": 600, "tracking": -0.01, "leading": 1.2}
Typography.MONO = {"size": 14, "weight": 500, "tracking": 0, "leading": 1.3}
Typography.MONO_SM = {"size": 12, "weight": 500, "tracking": 0, "leading": 1.3}


@dataclass(frozen=True)
class Spacing:
    XS: int = 4
    SM: int = 8
    MD: int = 12
    LG: int = 16
    XL: int = 24
    XXL: int = 32
    XXXL: int = 48


@dataclass(frozen=True)
class Radius:
    NONE: int = 0
    SM: int = 4
    MD: int = 6
    LG: int = 8
    XL: int = 12
    PILL: int = 9999


@dataclass(frozen=True)
class Shadow:
    SM: str = "0 1px 2px 0 rgba(0, 0, 0, 0.30)"
    MD: str = "0 4px 12px -2px rgba(0, 0, 0, 0.40)"
    LG: str = "0 8px 24px -4px rgba(0, 0, 0, 0.50)"
    GLOW_ACCENT: str = "0 0 0 3px rgba(0, 230, 118, 0.20)"
    GLOW_BUY: str = "0 0 16px rgba(0, 230, 118, 0.30)"
    GLOW_SELL: str = "0 0 16px rgba(255, 82, 82, 0.30)"


@dataclass(frozen=True)
class Motion:
    FAST: int = 120
    NORMAL: int = 200
    SLOW: int = 320
    EASE_OUT: str = "cubic-bezier(0.16, 1, 0.3, 1)"
    EASE_IN_OUT: str = "cubic-bezier(0.65, 0, 0.35, 1)"


COLOR = Color()
TYPO = Typography()
SPACE = Spacing()
RADIUS = Radius()
SHADOW = Shadow()
MOTION = Motion()


def build_css_variables() -> str:
    lines = [":root {"]
    for attr in dir(COLOR):
        if not attr.startswith("_"):
            val = getattr(COLOR, attr)
            lines.append(f"  --color-{attr.lower().replace('_', '-')}: {val};")
    for attr in dir(SPACE):
        if not attr.startswith("_"):
            val = getattr(SPACE, attr)
            lines.append(f"  --space-{attr.lower()}: {val}px;")
    for attr in dir(RADIUS):
        if not attr.startswith("_"):
            val = getattr(RADIUS, attr)
            lines.append(f"  --radius-{attr.lower()}: {val}px;")
    for attr in dir(SHADOW):
        if not attr.startswith("_"):
            val = getattr(SHADOW, attr)
            lines.append(f"  --shadow-{attr.lower().replace('_', '-')}: {val};")
    for attr in dir(MOTION):
        if not attr.startswith("_"):
            val = getattr(MOTION, attr)
            if isinstance(val, int):
                lines.append(f"  --motion-{attr.lower()}: {val}ms;")
            else:
                lines.append(f"  --motion-{attr.lower()}: {val};")
    lines.append(f"  --font-ui: {TYPO.FONT_UI};")
    lines.append(f"  --font-mono: {TYPO.FONT_MONO};")
    for attr in ["DISPLAY", "H1", "H2", "H3", "BODY_LG", "BODY", "BODY_SM",
                 "CAPTION", "LABEL", "MONO_LG", "MONO", "MONO_SM"]:
        s = getattr(Typography, attr)
        lines.append(f"  --text-{attr.lower().replace('_', '-')}: {s['size']}px;")
        lines.append(f"  --text-{attr.lower().replace('_', '-')}-weight: {s['weight']};")
        lines.append(f"  --text-{attr.lower().replace('_', '-')}-tracking: {s['tracking']}em;")
        lines.append(f"  --text-{attr.lower().replace('_', '-')}-leading: {s['leading']};")
    lines.append("  --sidebar-width: 180px;")
    lines.append("}")
    return "\n".join(lines)
