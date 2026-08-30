"""
agent/tools.py — Tool functions exposed to the Claude LLM.

Each function:
- Fetches live data from monday.com via the GraphQL client.
- Passes it through the normalization layer.
- Returns a JSON string (as Claude tool results must be strings).
- Includes a data_quality_notes field — the agent is instructed to surface these.

Design decision: 4 tools kept small and focused.
- query_deals / query_work_orders: main fetch+filter tools.
- get_field_values: discovery tool — lets the LLM find actual distinct values
  in messy categorical columns instead of guessing spelling/casing.
- cross_reference: joins both boards on shared client codes for cross-board questions.
"""

from __future__ import annotations
import json
import os
from datetime import date
from typing import Optional

import streamlit as st

from monday.client import get_board
from data.normalize import normalize_deals, normalize_work_orders


def _get_board_ids() -> tuple[str, str]:
    """Read board IDs from st.secrets or env vars."""
    try:
        wo_id = st.secrets["WORK_ORDERS_BOARD_ID"]
        deals_id = st.secrets["DEALS_BOARD_ID"]
    except Exception:
        wo_id = os.environ.get("WORK_ORDERS_BOARD_ID", "")
        deals_id = os.environ.get("DEALS_BOARD_ID", "")
    return str(wo_id), str(deals_id)


def _parse_date_filter(quarter: Optional[str], year: Optional[int]):
    """Convert a loose quarter/year mention into (start_date, end_date) or (None, None)."""
    if not quarter and not year:
        return None, None
    today = date.today()
    y = year or today.year

    quarter_map = {
        "q1": (date(y, 1, 1), date(y, 3, 31)),
        "q2": (date(y, 4, 1), date(y, 6, 30)),
        "q3": (date(y, 7, 1), date(y, 9, 30)),
        "q4": (date(y, 10, 1), date(y, 12, 31)),
        "this quarter": _current_quarter(today),
        "current quarter": _current_quarter(today),
        "last quarter": _last_quarter(today),
    }
    if quarter:
        key = str(quarter).strip().lower()
        return quarter_map.get(key, (None, None))
    return None, None


def _current_quarter(today: date):
    q = (today.month - 1) // 3
    starts = [date(today.year, 1, 1), date(today.year, 4, 1),
              date(today.year, 7, 1), date(today.year, 10, 1)]
    ends = [date(today.year, 3, 31), date(today.year, 6, 30),
            date(today.year, 9, 30), date(today.year, 12, 31)]
    return starts[q], ends[q]


def _last_quarter(today: date):
    q = (today.month - 1) // 3
    if q == 0:
        return date(today.year - 1, 10, 1), date(today.year - 1, 12, 31)
    starts = [date(today.year, 1, 1), date(today.year, 4, 1), date(today.year, 7, 1)]
    ends = [date(today.year, 3, 31), date(today.year, 6, 30), date(today.year, 9, 30)]
    return starts[q - 1], ends[q - 1]


def _date_in_range(date_str: Optional[str], start: Optional[date], end: Optional[date]) -> bool:
    if start is None and end is None:
        return True
    if not date_str:
        return False
    try:
        from dateutil import parser as dp
        d = dp.parse(date_str).date()
    except Exception:
        return False
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True


# ── Tool 1: query_deals ────────────────────────────────────────────────────

