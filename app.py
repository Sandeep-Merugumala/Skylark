"""
app.py — Skylark Drones BI Agent
Streamlit chat UI + agent orchestration.

Run locally:
    streamlit run app.py

Secrets needed (in .streamlit/secrets.toml or Streamlit Cloud):
    GEMINI_API_KEY         = "..."
    MONDAY_API_TOKEN       = "..."
    WORK_ORDERS_BOARD_ID   = "123456789"
    DEALS_BOARD_ID         = "987654321"
"""

import os
import streamlit as st
import base64
from dotenv import load_dotenv

load_dotenv()  # loads .env in local dev; no-op in production

from agent.llm import run_agent, reset_chat
from monday.client import get_me

# ── Page config ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Skylark BI Agent",
    page_icon="assets/logo.jpg",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS — Premium ChatGPT/Claude Aesthetic ───────────────────────────

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    /* Chat Messages styling */
    [data-testid="stChatMessage"] {
        background-color: transparent;
        border: none;
        padding: 1rem 0;
    }
    
    [data-testid="stChatMessage"][data-testid*="user"] {
        background-color: var(--secondary-background-color);
        border-radius: 16px;
        padding: 1rem;
        margin-left: auto;
        margin-right: 0;
        max-width: 80%;
    }

    /* Avatar styling */
    [data-testid="stChatMessageAvatar"] {
        border-radius: 50% !important;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    }

    /* Empty state hero styling */
    .hero-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        margin-top: 10vh;
        margin-bottom: 5vh;
        text-align: center;
    }
    .hero-title {
        font-size: 32px;
        font-weight: 600;
        margin-top: 16px;
        color: #ECECEC;
    }
    .hero-subtitle {
        font-size: 16px;
        color: #A0A0A0;
        margin-top: 8px;
        max-width: 500px;
    }

    /* Quick action buttons (prompt suggestions) */
    .suggestion-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
        max-width: 700px;
        margin: 0 auto 40px auto;
    }
    div[data-testid="stButton"] > button {
        background-color: #2f2f2f !important;
        border: 1px solid #424242 !important;
        border-radius: 12px !important;
        color: #ECECEC !important;
        padding: 12px 16px !important;
        font-size: 14px !important;
        text-align: left !important;
        width: 100% !important;
        height: 100% !important;
        transition: all 0.2s ease !important;
        justify-content: flex-start !important;
    }
    div[data-testid="stButton"] > button:hover {
        background-color: #424242 !important;
        border-color: #63b3ed !important;
        transform: translateY(-2px);
    }
    div[data-testid="stButton"] > button p {
        white-space: normal;
        text-align: left;
    }

    /* Hide Streamlit branding */
    #MainMenu, footer, header { visibility: hidden; }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: #171717 !important;
        border-right: 1px solid #333 !important;
    }
    
    .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 500;
        margin-bottom: 20px;
    }
    .status-connected {
        background: rgba(72, 187, 120, 0.1);
        border: 1px solid rgba(72, 187, 120, 0.3);
        color: #68d391;
    }
    .status-error {
        background: rgba(252, 129, 74, 0.1);
        border: 1px solid rgba(252, 129, 74, 0.3);
        color: #fc814a;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Helpers for images ───────────────────────────────────────────────────────

@st.cache_data
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

logo_path = "assets/logo.jpg"
logo_base64 = get_base64_of_bin_file(logo_path) if os.path.exists(logo_path) else ""
img_html = f'<img src="data:image/jpeg;base64,{logo_base64}" width="80" style="border-radius:50%; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">'

# ── Session state init ───────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []

if "monday_status" not in st.session_state:
    st.session_state.monday_status = None

if "pending_query" not in st.session_state:
    st.session_state.pending_query = None

def check_monday_connection():
    try:
        me = get_me()
        st.session_state.monday_status = ("ok", me.get("name", "Connected"))
    except Exception as e:
        st.session_state.monday_status = ("error", str(e))

if st.session_state.monday_status is None:
    check_monday_connection()


# ── Minimal Sidebar ─────────────────────────────────────────────────────────

with st.sidebar:
    # New chat button at top
    if st.button("➕ New chat", use_container_width=True, key="new_chat"):
        st.session_state.messages = []
        reset_chat()
        st.rerun()
        
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Status
    if st.session_state.monday_status:
        status_code, status_msg = st.session_state.monday_status
        if status_code == "ok":
            st.markdown(f'<div class="status-pill status-connected">● {status_msg}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="status-pill status-error">⚠ Connection Error</div>', unsafe_allow_html=True)
    
    st.markdown(
        """
        <div style="color:#A0A0A0;font-size:12px;line-height:1.6;margin-top:20px;">
        <b>Boards Active</b><br>
        • Work Orders<br>
        • Deals Pipeline<br><br>
        <b>Model</b><br>
        Gemini 3.6 Flash
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Main Chat Area ───────────────────────────────────────────────────────────

# Empty State (Hero)
if len(st.session_state.messages) == 0:
    st.markdown(
        f"""
        <div class="hero-container">
            {img_html if logo_base64 else '🚁'}
            <div class="hero-title">How can I help you today?</div>
            <div class="hero-subtitle">I can query your live monday.com Work Orders and Deals boards.</div>
        </div>
        """, 
        unsafe_allow_html=True
    )
    
    st.markdown('<div class="suggestion-grid">', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📊 Pipeline for energy sector this quarter?"):
            st.session_state.pending_query = "How's our pipeline looking for the energy sector this quarter?"
        if st.button("🔄 Sectors with both active deals & work orders?"):
            st.session_state.pending_query = "Which sectors have both active deals AND active work orders?"
    with col2:
        if st.button("📋 Prepare a leadership update"):
            st.session_state.pending_query = "Prepare a leadership update"
        if st.button("🏗️ Operational status across all work orders?"):
            st.session_state.pending_query = "What's the operational status across all work orders?"
    st.markdown('</div>', unsafe_allow_html=True)

# Render Chat History
for msg in st.session_state.messages:
    # Use logo for assistant, custom emoji for user
    if msg["role"] == "assistant" and os.path.exists(logo_path):
        avatar = logo_path
    elif msg["role"] == "user":
        avatar = "👤"
    else:
        avatar = None
        
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# Handle Input
prompt = st.chat_input("Message Skylark...")

if st.session_state.pending_query and not prompt:
    prompt = st.session_state.pending_query
    st.session_state.pending_query = None

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar=logo_path if os.path.exists(logo_path) else None):
        with st.spinner("Thinking..."):
            try:
                reply_parts = list(run_agent(st.session_state.messages))
                reply = reply_parts[-1] if reply_parts else "(No response)"
            except Exception as e:
                reply = (
                    f"⚠️ **Agent error:** {str(e)}\n\n"
                    "Please check your API keys and Board IDs."
                )
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()
