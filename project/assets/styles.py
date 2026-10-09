"""Global CSS for P2P Sentinel Pro v3.0.
Loads from external styles.css (generated from design/tokens.py).
"""

from pathlib import Path


STYLE_CSS_PATH = Path(__file__).with_name("styles.css")


def inject_styles():
    import streamlit as st
    css = STYLE_CSS_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)