def query_deals(
    sector: Optional[str] = None,
    stage: Optional[str] = None,
    deal_status: Optional[str] = None,
    quarter: Optional[str] = None,
    year: Optional[int] = None,
    owner_code: Optional[str] = None,
) -> str:
    """Fetch deals from the Deals board, optionally filtered.

    Args:
        sector: Sector to filter by (e.g. 'Energy', 'Mining', 'Renewables'), or None for all.
        stage: Deal stage to filter by (e.g. 'Proposal Sent', 'Negotiations'), or None for all.
        deal_status: Status filter: 'Open', 'Won', 'Dead', 'On Hold', or None for all.
        quarter: Time filter by quarter: 'Q1', 'Q2', 'Q3', 'Q4', 'this quarter', 'last quarter'.
        year: Year for the quarter filter (defaults to current year).
        owner_code: Filter by owner/BD personnel code (e.g. 'OWNER_001').

    Returns:
        JSON string with keys: deals (list), summary (dict), data_quality_notes (list).
    """
    try:
        _, deals_id = _get_board_ids()
        if not deals_id:
            return json.dumps({"error": "DEALS_BOARD_ID not configured."})

        board = get_board(deals_id)
        columns = board.get("columns", [])
        raw_items = board.get("all_items", [])

        clean, notes = normalize_deals(raw_items, columns)

        # Filter
        filtered = clean
        if sector:
            sector_lower = sector.strip().lower()
            filtered = [d for d in filtered if sector_lower in (d["sector"] or "").lower()
                        or sector_lower in (d["sector_raw"] or "").lower()]

        if stage:
            stage_lower = stage.strip().lower()
            filtered = [d for d in filtered if stage_lower in (d["deal_stage"] or "").lower()
                        or stage_lower in (d["deal_stage_raw"] or "").lower()]

        if deal_status:
            status_lower = deal_status.strip().lower()
            filtered = [d for d in filtered if (d["deal_status"] or "").lower() == status_lower]

        if owner_code:
            filtered = [d for d in filtered if d.get("owner_code") == owner_code]

        start_date, end_date = _parse_date_filter(quarter, year)
        if start_date or end_date:
            date_filtered = [
                d for d in filtered
                if _date_in_range(d.get("tentative_close_date") or d.get("created_date"),
                                  start_date, end_date)
            ]
            excluded = len(filtered) - len(date_filtered)
            if excluded:
                notes.append(
                    f"{excluded} deal(s) had no date that could be matched to the requested "
                    f"period ({quarter or ''} {year or ''}) and were excluded."
                )
            filtered = date_filtered

        # Summary stats
        total_value = sum(d["deal_value"] for d in filtered if d["deal_value"] is not None)
        by_stage: dict[str, int] = {}
        by_sector: dict[str, int] = {}
        by_sector_value: dict[str, float] = {}
        for d in filtered:
            st_key = d["deal_stage"] or "Unknown"
            sc_key = d["sector"] or "Unspecified"
            by_stage[st_key] = by_stage.get(st_key, 0) + 1
            by_sector[sc_key] = by_sector.get(sc_key, 0) + 1
            if d["deal_value"]:
                by_sector_value[sc_key] = by_sector_value.get(sc_key, 0.0) + d["deal_value"]

        summary = {
            "total_deals": len(filtered),
            "total_value_inr": round(total_value, 2),
            "by_stage": by_stage,
            "by_sector_count": by_sector,
            "by_sector_value_inr": {k: round(v, 2) for k, v in by_sector_value.items()},
            "filters_applied": {
                "sector": sector, "stage": stage, "deal_status": deal_status,
                "quarter": quarter, "year": year, "owner_code": owner_code,
            },
        }

        return json.dumps(
            {"deals": filtered[:50], "summary": summary, "data_quality_notes": notes},
            default=str,
        )

    except Exception as e:
        return json.dumps({"error": str(e), "data_quality_notes": []})


# ── Tool 2: query_work_orders ──────────────────────────────────────────────

