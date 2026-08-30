"""
agent/llm.py — Gemini agent using google-genai SDK (current, non-deprecated).

Uses explicit FunctionDeclaration objects (avoids pydantic Optional conflicts
with auto-schema generation from Python function signatures).

The tool loop is manual but clean: send message, check for function calls,
execute them, send results back, repeat until a text response arrives.
"""

from __future__ import annotations
import json
import os
from typing import Generator

from google import genai
from google.genai import types as genai_types
import streamlit as st

from agent.tools import query_deals, query_work_orders, get_field_values, cross_reference
from agent.prompts import build_system_prompt
from monday.schema import schema_summary

# Map tool name → Python function
TOOL_FUNCTIONS = {
    "query_deals": query_deals,
    "query_work_orders": query_work_orders,
    "get_field_values": get_field_values,
    "cross_reference": cross_reference,
}

# ── Explicit tool schemas (avoids pydantic Optional inference issues) ─────────

_TOOLS = genai_types.Tool(
    function_declarations=[
        genai_types.FunctionDeclaration(
            name="query_deals",
            description=(
                "Fetch deals from the live Deals pipeline board, optionally filtered. "
                "Use for pipeline, sector, stage, or deal-value questions. "
                "Returns deal list, summary stats, and data quality notes."
            ),
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "sector": genai_types.Schema(type="STRING", description="Sector filter e.g. 'Mining', 'Renewables', 'Powerline'."),
                    "stage": genai_types.Schema(type="STRING", description="Deal stage filter e.g. 'Proposal Sent', 'Negotiations'."),
                    "deal_status": genai_types.Schema(type="STRING", description="Status filter: 'Open', 'Won', 'Dead', 'On Hold'."),
                    "quarter": genai_types.Schema(type="STRING", description="Quarter: 'Q1','Q2','Q3','Q4','this quarter','last quarter'."),
                    "year": genai_types.Schema(type="INTEGER", description="Year for quarter filter e.g. 2025."),
                    "owner_code": genai_types.Schema(type="STRING", description="Owner/BD code e.g. 'OWNER_001'."),
                },
            ),
        ),
        genai_types.FunctionDeclaration(
            name="query_work_orders",
            description=(
                "Fetch work orders from the live Work Orders execution board, optionally filtered. "
                "Use for operational, delivery, billing, or capacity questions. "
                "Returns order list, financial summary, status breakdown, and data quality notes."
            ),
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "sector": genai_types.Schema(type="STRING", description="Sector filter e.g. 'Mining', 'Railways'."),
                    "execution_status": genai_types.Schema(type="STRING", description="Execution status e.g. 'Completed', 'Ongoing', 'Paused'."),
                    "quarter": genai_types.Schema(type="STRING", description="Quarter: 'Q1','Q2','Q3','Q4','this quarter','last quarter'."),
                    "year": genai_types.Schema(type="INTEGER", description="Year for quarter filter."),
                    "invoice_status": genai_types.Schema(type="STRING", description="Invoice status e.g. 'Fully Billed', 'Partially Billed'."),
                    "wo_status": genai_types.Schema(type="STRING", description="WO billing status: 'Open' or 'Closed'."),
                },
            ),
        ),
        genai_types.FunctionDeclaration(
            name="get_field_values",
            description=(
                "Discover actual distinct values in any column of either board. "
                "Use BEFORE filtering when unsure about exact spellings of sectors, stages, or statuses."
            ),
            parameters=genai_types.Schema(
                type="OBJECT",
                required=["board", "field_title"],
                properties={
                    "board": genai_types.Schema(type="STRING", description="Which board: 'deals' or 'work_orders'."),
                    "field_title": genai_types.Schema(type="STRING", description="Column title e.g. 'Sector/service', 'Deal Stage', 'Execution Status'."),
                },
            ),
        ),
        genai_types.FunctionDeclaration(
            name="cross_reference",
            description=(
                "Join Deals and Work Orders boards on shared sector/client codes. "
                "Use for cross-board questions: which sectors have both active deals AND work orders."
            ),
            parameters=genai_types.Schema(
                type="OBJECT",
                properties={
                    "sector": genai_types.Schema(type="STRING", description="Optional sector to scope the cross-reference."),
                    "client_code": genai_types.Schema(type="STRING", description="Optional client code to match on."),
                },
            ),
        ),
    ]
)


def _get_api_key() -> str:
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise RuntimeError("GEMINI_API_KEY not set. Add it to .env or Streamlit secrets.")
        return key


