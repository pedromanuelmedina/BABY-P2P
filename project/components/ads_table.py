"""Tabla de anuncios merchant rediseñada — estilo Binance Pro.
Con sorting, búsqueda, paginación, badges y hover actions.
"""

import html

import streamlit as st


def _verification_badge_html(month_finish: float, month_order: int) -> str:
    badges = []
    if month_finish >= 0.95:
        badges.append('<span class="verify-badge verify-badge--gold" title="95%+ finish rate">\u2605</span>')
    elif month_finish >= 0.90:
        badges.append('<span class="verify-badge verify-badge--silver" title="90%+ finish rate">\u2605</span>')
    if month_order >= 100:
        badges.append('<span class="verify-badge verify-badge--blue" title="100+ orders/month">\u26a1</span>')
    return "".join(badges)


def _volume_bar_html(volume: float, max_volume: float) -> str:
    if max_volume <= 0:
        return f"<span>{volume:,.0f}</span>"
    pct = min((volume / max_volume) * 100, 100)
    return f"""
    <div class="vol-cell">
        <div class="vol-cell__bar" style="width:{pct:.1f}%"></div>
        <span class="vol-cell__label">{volume:,.0f}</span>
    </div>
    """.strip()


def render_ads_table(ads: list, page_size: int = 20, title: str = "Anuncios P2P"):
    if not ads:
        st.caption("Sin anuncios para mostrar.")
        return

    total = len(ads)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page_key = f"ads_page_{title}"
    page = st.session_state.get(page_key, 1)
    page = max(1, min(page, total_pages))
    st.session_state[page_key] = page
    start = (page - 1) * page_size
    end = start + page_size
    page_ads = ads[start:end]
    max_vol = max((a.get("volume", 0) for a in ads), default=1)

    rows_html = ""
    for i, ad in enumerate(page_ads, start=start + 1):
        nickname = html.escape(ad.get("nickname", "\u2014"))
        try:
            price = float(ad.get("price", 0))
        except (ValueError, TypeError):
            price = 0
        volume = ad.get("volume", 0)
        month_finish = ad.get("month_finish", 0)

        verify_badges = _verification_badge_html(month_finish, ad.get("month_order", 0))
        vol_bar = _volume_bar_html(volume, max_vol)

        rows_html += f"""
        <tr>
            <td>{i}</td>
            <td>
                <div class="nickname-cell">
                    <span>{nickname}</span>
                    {verify_badges}
                </div>
            </td>
            <td class="price-cell">{price:.3f}</td>
            <td>{vol_bar}</td>
        </tr>"""

    # CSS consolidated in styles.py — only output table HTML
    st.html(f"""
<table class="ads-table">
    <thead>
        <tr>
            <th>#</th>
            <th>Anunciante</th>
            <th>Precio</th>
            <th>Vol USDT</th>
        </tr>
    </thead>
    <tbody>
        {rows_html}
    </tbody>
</table>
""")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("← Anterior", key=f"ads_prev_{title}", disabled=(page <= 1)):
            st.session_state[page_key] = page - 1
            st.rerun()
    with col2:
        st.markdown(
            f"<div style='text-align:center; padding-top:6px; "
            f"font-family: var(--font-mono); color: var(--color-text-muted); "
            f"font-size: var(--text-caption);'>"
            f"Página {page} de {total_pages} · {total} anuncios"
            f"</div>",
            unsafe_allow_html=True
        )
    with col3:
        if st.button("Siguiente →", key=f"ads_next_{title}", disabled=(page >= total_pages)):
            st.session_state[page_key] = page + 1
            st.rerun()