def query_work_orders(
    sector: Optional[str] = None,
    execution_status: Optional[str] = None,
    quarter: Optional[str] = None,
    year: Optional[int] = None,
    invoice_status: Optional[str] = None,
    wo_status: Optional[str] = None,
) -> str:
    """Fetch work orders from the Work Orders board, optionally filtered.

    Args:
        sector: Sector filter (e.g. 'Mining', 'Powerline').
        execution_status: Filter by execution status (e.g. 'Completed', 'Ongoing', 'Paused').
        quarter: Time window filter ('Q1', 'Q2', 'Q3', 'Q4', 'this quarter', 'last quarter').
        year: Year for quarter filter.
        invoice_status: Invoice status filter (e.g. 'Fully Billed', 'Partially Billed').
        wo_status: WO billing status ('Open', 'Closed').

    Returns:
        JSON string with keys: work_orders (list), summary (dict), data_quality_notes (list).
    """
    try:
        wo_id, _ = _get_board_ids()
        if not wo_id:
            return json.dumps({"error": "WORK_ORDERS_BOARD_ID not configured."})

        board = get_board(wo_id)
        columns = board.get("columns", [])
        raw_items = board.get("all_items", [])

        clean, notes = normalize_work_orders(raw_items, columns)

        filtered = clean
        if sector:
            sector_lower = sector.strip().lower()
            filtered = [w for w in filtered if sector_lower in (w["sector"] or "").lower()
                        or sector_lower in (w["sector_raw"] or "").lower()]

        if execution_status:
            es_lower = execution_status.strip().lower()
            filtered = [w for w in filtered if es_lower in (w["execution_status"] or "").lower()]

        if invoice_status:
            inv_lower = invoice_status.strip().lower()
            filtered = [w for w in filtered if inv_lower in (w["invoice_status"] or "").lower()]

        if wo_status:
            ws_lower = wo_status.strip().lower()
            filtered = [w for w in filtered if ws_lower in (w["wo_status"] or "").lower()]

        start_date, end_date = _parse_date_filter(quarter, year)
        if start_date or end_date:
            date_filtered = [
                w for w in filtered
                if _date_in_range(w.get("start_date") or w.get("delivery_date"),
                                  start_date, end_date)
            ]
            excluded = len(filtered) - len(date_filtered)
            if excluded:
                notes.append(
                    f"{excluded} work order(s) had no start date within "
                    f"{quarter or ''} {year or ''} and were excluded from the time-filtered results."
                )
            filtered = date_filtered

        # Summary
        total_amt = sum(w["amount_excl_gst"] for w in filtered if w["amount_excl_gst"] is not None)
        total_billed = sum(w["billed_excl_gst"] for w in filtered if w["billed_excl_gst"] is not None)
        total_collected = sum(w["collected_incl_gst"] for w in filtered if w["collected_incl_gst"] is not None)
        by_status: dict[str, int] = {}
        by_sector: dict[str, int] = {}
        for w in filtered:
            st_key = w["execution_status"] or "Unknown"
            sc_key = w["sector"] or "Unspecified"
            by_status[st_key] = by_status.get(st_key, 0) + 1
            by_sector[sc_key] = by_sector.get(sc_key, 0) + 1

        summary = {
            "total_work_orders": len(filtered),
            "total_order_value_inr_excl_gst": round(total_amt, 2),
            "total_billed_inr_excl_gst": round(total_billed, 2),
            "total_collected_inr_incl_gst": round(total_collected, 2),
            "by_execution_status": by_status,
            "by_sector": by_sector,
            "filters_applied": {
                "sector": sector, "execution_status": execution_status,
                "quarter": quarter, "year": year,
                "invoice_status": invoice_status, "wo_status": wo_status,
            },
        }

        return json.dumps(
            {"work_orders": filtered[:50], "summary": summary, "data_quality_notes": notes},
            default=str,
        )

    except Exception as e:
        return json.dumps({"error": str(e), "data_quality_notes": []})


# ── Tool 3: get_field_values ───────────────────────────────────────────────

def get_field_values(board: str, field_title: str) -> str:
    """Discover the actual distinct values in a column of either board.

    Use this tool when unsure about how a sector, status, or stage is spelled
    in the real data before filtering. Returns raw and normalised values.

    Args:
        board: Which board to inspect — 'deals' or 'work_orders'.
        field_title: The column title to inspect (e.g. 'Sector/service', 'Deal Stage').

    Returns:
        JSON string with distinct_values (list) and sample_count (int).
    """
    try:
        wo_id, deals_id = _get_board_ids()
        board_id = deals_id if board.lower() in ("deals", "deal", "deal funnel") else wo_id
        if not board_id:
            return json.dumps({"error": f"Board ID for '{board}' not configured."})

        board_data = get_board(board_id)
        columns = board_data.get("columns", [])
        items = board_data.get("all_items", [])

        # Find column id by title (case-insensitive)
        target_col_id = None
        for c in columns:
            if c["title"].lower() == field_title.lower():
                target_col_id = c["id"]
                break

        if not target_col_id:
            available = [c["title"] for c in columns]
            return json.dumps({
                "error": f"Column '{field_title}' not found.",
                "available_columns": available,
            })

        values: set[str] = set()
        for item in items:
            for cv in item.get("column_values", []):
                if cv.get("id") == target_col_id:
                    txt = cv.get("text") or cv.get("value") or ""
                    if txt and txt.strip():
                        values.add(txt.strip())

        return json.dumps({
            "board": board,
            "field": field_title,
            "distinct_values": sorted(values),
            "sample_count": len(items),
        })

    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Tool 4: cross_reference ────────────────────────────────────────────────

