"""
Full end-to-end test using google-genai SDK.
"""
import os, sys, json
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

import streamlit as st

class FakeSecrets:
    def __getitem__(self, key): return os.environ[key]
    def get(self, key, default=None): return os.environ.get(key, default)
    def __contains__(self, key): return key in os.environ

st.secrets = FakeSecrets()
st.session_state = {}  # Simple dict for testing

print("Test 1: imports...")
from agent.llm import run_agent, reset_chat, _get_client, _TOOLS, TOOL_FUNCTIONS
from agent.tools import query_deals, query_work_orders
print("  OK - all imports")

print("\nTest 2: Tool functions still work...")
result = json.loads(query_deals(sector="Renewables"))
print(f"  Renewables deals: {result['summary']['total_deals']}")
result2 = json.loads(query_work_orders(sector="Mining"))
print(f"  Mining work orders: {result2['summary']['total_work_orders']}")

print("\nTest 3: Gemini client creates successfully...")
client = _get_client()
print(f"  Client: {type(client).__name__}")

print("\nTest 4: Tool schema created...")
print(f"  Functions declared: {[fd.name for fd in _TOOLS.function_declarations]}")

print("\nTest 5: Full Gemini agent call (the assignment's demo query)...")
print("  Q: 'How's our pipeline looking for energy sector this quarter?'")
messages = [{"role": "user", "content": "How's our pipeline looking for energy sector this quarter?"}]
reply = list(run_agent(messages))[-1]
print(f"\n  AGENT RESPONSE:\n{'='*70}")
print(reply)
print('='*70)

print("\nALL TESTS PASSED - ready to run: streamlit run app.py")
