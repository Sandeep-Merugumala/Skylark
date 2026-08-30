import os, sys, json
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

# Patch st.secrets for local testing
import streamlit as st
import types

class FakeSecrets:
    def __getitem__(self, key):
        return os.environ[key]
    def get(self, key, default=None):
        return os.environ.get(key, default)

st.secrets = FakeSecrets()

from monday.client import get_board_schema, get_board
from data.normalize import normalize_work_orders, normalize_deals

print("=== Fetching Board Schemas ===")
wo_schema = get_board_schema(os.environ['WORK_ORDERS_BOARD_ID'])
print("Work Orders board name:", wo_schema['name'])
print("Columns:", [c['title'] for c in wo_schema['columns']])

deals_schema = get_board_schema(os.environ['DEALS_BOARD_ID'])
print()
print("Deals board name:", deals_schema['name'])
print("Columns:", [c['title'] for c in deals_schema['columns']])

print()
print("=== Fetching Full Boards ===")
wo_board = get_board(os.environ['WORK_ORDERS_BOARD_ID'])
wo_items = wo_board["all_items"]
print(f"Work Orders: {len(wo_items)} items")

deals_board = get_board(os.environ['DEALS_BOARD_ID'])
deals_items = deals_board["all_items"]
print(f"Deals: {len(deals_items)} items")

print()
print("=== Normalizing Work Orders ===")
clean_wo, wo_notes = normalize_work_orders(wo_items, wo_board["columns"])
print(f"Clean work orders: {len(clean_wo)}")
print("Data quality notes:", wo_notes)
if clean_wo:
    print("Sample:", json.dumps(clean_wo[0], default=str, indent=2))

print()
print("=== Normalizing Deals ===")
clean_deals, deal_notes = normalize_deals(deals_items, deals_board["columns"])
print(f"Clean deals: {len(clean_deals)}")
print("Data quality notes:", deal_notes)
if clean_deals:
    print("Sample:", json.dumps(clean_deals[0], default=str, indent=2))

print()
print("ALL GOOD - boards are live and data normalizes correctly")
