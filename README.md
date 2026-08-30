# Skylark Drones — BI Agent 🚁

A **conversational business-intelligence agent** that answers founder-level questions by querying two live monday.com boards — **Work Orders** and **Deals** — dynamically, never from a hardcoded CSV.

**Live demo →** *(add Streamlit Cloud URL after deployment)*  
**GitHub →** *(add repo URL)*

---

## What it does

Ask questions in plain English and get back real insight:

> *"How's our pipeline looking for the energy sector this quarter?"*  
> *"Which sectors have both active deals and active work orders?"*  
> *"Prepare a leadership update"*

The agent:
- Fetches **live data** from monday.com boards via GraphQL (never hardcoded)
- **Normalizes messy data** — inconsistent sector names, multiple date formats, blank cells — and reports what it found/ignored transparently
- **Asks clarifying questions** when a request is ambiguous (e.g., no timeframe given)
- **Reasons across both boards** for cross-sector analysis
- Produces a **structured leadership update** on demand

---

## Architecture

```
skylark-bi-agent/
├── app.py                  # Streamlit chat UI + session management
├── agent/
│   ├── llm.py              # Claude tool-calling loop
│   ├── tools.py            # 4 tool functions exposed to the LLM
│   └── prompts.py          # Dynamic system prompt (injects live board schema)
├── monday/
│   ├── client.py           # GraphQL wrapper, auth, pagination
│   └── schema.py           # Cached board schema loader
├── data/
│   └── normalize.py        # Date/sector/stage/amount normalizers
├── requirements.txt
├── .env.example
└── DECISION_LOG.md
```

**Key architectural decisions:**

| Decision | Choice | Why |
|---|---|---|
| UI + Backend | Single Streamlit app | Removes CORS / two-deploy overhead in a 5–6h window |
| LLM | Claude Sonnet 4.5 | Strong tool-calling, good reasoning over semi-structured data |
| monday.com integration | Direct GraphQL API | Simpler auth surface than MCP for a time-boxed build |
| Tool count | 4 focused tools | Fewer tools = less ambiguity for the model |
| Data cleaning | In normalization layer, not on import | Preserves real-world messiness for agent to handle |

### Tool architecture

```
query_deals          — Fetch + filter Deals board
query_work_orders    — Fetch + filter Work Orders board
get_field_values     — Discover actual distinct values in any column
cross_reference      — Join both boards by shared sector/client codes
```

### Agent loop

```
User message
     ↓
Claude API (with TOOLS + live schema in system prompt)
     ↓ stop_reason = "tool_use"
Run Python tool function(s)
     ↓
Send tool_result(s) back to Claude
     ↓ stop_reason = "end_turn"
Stream final text reply to UI
```

---

## Data Quality Approach

The data is intentionally messy (real-world). The agent handles:

- **Inconsistent sector naming** → alias table + `.lower()` fuzzy fallback
- **Multiple date formats** → `python-dateutil` fuzzy parser
- **Missing values** → tracked per-query, surfaced in agent response (never silently dropped)
- **Header rows in data** → detected and skipped at normalization
- **Mixed numeric formats** → stripped of currency symbols, commas before parsing

Every response that uses filtered data also includes a "Data Quality Notes" section telling the founder exactly what was skipped and why.

---

## Setup

### Prerequisites

- Python 3.10+
- A monday.com account with two boards set up (see below)
- An Anthropic API key

### 1. Clone and install

```bash
git clone <repo-url>
cd skylark-bi-agent
pip install -r requirements.txt
```

### 2. Set up monday.com boards

1. Create two boards in monday.com: **Work Orders** and **Deals**
2. Import the provided XLSX files as-is (don't clean the data — the agent handles that)
3. Get your API token: profile picture → **Developers** → API Token
4. Get board IDs from the URL: `app.monday.com/boards/XXXXXXXXX`

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your values:
# ANTHROPIC_API_KEY=sk-ant-...
# MONDAY_API_TOKEN=...
# WORK_ORDERS_BOARD_ID=...
# DEALS_BOARD_ID=...
```

### 4. Run locally

```bash
streamlit run app.py
```

---

## Deployment (Streamlit Community Cloud)

1. Push repo to GitHub (make sure `.env` is in `.gitignore`)
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app → select repo
3. Add secrets in **Settings → Secrets**:

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
MONDAY_API_TOKEN = "..."
WORK_ORDERS_BOARD_ID = "123456789"
DEALS_BOARD_ID = "987654321"
```

4. Deploy — public URL generated automatically

**Note:** Free tier apps sleep after inactivity; first load after sleep takes ~30s.

---

## Example Queries

| Question | What the agent does |
|---|---|
| *"How's our pipeline for energy sector this quarter?"* | Calls `query_deals(sector="Energy", quarter="this quarter")`, returns count, value, stage breakdown + interpretation |
| *"Which sectors have both deals and work orders?"* | Calls `cross_reference()`, shows overlap with counts |
| *"Prepare a leadership update"* | Calls both boards, produces structured digest with pipeline + ops + data quality flags |
| *"How's the pipeline?"* (no context) | Asks one clarifying question (which sector? which time window?) |
| *"Show me paused work orders"* | Calls `query_work_orders(execution_status="Paused")` |

---

## What's complete vs. what's left

### ✅ Completed
- Live monday.com GraphQL integration (auth, pagination, error handling)
- 4-tool agent with Claude Sonnet 4.5
- Data normalization for dates, sectors, deal stages, amounts
- Cross-board analysis
- Clarifying-question behavior (via system prompt)
- Leadership update mode
- Data-quality transparency (never silent about bad data)
- Dark-themed Streamlit UI with quick-action sidebar
- Dynamic system prompt with live board schema

### 🔲 Not done / would improve with more time
- **MCP integration**: monday.com publishes an official MCP server; swapping the tool layer to call it is a clean, contained change — documented as the preferred production path in DECISION_LOG.md
- **Fuzzy matching**: `rapidfuzz` for near-duplicate sector names the alias table doesn't catch
- **Response streaming**: stream Claude's output token-by-token rather than buffering the full response
- **Caching**: in-memory TTL cache for repeated monday.com queries within a session
- **Unit tests**: normalize functions are pure and easy to test — skipped for time
- **Auth/multi-user**: Streamlit Community Cloud is public; a production version would need user auth

---

## AI Tools Used

- **Antigravity (Google DeepMind)** — primary coding assistant for scaffolding, code generation, and architecture decisions
- **Claude** — both as the runtime agent LLM and for drafting system prompts and documentation

---

## Challenges

1. **Board schema inspection**: monday.com's GraphQL `column_values` returns text/value per item but the mapping between column ID and title requires a separate schema call — handled by `schema.py`
2. **Messy data header rows**: the XLSX files have the column names as row 0 but also as the first data row — required explicit skip logic in normalizers
3. **Tool loop complexity**: making Claude call multiple tools per turn (e.g. both `query_deals` and `query_work_orders`) required careful message history management in the loop
