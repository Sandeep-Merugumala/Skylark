"""
app.py — Skylark Drones BI Agent
Streamlit chat UI + agent orchestration.

Run locally:
    streamlit run app.py

Secrets needed (in .streamlit/secrets.toml or Streamlit Cloud):
    ANTHROPIC_API_KEY      = "sk-ant-..."
    MONDAY_API_TOKEN       = "..."
    WORK_ORDERS_BOARD_ID   = "123456789"
    DEALS_BOARD_ID         = "987654321"
"""

import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # loads .env in local dev; no-op in production

from agent.llm import run_agent, reset_chat
from monday.client import get_me

# ── Page config ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Skylark BI Agent",
    page_icon="🚁",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS — premium dark theme ─────────────────────────────────────────

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Background */
    .stApp {
        background: linear-gradient(135deg, #0a0e1a 0%, #0d1526 50%, #0a1020 100%);
        min-height: 100vh;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: rgba(15, 22, 40, 0.95);
        border-right: 1px solid rgba(99, 179, 237, 0.15);
    }

    /* Chat messages */
    [data-testid="stChatMessage"] {
        background: rgba(255,255,255,0.04);
        border-radius: 12px;
        border: 1px solid rgba(255,255,255,0.07);
        margin-bottom: 12px;
        padding: 4px 8px;
        backdrop-filter: blur(10px);
    }

    /* User messages */
    [data-testid="stChatMessage"][data-testid*="user"] {
        background: rgba(99, 179, 237, 0.08);
        border-color: rgba(99, 179, 237, 0.2);
    }

    /* Chat input */
    [data-testid="stChatInput"] textarea {
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(99,179,237,0.3) !important;
        border-radius: 12px !important;
        color: #e2e8f0 !important;
        font-family: 'Inter', sans-serif !important;
    }

    [data-testid="stChatInput"] textarea:focus {
        border-color: rgba(99,179,237,0.6) !important;
        box-shadow: 0 0 0 2px rgba(99,179,237,0.15) !important;
    }

    /* Status pill */
    .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 500;
    }
    .status-connected {
        background: rgba(72, 187, 120, 0.15);
        border: 1px solid rgba(72, 187, 120, 0.4);
        color: #68d391;
    }
    .status-error {
        background: rgba(252, 129, 74, 0.15);
        border: 1px solid rgba(252, 129, 74, 0.4);
        color: #fc814a;
    }

    /* Metric cards in sidebar */
    .metric-card {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 10px;
        padding: 12px 16px;
        margin-bottom: 10px;
    }
    .metric-label {
        font-size: 11px;
        color: #718096;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 4px;
    }
    .metric-value {
        font-size: 20px;
        font-weight: 600;
        color: #e2e8f0;
    }

    /* Quick-action buttons */
    div[data-testid="stButton"] > button {
        background: rgba(99,179,237,0.08) !important;
        border: 1px solid rgba(99,179,237,0.25) !important;
        border-radius: 8px !important;
        color: #90cdf4 !important;
        font-size: 13px !important;
        font-family: 'Inter', sans-serif !important;
        transition: all 0.2s ease !important;
        text-align: left !important;
        width: 100% !important;
    }
    div[data-testid="stButton"] > button:hover {
        background: rgba(99,179,237,0.16) !important;
        border-color: rgba(99,179,237,0.5) !important;
        transform: translateX(3px) !important;
    }

    /* Title area */
    .hero-title {
        font-size: 28px;
        font-weight: 700;
        background: linear-gradient(135deg, #63b3ed, #9f7aea, #63b3ed);
        background-clip: text;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 4px;
    }
    .hero-sub {
        color: #718096;
        font-size: 14px;
        margin-bottom: 24px;
    }

    /* Spinner */
    .stSpinner > div {
        border-color: #63b3ed !important;
    }

    /* Scrollbar */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(99,179,237,0.3); border-radius: 3px; }

    /* Hide Streamlit branding */
    #MainMenu, footer { visibility: hidden; }
    header { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Session state init ───────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []

if "monday_status" not in st.session_state:
    st.session_state.monday_status = None  # None = unchecked

if "pending_query" not in st.session_state:
    st.session_state.pending_query = None


# ── Helper: check monday.com connectivity ───────────────────────────────────

def check_monday_connection():
    try:
        me = get_me()
        st.session_state.monday_status = ("ok", me.get("name", "Connected"))
    except Exception as e:
        st.session_state.monday_status = ("error", str(e))


if st.session_state.monday_status is None:
    check_monday_connection()


# ── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🚁 Skylark BI Agent")
    st.markdown("---")

    # Connection status
    if st.session_state.monday_status:
        status_code, status_msg = st.session_state.monday_status
        if status_code == "ok":
            st.markdown(
                f'<div class="status-pill status-connected">● monday.com connected — {status_msg}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="status-pill status-error">⚠ monday.com error</div>',
                unsafe_allow_html=True,
            )
            st.caption(f"Error: {status_msg[:120]}")

    st.markdown("---")

    # Quick-action prompts
    st.markdown("**Quick Questions**")
    quick_questions = [
        "📊 How's our pipeline looking for the energy sector this quarter?",
        "🏗️ What's the operational status across all work orders?",
        "💰 Which sectors have the highest total deal value?",
        "🔄 Which sectors have both active deals AND active work orders?",
        "📋 Prepare a leadership update",
        "⚠️ Show me deals with no close date or value",
        "📈 What's the breakdown of deals by pipeline stage?",
        "🎯 How many deals are in Negotiations or beyond?",
    ]

    for q in quick_questions:
        if st.button(q, key=f"quick_{q[:20]}"):
            st.session_state.pending_query = q

    st.markdown("---")

    # Clear chat
    if st.button("🗑️ Clear conversation", key="clear_chat"):
        st.session_state.messages = []
        reset_chat()  # also resets the Gemini chat session
        st.rerun()

    st.markdown("---")
    st.markdown(
        """
        <div style="color:#4a5568;font-size:11px;line-height:1.6;">
        <b>Data Sources</b><br>
        • Work Orders board (live)<br>
        • Deals pipeline board (live)<br><br>
        <b>Model</b><br>
        Gemini 2.0 Flash<br><br>
        <b>Note</b><br>
        All data fetched live from monday.com. 
        Numbers include data-quality caveats where applicable.
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Main chat area ───────────────────────────────────────────────────────────

col_main, col_right = st.columns([3, 1])

with col_main:
    st.markdown('<div class="hero-title">🚁 Skylark Drones BI Agent</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="hero-sub">Ask any founder-level question about your pipeline or operations — '
        'data pulled live from monday.com.</div>',
        unsafe_allow_html=True,
    )

    # Render conversation history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Handle pending query from sidebar buttons
    prompt = st.chat_input("Ask about pipeline, work orders, sectors, revenue...")

    if st.session_state.pending_query and not prompt:
        prompt = st.session_state.pending_query
        st.session_state.pending_query = None

    if prompt:
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Run agent and display response
        with st.chat_message("assistant"):
            with st.spinner("Checking monday.com boards..."):
                try:
                    reply_parts = list(run_agent(st.session_state.messages))
                    reply = reply_parts[-1] if reply_parts else "(No response)"
                except Exception as e:
                    reply = (
                        f"⚠️ **Agent error:** {str(e)}\n\n"
                        "Please check that your API keys and Board IDs are configured correctly."
                    )
            st.markdown(reply)

        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()


with col_right:
    st.markdown("**About the boards**")

    wo_id = os.environ.get("WORK_ORDERS_BOARD_ID", "")
    deals_id = os.environ.get("DEALS_BOARD_ID", "")
    try:
        wo_id = st.secrets.get("WORK_ORDERS_BOARD_ID", wo_id)
        deals_id = st.secrets.get("DEALS_BOARD_ID", deals_id)
    except Exception:
        pass

    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">Work Orders Board</div>
            <div class="metric-value">📋</div>
            <div style="color:#718096;font-size:12px;margin-top:4px;">ID: {wo_id or 'not set'}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Deals Board</div>
            <div class="metric-value">💼</div>
            <div style="color:#718096;font-size:12px;margin-top:4px;">ID: {deals_id or 'not set'}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.session_state.messages:
        st.markdown(f"**Messages in session:** {len(st.session_state.messages)}")

    st.markdown("**Try asking:**")
    st.markdown(
        """
        <div style="color:#718096;font-size:12px;line-height:1.8;">
        • "How's our pipeline for energy sector this quarter?"<br>
        • "Show me work orders by sector"<br>
        • "Which sectors are in both boards?"<br>
        • "Prepare a leadership update"<br>
        • "What deals are in negotiations?"
        </div>
        """,
        unsafe_allow_html=True,
    )
