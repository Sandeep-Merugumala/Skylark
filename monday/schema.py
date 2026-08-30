"""
monday/schema.py — Cached board schema loader.
Reads live column names/types at startup, injects into system prompt.
"""

import streamlit as st
from monday.client import get_board_schema


@st.cache_data(ttl=300, show_spinner=False)
def load_schema(board_id: int | str) -> dict:
    """Return board schema dict with columns list. Cached 5 min."""
    return get_board_schema(board_id)


def schema_summary(board_id: int | str) -> str:
    """Return a compact string describing a board's columns, for the system prompt."""
    try:
        schema = load_schema(board_id)
        cols = schema.get("columns", [])
        lines = [f"  Board: {schema.get('name', board_id)} (id={board_id})"]
        for c in cols:
            lines.append(f"    - {c['title']} (id={c['id']}, type={c['type']})")
        return "\n".join(lines)
    except Exception as e:
        return f"  [Schema unavailable: {e}]"
