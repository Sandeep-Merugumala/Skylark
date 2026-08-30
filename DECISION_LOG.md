# Decision Log — Skylark Drones BI Agent

*Written inline during development, not reconstructed after the fact.*

---

## Assumptions

1. **Timeline (5h vs 6h conflict):** Treated the assignment as a 5-hour constraint with a 1-hour buffer. Prioritized a working end-to-end demo over feature completeness. The brief itself says "document your assumptions and proceed."

2. **Deliverable format (ZIP vs GitHub):** The covering email specifies GitHub; the assignment doc says ZIP. I will do both — push to a public GitHub repo and attach a ZIP. Costs ~2 minutes, removes ambiguity.

3. **Data import:** Both XLSX files were imported into monday.com as-is — no pre-cleaning. The assignment explicitly rewards "Data Resilience," meaning the agent must handle the messiness, not the importer. Cleaning it during import would delete the evidence that I handled it.

4. **Board structure:** The Work Orders sheet has 38 columns (176 rows of actual data) including masked financial figures, multiple date columns, and inconsistent categorical values. The Deals sheet has 12 columns (345 rows), with inconsistent sector naming (e.g., 'Sector/service' column) and many missing close dates. I built normalizers for what was actually there, not for hypothetical clean data.

5. **"Quarter" interpretation:** When the user says "this quarter" without specifying a year, I default to the current calendar year and current calendar quarter. I document this in the system prompt.

6. **Masked data:** All financial figures and company/person names in the dataset are masked (e.g., `WOCOMPANY_002`, `OWNER_003`, `Scooby-Doo`). The agent treats these as real identifiers — it surfaces the masked codes in responses rather than guessing real names.

7. **"Energy sector" in the demo query:** The Work Orders board uses "Powerline" and "Renewables" as sectors — there is no explicit "Energy" sector. My normalizer and the `get_field_values` tool allow the agent to discover this and respond appropriately (likely mapping "energy" → "Powerline" or "Renewables" and explaining the ambiguity).

---

## Key Trade-offs

### 1. Direct GraphQL API vs. monday.com MCP server

**Chose:** Direct GraphQL API  
**Why:** monday.com publishes an official MCP server (`@mondaycom/monday-api-mcp`) and Claude's Messages API supports remote MCP servers natively via `mcp_servers`. This would have been the more "on-brief" path since the assignment names MCP explicitly. However, setting up the MCP token/OAuth surface on top of the tool-layer plumbing added an extra configuration layer that a 5-hour clock couldn't afford to debug. The direct API is 3 lines of auth + a GraphQL string — faster, more transparent, and easier to reason about when something goes wrong.  
**What I'd do with more time:** Swap the tool layer to call the MCP server. It's a contained change in `agent/tools.py` — the rest of the app wouldn't change.

### 2. Single Streamlit app vs. React + FastAPI

**Chose:** Single Streamlit app  
**Why:** Collapses frontend + backend into one codebase, one deploy, no CORS, no API contract. Streamlit's `st.chat_message` pattern is exactly the right abstraction for a conversational agent. The honest downside: it reads as less "traditional full-stack" than a React frontend + separate backend. This is documented in the README. If the evaluator specifically wants to see a split architecture, the same agent/monday/data modules work behind a FastAPI endpoint with a React chat widget in front.

### 3. Claude Sonnet 4.5 vs. Haiku

**Chose:** Claude Sonnet 4.5  
**Why:** This task involves reasoning across multiple tool results, handling ambiguous questions, and producing insight rather than just numbers. Haiku is faster and cheaper but would struggle with the cross-board reasoning. Sonnet's tool-calling quality is noticeably better for multi-step queries.

### 4. 4 tools vs. more

**Chose:** 4 focused tools (query_deals, query_work_orders, get_field_values, cross_reference)  
**Why:** More tools = more surface for the model to pick the wrong one. These four cover all the question types in the brief. `get_field_values` is the key "unlock" — it lets the agent discover actual values in messy categorical columns rather than guessing spellings, which is directly what makes the system robust to inconsistent naming.

### 5. AI coding assistants used

- **Antigravity (Google DeepMind)**: Primary tool for code generation, architecture scaffolding, and producing this documentation. All technical decisions described here were made by me; Antigravity implemented them.
- **Claude**: Used as the runtime LLM and for drafting/reviewing the system prompt content.

---

## "Leadership Updates" — My Interpretation

The assignment leaves this open. My interpretation: a trigger phrase or sidebar button — *"Prepare a leadership update"* — causes the agent to call both boards unconditionally and produce a **structured 4-section digest** rather than a conversational answer:

1. **Pipeline Summary** — open deal count and value, by stage and sector
2. **Operational Snapshot** — work order status breakdown by sector
3. **Data Quality Flags** — explicit list of what the normalizer flagged (missing dates, unrecognized values, etc.)
4. **Key Observations** — 2–3 founder-level insights drawn from the data

I did not build a PDF/slide export because the brief is evaluating *judgment about what a founder needs summarized*, not export pipeline mechanics. The output is formatted markdown rendered in the chat — readable, shareable, and demonstrably correct.

---

## What I'd Do Differently With More Time

1. **MCP integration** — Swap the tool layer to call monday's official MCP server. Given my prior MCP hackathon experience, this is a 2-3 hour contained change that would make the architecture more "on-brief" and more production-ready.

2. **`rapidfuzz` fuzzy matching** — The current alias table handles known mis-spellings. `rapidfuzz` would catch novel mis-spellings at query time (e.g., "Renewbles" → "Renewables") without needing to pre-enumerate all variants.

3. **Response streaming** — Buffer the full Claude response currently, then render it. Proper token-by-token streaming would make the UI feel faster. Streamlit supports this via `st.write_stream`.

4. **In-memory TTL cache** — Each question re-hits the monday.com API. A simple dict + timestamp cache per session would avoid redundant network calls for repeated questions.

5. **Unit tests for normalizers** — `data/normalize.py` functions are pure (no side effects, no I/O). Writing 10–15 unit tests would take 30 minutes and is a clear engineering-quality signal. Skipped for time.

6. **Auth hardening** — Streamlit Community Cloud is public. A production deployment would need user authentication (e.g., st-oauth or a custom login gate) so the board data isn't exposed to the internet.

7. **Richer cross-board join** — Currently the cross-reference tool matches by sector. The two boards also share masked client/company codes (`WOCOMPANY_XXX` vs `COMPANY_XXX`) that could be used for exact-match joins if a consistent key format is enforced during import.

---

## Known Limitations

- **No real-time push** — Data is fetched on query, not pushed. If the board changes mid-conversation, earlier answers in the session may be stale.
- **Rate limits** — The client includes a 60s back-off on 429s, but a session with many questions in quick succession could hit monday.com's complexity budget.
- **Masked identifiers** — All company names and personnel are masked. Responses that reference "WOCOMPANY_002" instead of a real name are correct behavior, not a bug — the data was given masked.
- **Energy sector ambiguity** — The brief's demo query references "energy sector" but the dataset uses "Powerline" and "Renewables" for energy-related work. The agent uses `get_field_values` to surface this and asks for clarification or explains the mismatch.
- **No pagination beyond 100 items shown** — The GraphQL client paginates correctly (all items fetched), but the tool functions cap the `deals` / `work_orders` arrays in the JSON at 50 rows to keep tool results inside the context window. Summaries are computed across all rows before the cap.
