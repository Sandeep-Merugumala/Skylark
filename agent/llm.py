"""
agent/llm.py — Claude API tool-calling loop.

Implements the classic tool-use loop:
  1. Call messages.create() with tools.
  2. If stop_reason == 'tool_use', run the matching Python function.
  3. Send tool_result back.
  4. Repeat until stop_reason == 'end_turn'.

Max iterations guard prevents infinite loops on edge cases.
"""

from __future__ import annotations
import json
import os
from typing import Generator

import anthropic
import streamlit as st

from agent.tools import TOOLS, TOOL_FUNCTIONS
from agent.prompts import build_system_prompt
from monday.schema import schema_summary


def _get_api_key() -> str:
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set. Add it to .env or Streamlit secrets.")
        return key


def _get_board_ids() -> tuple[str, str]:
    try:
        wo_id = st.secrets["WORK_ORDERS_BOARD_ID"]
        deals_id = st.secrets["DEALS_BOARD_ID"]
    except Exception:
        wo_id = os.environ.get("WORK_ORDERS_BOARD_ID", "")
        deals_id = os.environ.get("DEALS_BOARD_ID", "")
    return str(wo_id), str(deals_id)


def get_system_prompt() -> str:
    """Build system prompt with live schema (cached by schema_summary)."""
    wo_id, deals_id = _get_board_ids()
    wo_schema = schema_summary(wo_id) if wo_id else "(WORK_ORDERS_BOARD_ID not configured)"
    deals_schema = schema_summary(deals_id) if deals_id else "(DEALS_BOARD_ID not configured)"
    return build_system_prompt(wo_schema, deals_schema)


def run_agent(messages: list[dict]) -> Generator[str, None, None]:
    """
    Run the agent tool-calling loop for a given conversation history.
    Yields text chunks as the agent produces them (streaming-style for UI).

    Messages format: list of {"role": "user"|"assistant", "content": str}
    """
    client = anthropic.Anthropic(api_key=_get_api_key())
    system = get_system_prompt()

    # Convert simple string messages to the Anthropic content format
    api_messages = []
    for m in messages:
        api_messages.append({"role": m["role"], "content": m["content"]})

    max_iterations = 8  # guard against infinite tool loops
    iteration = 0
    tool_results_buffer: list[dict] = []

    while iteration < max_iterations:
        iteration += 1

        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            system=system,
            tools=TOOLS,
            messages=api_messages,
        )

        # Collect all content blocks from this response
        text_blocks = []
        tool_use_blocks = []

        for block in response.content:
            if block.type == "text":
                text_blocks.append(block.text)
            elif block.type == "tool_use":
                tool_use_blocks.append(block)

        if response.stop_reason == "end_turn":
            # Done — yield the final text
            yield "".join(text_blocks)
            return

        if response.stop_reason == "tool_use" and tool_use_blocks:
            # Append the assistant's response (with tool_use blocks) to history
            api_messages.append({"role": "assistant", "content": response.content})

            # Execute each tool call
            tool_results = []
            for tool_block in tool_use_blocks:
                func_name = tool_block.name
                func_args = tool_block.input or {}

                tool_func = TOOL_FUNCTIONS.get(func_name)
                if tool_func is None:
                    result_str = json.dumps({"error": f"Unknown tool: {func_name}"})
                else:
                    try:
                        result_str = tool_func(**func_args)
                    except Exception as e:
                        result_str = json.dumps({"error": f"Tool error: {str(e)}"})

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result_str,
                })

            # Send tool results back
            api_messages.append({"role": "user", "content": tool_results})
            continue  # loop back for the next LLM call

        # Unexpected stop_reason — yield whatever text we have
        if text_blocks:
            yield "".join(text_blocks)
        else:
            yield "(Agent finished without a response. Please try again.)"
        return

    yield (
        "⚠️ The agent reached its maximum number of tool calls without a final answer. "
        "This usually means the question is very complex. Please try rephrasing or narrowing your question."
    )
