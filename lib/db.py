"""
db.py: one place to create the Supabase client.

Laptop scripts use the service key (can write).
The Streamlit site will use the anon key (read-only, enforced by RLS).
"""

import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


def get_client(write: bool = False) -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY" if write else "SUPABASE_ANON_KEY"]
    return create_client(url, key)
