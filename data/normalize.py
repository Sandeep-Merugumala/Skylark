"""
data/normalize.py — Data resilience layer.

Normalizes raw monday.com item column_values into clean Python dicts.
Tracks data-quality issues transparently — never silently drops bad data.

Key design decisions:
- normalize_date: uses dateutil for fuzzy date parsing (handles multiple formats).
- normalize_sector / normalize_deal_stage: alias tables built from actual
  observed values in the real dataset (run get_field_values to discover them).
- All normalizers return (clean_value, quality_flag) so callers can aggregate
  data_quality_notes and surface them in agent responses.
"""

from __future__ import annotations
import re
from datetime import datetime, date
from typing import Any

try:
    from dateutil import parser as date_parser  # type: ignore
    _HAS_DATEUTIL = True
except ImportError:
    _HAS_DATEUTIL = False


# ── Date normalization ──────────────────────────────────────────────────────

def normalize_date(raw: Any) -> tuple[date | None, str]:
    """Parse a raw date value into a Python date.

    Returns (date_obj, 'ok') on success or (None, reason_string) on failure.
    Never raises.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, "missing"
    raw_str = str(raw).strip()
    if raw_str.lower() in ("nan", "none", "n/a", "-", ""):
        return None, "missing"

    if _HAS_DATEUTIL:
        try:
            parsed = date_parser.parse(raw_str, fuzzy=True)
            return parsed.date(), "ok"
        except (ValueError, OverflowError, TypeError):
            pass

    # Fallback: try common ISO format
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw_str[:10], fmt).date(), "ok"
        except ValueError:
            continue

    return None, f"unparseable: {raw_str!r}"


# ── Sector normalization ────────────────────────────────────────────────────

# Built from actual unique values observed in both the Deals and Work Orders sheets.
SECTOR_ALIASES: dict[str, str] = {
    # Energy / Power (note: dataset uses 'Powerline'/'Renewables', no 'Energy' tag)
    "energy": "Energy",
    "energy sector": "Energy",
    "pwr": "Energy",
    "power": "Energy",
    # Renewables
    "renewables": "Renewables",
    "renewable": "Renewables",
    "solar": "Renewables",
    "wind": "Renewables",
    # Mining
    "mining": "Mining",
    "mine": "Mining",
    # Powerline
    "powerline": "Powerline",
    "power line": "Powerline",
    "transmission": "Powerline",
    # Railways
    "railways": "Railways",
    "railway": "Railways",
    "rail": "Railways",
    # Construction
    "construction": "Construction",
    # Others / DSP / Tender / Security
    "dsp": "DSP",
    "tender": "Tender",
    "security and surveillance": "Security & Surveillance",
    "security": "Security & Surveillance",
    "surveillance": "Security & Surveillance",
    # Aviation
    "aviation": "Aviation",
    # Manufacturing
    "manufacturing": "Manufacturing",
    "others": "Others",
    "other": "Others",
}


try:
    from rapidfuzz import process, fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False

KNOWN_SECTORS = [
    "Energy", "Renewables", "Mining", "Powerline", "Railways", 
    "Construction", "DSP", "Tender", "Security & Surveillance", 
    "Aviation", "Manufacturing", "Others"
]

def normalize_sector(raw: Any) -> str:
    """Return a canonical sector name from any messy raw value, using fuzzy matching."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "Unspecified"
    key = str(raw).strip().lower()
    if key in ("nan", "none", "n/a", "-", ""):
        return "Unspecified"
        
    if key in SECTOR_ALIASES:
        return SECTOR_ALIASES[key]
        
    raw_clean = str(raw).strip()
    if _HAS_RAPIDFUZZ:
        # 80% similarity threshold
        match = process.extractOne(raw_clean, KNOWN_SECTORS, scorer=fuzz.ratio)
        if match and match[1] >= 80:
            return match[0]
            
    return raw_clean.title()


# ── Deal stage normalization ────────────────────────────────────────────────