def cross_reference(
    sector: Optional[str] = None,
    client_code: Optional[str] = None,
) -> str:
    """Join Deals and Work Orders boards on shared client/company codes.

    Useful for questions like:
    - 'Which sectors have both active deals and active work orders?'
    - 'Show me the full picture for the Mining sector.'

    Args:
        sector: Optional sector to scope the cross-reference.
        client_code: Optional client code to match on (e.g. 'COMPANY089').

    Returns:
        JSON with matched_clients, deals_summary, work_orders_summary, data_quality_notes.
    """
    try:
        wo_id, deals_id = _get_board_ids()
        if not wo_id or not deals_id:
            return json.dumps({"error": "Board IDs not configured."})

        # Fetch both boards
        deals_board = get_board(deals_id)
        wo_board = get_board(wo_id)

        clean_deals, deal_notes = normalize_deals(
            deals_board.get("all_items", []), deals_board.get("columns", [])
        )
        clean_wo, wo_notes = normalize_work_orders(
            wo_board.get("all_items", []), wo_board.get("columns", [])
        )

        # Filter by sector if specified
        if sector:
            s_lower = sector.strip().lower()
            clean_deals = [d for d in clean_deals if s_lower in (d["sector"] or "").lower()
                           or s_lower in (d["sector_raw"] or "").lower()]
            clean_wo = [w for w in clean_wo if s_lower in (w["sector"] or "").lower()
                        or s_lower in (w["sector_raw"] or "").lower()]

        if client_code:
            clean_deals = [d for d in clean_deals if d.get("client_code") == client_code]
            clean_wo = [w for w in clean_wo if w.get("customer_code") == client_code]

        # Aggregate by sector
        deal_sectors: dict[str, dict] = {}
        for d in clean_deals:
            sc = d["sector"] or "Unspecified"
            if sc not in deal_sectors:
                deal_sectors[sc] = {"count": 0, "total_value": 0.0, "stages": {}}
            deal_sectors[sc]["count"] += 1
            if d["deal_value"]:
                deal_sectors[sc]["total_value"] += d["deal_value"]
            stg = d["deal_stage"] or "Unknown"
            deal_sectors[sc]["stages"][stg] = deal_sectors[sc]["stages"].get(stg, 0) + 1

        wo_sectors: dict[str, dict] = {}
        for w in clean_wo:
            sc = w["sector"] or "Unspecified"
            if sc not in wo_sectors:
                wo_sectors[sc] = {"count": 0, "total_value": 0.0, "statuses": {}}
            wo_sectors[sc]["count"] += 1
            if w["amount_excl_gst"]:
                wo_sectors[sc]["total_value"] += w["amount_excl_gst"]
            st = w["execution_status"] or "Unknown"
            wo_sectors[sc]["statuses"][st] = wo_sectors[sc]["statuses"].get(st, 0) + 1

        # Sectors present in both
        both = sorted(set(deal_sectors.keys()) & set(wo_sectors.keys()))
        deals_only = sorted(set(deal_sectors.keys()) - set(wo_sectors.keys()))
        wo_only = sorted(set(wo_sectors.keys()) - set(deal_sectors.keys()))

        notes = deal_notes + wo_notes

        return json.dumps(
            {
                "sectors_in_both_boards": both,
                "sectors_deals_only": deals_only,
                "sectors_wo_only": wo_only,
                "deals_by_sector": {k: {**v, "total_value": round(v["total_value"], 2)}
                                    for k, v in deal_sectors.items()},
                "work_orders_by_sector": {k: {**v, "total_value": round(v["total_value"], 2)}
                                          for k, v in wo_sectors.items()},
                "data_quality_notes": notes,
            },
            default=str,
        )

    except Exception as e:
        return json.dumps({"error": str(e), "data_quality_notes": []})



# ── Gemini uses Python functions directly ──────────────────────────────────
#
# Unlike the Anthropic API which requires a manual JSON schema dict,
# Gemini's google-generativeai SDK auto-generates tool schemas from
# Python function signatures and docstrings.
#
# Pass these functions directly to GenerativeModel(tools=[...]):
#   query_deals, query_work_orders, get_field_values, cross_reference
#
# See agent/llm.py for usage.