def _get_board_ids() -> tuple[str, str]:
    try:
        wo_id = st.secrets["WORK_ORDERS_BOARD_ID"]
        deals_id = st.secrets["DEALS_BOARD_ID"]
    except Exception:
        wo_id = os.environ.get("WORK_ORDERS_BOARD_ID", "")
        deals_id = os.environ.get("DEALS_BOARD_ID", "")
    return str(wo_id), str(deals_id)


def _get_system_prompt() -> str:
    wo_id, deals_id = _get_board_ids()
    wo_schema = schema_summary(wo_id) if wo_id else "(WORK_ORDERS_BOARD_ID not configured)"
    deals_schema = schema_summary(deals_id) if deals_id else "(DEALS_BOARD_ID not configured)"
    return build_system_prompt(wo_schema, deals_schema)


def _get_client() -> genai.Client:
    return genai.Client(api_key=_get_api_key())


def _build_config() -> genai_types.GenerateContentConfig:
    return genai_types.GenerateContentConfig(
        system_instruction=_get_system_prompt(),
        tools=[_TOOLS],
        temperature=0.2,
    )


def reset_chat() -> None:
    """Clear the Gemini chat session (call when user clears conversation)."""
    st.session_state.pop("gemini_chat", None)
    for key in ["gemini_client", "gemini_history"]:
        try:
            del st.session_state[key]
        except (KeyError, AttributeError):
            pass


def _get_or_create_session() -> tuple[genai.Client, list]:
    """Return (client, history_list). History is stored in session_state."""
    if "gemini_client" not in st.session_state:
        st.session_state["gemini_client"] = _get_client()
    if "gemini_history" not in st.session_state:
        st.session_state["gemini_history"] = []
    return st.session_state["gemini_client"], st.session_state["gemini_history"]


def run_agent(messages: list[dict]) -> Generator[str, None, None]:
    """
    Run the Gemini tool-calling loop for the latest user message.

    Maintains a history of Content objects in st.session_state.gemini_history
    for multi-turn conversation memory.
    """
    # Extract last user message
    last_user_msg = ""
    for m in reversed(messages):
        if m["role"] == "user":
            last_user_msg = m["content"]
            break

    if not last_user_msg:
        yield "Please ask a question."
        return

    try:
        client, history = _get_or_create_session()
        config = _build_config()

        # Add user turn to history
        history.append(
            genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=last_user_msg)],
            )
        )

        max_tool_rounds = 8
        for _ in range(max_tool_rounds):
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=history,
                config=config,
            )

            candidate = response.candidates[0] if response.candidates else None
            if not candidate:
                yield "(No response — please try again.)"
                return

            # Add model response to history
            history.append(candidate.content)

            # Check if model wants to call tools
            function_calls = [
                p for p in candidate.content.parts
                if hasattr(p, "function_call") and p.function_call
            ]

            if not function_calls:
                # Final text response
                text = "".join(
                    p.text for p in candidate.content.parts
                    if hasattr(p, "text") and p.text
                )
                yield text or "(No response — please try rephrasing.)"
                return

            # Execute tool calls and collect results
            tool_results = []
            for part in function_calls:
                fc = part.function_call
                func_name = fc.name
                func_args = dict(fc.args) if fc.args else {}

                tool_func = TOOL_FUNCTIONS.get(func_name)
                if tool_func is None:
                    result_str = json.dumps({"error": f"Unknown tool: {func_name}"})
                else:
                    try:
                        result_str = tool_func(**func_args)
                    except Exception as e:
                        result_str = json.dumps({"error": f"Tool '{func_name}' error: {str(e)}"})

                tool_results.append(
                    genai_types.Part(
                        function_response=genai_types.FunctionResponse(
                            name=func_name,
                            response={"result": result_str},
                        )
                    )
                )

            # Add tool results to history and loop
            history.append(
                genai_types.Content(role="user", parts=tool_results)
            )

        yield (
            "⚠️ The agent reached its maximum tool-call limit. "
            "Try rephrasing or narrowing your question."
        )

    except Exception as e:
        err = str(e)
        if "api_key" in err.lower() or "401" in err or "invalid" in err.lower():
            yield "⚠️ **API key error:** Gemini API key is invalid or expired."
        elif "quota" in err.lower() or "429" in err or "resource_exhausted" in err.lower():
            yield "⚠️ **Rate limit hit.** Please wait a moment and try again."
        else:
            yield f"⚠️ **Agent error:** {err}"