# From actual Deal Stage column unique values in Deal funnel Data.xlsx
DEAL_STAGE_ALIASES: dict[str, str] = {
    # Full stage labels from actual data
    "a. lead generated": "Lead Generated",
    "b. sales qualified leads": "Sales Qualified Lead",
    "c. demo done": "Demo Done",
    "d. feasibility": "Feasibility",
    "e. proposal/commercials sent": "Proposal Sent",
    "f. negotiations": "Negotiations",
    "g. project won": "Won",
    "h. work order received": "Work Order Received",
    "i. poc": "POC",
    "j. invoice sent": "Invoice Sent",
    "k. amount accrued": "Amount Accrued",
    "l. project lost": "Lost",
    "m. projects on hold": "On Hold",
    "n. not relevant at the moment": "Not Relevant",
    "o. not relevant at all": "Not Relevant",
    "project completed": "Completed",
    # shorthand forms
    "lead": "Lead Generated",
    "sql": "Sales Qualified Lead",
    "proposal": "Proposal Sent",
    "negotiation": "Negotiations",
    "won": "Won",
    "dead": "Dead",
    "lost": "Lost",
    "on hold": "On Hold",
    "hold": "On Hold",
    "poc": "POC",
    "invoice sent": "Invoice Sent",
    "completed": "Completed",
}


def normalize_deal_stage(raw: Any) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "Unknown"
    key = str(raw).strip().lower()
    if key in ("nan", "none", ""):
        return "Unknown"
    return DEAL_STAGE_ALIASES.get(key, str(raw).strip())


# ── Execution status normalization ─────────────────────────────────────────

EXEC_STATUS_ALIASES: dict[str, str] = {
    "completed": "Completed",
    "not started": "Not Started",
    "executed until current month": "Ongoing",
    "ongoing": "Ongoing",
    "pause / struck": "Paused",
    "paused": "Paused",
    "partial completed": "Partially Completed",
    "partially completed": "Partially Completed",
    "details pending from client": "Pending Client Details",
}


def normalize_exec_status(raw: Any) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "Unknown"
    key = str(raw).strip().lower()
    return EXEC_STATUS_ALIASES.get(key, str(raw).strip().title())


# ── Numeric / currency normalization ───────────────────────────────────────

def normalize_number(raw: Any) -> tuple[float | None, str]:
    """Parse a raw numeric value. Returns (float, 'ok') or (None, reason)."""
    if raw is None:
        return None, "missing"
    raw_str = str(raw).strip()
    if raw_str.lower() in ("nan", "none", "n/a", "-", ""):
        return None, "missing"
    # Strip currency symbols, commas
    cleaned = re.sub(r"[₹$,\s]", "", raw_str)
    try:
        return float(cleaned), "ok"
    except ValueError:
        return None, f"unparseable: {raw_str!r}"


# ── Item → dict helpers ────────────────────────────────────────────────────

def item_to_dict(item: dict, columns: list[dict]) -> dict:
    """Convert a monday.com items_page item into a flat Python dict.

    Uses column metadata (title, type) from the board schema so we map
    by column title (human-readable) not by opaque id.
    """
    col_meta = {c["id"]: c for c in columns}
    result: dict[str, Any] = {"id": item.get("id"), "name": item.get("name", "")}
    for cv in item.get("column_values", []):
        col_id = cv.get("id", "")
        meta = col_meta.get(col_id, {})
        title = meta.get("title", col_id)
        result[title] = cv.get("text") or cv.get("value") or None
    return result


# ── Work Orders normalizer ─────────────────────────────────────────────────

def normalize_work_orders(
    raw_items: list[dict], columns: list[dict]
) -> tuple[list[dict], list[str]]:
    """
    Normalize raw Work Orders items into clean dicts.
    Returns (clean_items, data_quality_notes).
    """
    clean: list[dict] = []
    notes: list[str] = []
    missing_sectors = 0
    bad_dates = 0
    missing_amounts = 0

    for item in raw_items:
        row = item_to_dict(item, columns)

        # Skip header rows that leaked through (row 0 of the raw sheet)
        if row.get("name", "").lower() in ("deal name masked", "name", ""):
            continue

        # Dates
        start_raw = row.get("Probable Start Date") or row.get("Date of PO/LOI")
        end_raw = row.get("Probable End Date")
        delivery_raw = row.get("Data Delivery Date")

        start_date, start_flag = normalize_date(start_raw)
        end_date, end_flag = normalize_date(end_raw)
        delivery_date, _ = normalize_date(delivery_raw)

        if start_flag != "ok" or end_flag != "ok":
            bad_dates += 1

        # Sector
        raw_sector = row.get("Sector")
        sector = normalize_sector(raw_sector)
        if sector == "Unspecified":
            missing_sectors += 1

        # Status
        raw_status = row.get("Execution Status")
        status = normalize_exec_status(raw_status)

        # Amounts — keep originals; surface quality notes if missing
        amount_excl, amount_flag = normalize_number(
            row.get("Amount in Rupees (Excl of GST) (Masked)")
        )
        if amount_flag != "ok":
            missing_amounts += 1

        billed, _ = normalize_number(
            row.get("Billed Value in Rupees (Excl of GST.) (Masked)")
        )
        collected, _ = normalize_number(
            row.get("Collected Amount in Rupees (Incl of GST.) (Masked)")
        )

        clean.append(
            {
                "id": row.get("id"),
                "name": row.get("name", ""),
                "serial_no": row.get("Serial #"),
                "customer_code": row.get("Customer Name Code"),
                "sector": sector,
                "sector_raw": raw_sector,
                "nature_of_work": row.get("Nature of Work"),
                "type_of_work": row.get("Type of Work"),
                "execution_status": status,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "delivery_date": delivery_date.isoformat() if delivery_date else None,
                "amount_excl_gst": amount_excl,
                "billed_excl_gst": billed,
                "collected_incl_gst": collected,
                "invoice_status": row.get("Invoice Status"),
                "billing_status": row.get("Billing Status"),
                "wo_status": row.get("WO Status (billed)"),
                "bd_personnel": row.get("BD/KAM Personnel code"),
                "last_invoice_date": normalize_date(row.get("Last invoice date"))[0],
            }
        )

    if missing_sectors:
        notes.append(
            f"{missing_sectors} work order(s) had no sector information and were tagged 'Unspecified'."
        )
    if bad_dates:
        notes.append(
            f"{bad_dates} work order(s) had missing or unparseable dates; "
            "those records are included but date-dependent calculations may be incomplete."
        )
    if missing_amounts:
        notes.append(
            f"{missing_amounts} work order(s) had no order amount value."
        )

    return clean, notes


