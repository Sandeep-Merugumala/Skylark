"""
monday/client.py — GraphQL wrapper for monday.com API v2
Personal API token goes in Authorization header WITHOUT 'Bearer' prefix.
"""

import os
import time
import requests
import streamlit as st

MONDAY_API_URL = "https://api.monday.com/v2"


def _get_token() -> str:
    """Read token from st.secrets (deployed) or env (local)."""
    try:
        return st.secrets["MONDAY_API_TOKEN"]
    except Exception:
        token = os.environ.get("MONDAY_API_TOKEN", "")
        if not token:
            raise RuntimeError(
                "MONDAY_API_TOKEN not set. Add it to .env or Streamlit secrets."
            )
        return token


def monday_query(query: str, variables: dict | None = None, retries: int = 2) -> dict:
    """Execute a GraphQL query against monday.com API.

    Handles 429 rate-limit responses with a 60s back-off (up to `retries` times).
    Raises RuntimeError on API-level errors so callers can surface them gracefully.
    """
    token = _get_token()
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "API-Version": "2024-01",
    }
    payload = {"query": query, "variables": variables or {}}

    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                MONDAY_API_URL,
                json=payload,
                headers=headers,
                timeout=20,
            )
        except requests.exceptions.Timeout:
            raise RuntimeError("monday.com API timed out. Please try again.")
        except requests.exceptions.ConnectionError:
            raise RuntimeError("Cannot reach monday.com API. Check your connection.")

        if resp.status_code == 429:
            if attempt < retries:
                time.sleep(60)
                continue
            raise RuntimeError("monday.com rate limit hit. Please wait a moment and retry.")

        resp.raise_for_status()
        body = resp.json()

        if "errors" in body and body["errors"]:
            raise RuntimeError(f"monday.com API error: {body['errors']}")

        return body.get("data", {})

    raise RuntimeError("monday.com query failed after retries.")


# ── Board schema + items ────────────────────────────────────────────────────

_BOARD_QUERY = """
query ($boardId: [ID!]!) {
  boards(ids: $boardId) {
    id
    name
    columns { id title type }
    items_page(limit: 100) {
      cursor
      items {
        id
        name
        column_values { id type text value }
      }
    }
  }
}
"""

_NEXT_PAGE_QUERY = """
query ($boardId: [ID!]!, $cursor: String!) {
  boards(ids: $boardId) {
    items_page(limit: 100, cursor: $cursor) {
      cursor
      items {
        id
        name
        column_values { id type text value }
      }
    }
  }
}
"""


@st.cache_data(ttl=300, show_spinner=False)
def get_board(board_id: int | str) -> dict:
    """Fetch full board: schema + all items (handles pagination). Caches for 5 minutes."""
    data = monday_query(_BOARD_QUERY, {"boardId": [str(board_id)]})
    if not data.get("boards"):
        raise RuntimeError(f"Board {board_id} not found or not accessible.")

    board = data["boards"][0]
    all_items = list(board["items_page"]["items"])
    cursor = board["items_page"].get("cursor")

    # Paginate
    while cursor:
        page_data = monday_query(
            _NEXT_PAGE_QUERY,
            {"boardId": [str(board_id)], "cursor": cursor},
        )
        page = page_data["boards"][0]["items_page"]
        all_items.extend(page["items"])
        cursor = page.get("cursor")

    board["all_items"] = all_items
    return board


_SCHEMA_ONLY_QUERY = """
query ($boardId: [ID!]!) {
  boards(ids: $boardId) {
    id
    name
    columns { id title type }
  }
}
"""


def get_board_schema(board_id: int | str) -> dict:
    """Fetch only the board schema (columns) — fast, no items."""
    data = monday_query(_SCHEMA_ONLY_QUERY, {"boardId": [str(board_id)]})
    if not data.get("boards"):
        raise RuntimeError(f"Board {board_id} not found.")
    return data["boards"][0]


def get_me() -> dict:
    """Simple connectivity / auth check."""
    data = monday_query("query { me { id name email } }")
    return data.get("me", {})
