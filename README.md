# GCC Signal Feed

A weekly feed of changes at Global Capability Centres (GCCs) in India: new centres, expansions, hiring pushes, office leases, layoffs and closures. Every signal links to its public source.

- **Sales view:** the full feed, strength scores (1 to 5), and a suggested next action.
- **Company Check:** look up one company to see if it is a real GCC and whether it is growing or shrinking.

Built with Streamlit, Supabase (Postgres + pgvector), Gemini, and Voyage embeddings.

## Setup

```bash
/usr/local/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your keys
```

Run `sql/01_schema.sql` in the Supabase SQL editor.