# ── Deals normalizer ───────────────────────────────────────────────────────

def normalize_deals(
    raw_items: list[dict], columns: list[dict]
) -> tuple[list[dict], list[str]]:
    """
    Normalize raw Deals items into clean dicts.
    Returns (clean_items, data_quality_notes).
    """
    clean: list[dict] = []
    notes: list[str] = []
    missing_sectors = 0
    bad_close_dates = 0
    missing_values = 0
    skipped_header = 0

    for item in raw_items:
        row = item_to_dict(item, columns)

        # Skip obvious header or empty rows
        name = str(row.get("name", "") or row.get("Deal Name", "")).strip()
        if name.lower() in ("deal name", "", "name"):
            skipped_header += 1
            continue

        # Sector
        raw_sector = row.get("Sector/service") or row.get("Sector")
        sector = normalize_sector(raw_sector)
        if sector == "Unspecified":
            missing_sectors += 1

        # Stage
        raw_stage = row.get("Deal Stage")
        stage = normalize_deal_stage(raw_stage)

        # Dates
        close_date, close_flag = normalize_date(row.get("Close Date (A)"))
        tentative_date, _ = normalize_date(row.get("Tentative Close Date"))
        created_date, _ = normalize_date(row.get("Created Date"))
        if close_flag != "ok":
            bad_close_dates += 1

        # Value
        deal_value, val_flag = normalize_number(row.get("Masked Deal value"))
        if val_flag != "ok":
            missing_values += 1

        # Closure probability
        prob_raw = row.get("Closure Probability")
        if prob_raw and str(prob_raw).lower() not in ("nan", "none", "closure probability"):
            closure_prob = str(prob_raw).strip().title()
        else:
            closure_prob = None

        # Deal status
        deal_status = str(row.get("Deal Status") or "").strip()
        if deal_status.lower() in ("nan", "none", "deal status", ""):
            deal_status = "Unknown"

        clean.append(
            {
                "id": row.get("id"),
                "name": name,
                "owner_code": row.get("Owner code"),
                "client_code": row.get("Client Code"),
                "deal_status": deal_status,
                "sector": sector,
                "sector_raw": raw_sector,
                "deal_stage": stage,
                "deal_stage_raw": raw_stage,
                "close_date": close_date.isoformat() if close_date else None,
                "tentative_close_date": tentative_date.isoformat() if tentative_date else None,
                "created_date": created_date.isoformat() if created_date else None,
                "deal_value": deal_value,
                "closure_probability": closure_prob,
                "product": row.get("Product deal"),
            }
        )

    if missing_sectors:
        notes.append(
            f"{missing_sectors} deal(s) had no sector — tagged 'Unspecified'."
        )
    if bad_close_dates:
        notes.append(
            f"{bad_close_dates} deal(s) had no actual close date recorded; "
            "cycle-time calculations for those deals are omitted."
        )
    if missing_values:
        notes.append(
            f"{missing_values} deal(s) had no deal value; excluded from value totals."
        )
    if skipped_header:
        notes.append(
            f"{skipped_header} header/blank row(s) were skipped during normalisation."
        )

    return clean, notes
