# GCC Signal Feed

A feed of changes at Global Capability Centres (GCCs) in India: new centres, expansions,
hiring pushes, office leases, layoffs and closures. Each change is pulled out of public
news by AI, **checked against its source in code**, and linked to the article it came from.

Built as a prototype for Flexiple's GCC sales team, with a lighter view for job seekers.

**Live app:** https://gcc-signal-feed.streamlit.app/

**Code:** https://github.com/SENJUS5/gcc-signal-feed

## The four views

| View | For | What it shows |
|---|---|---|
| **Sales view** (default) | Flexiple's GCC sales team | Every event as a card: type badges, city, date, strength (1–5 dots), summary, a suggested next action, and every source with its evidence quote. Filters (city, type, growing/shrinking, strength, dates), "New this week" labels, and a CSV download. |
| **Job seeker view** (Company Check) | Someone with an offer or interview at a GCC | One company at a time: is it a verified GCC (with source), is it growing or shrinking in plain words, stated headcounts, a news timeline, and what that means for their interview. Deliberately shows less: no scores, no sales actions, no full feed, no export. |
| **Ask** | Anyone | A plain-English question ("Any layoffs in Bengaluru?") answered only from the tracked articles, with numbered citations. If the news doesn't say, it answers "Not found in our tracked news." |
| **Providers** | Flexiple strategy / partnerships | Which service providers (ANSR, HCLTech, Accenture…) the news names as setup or hiring partners for a GCC, each with the exact sentence as proof. Found by fixed rules, no AI: one sentence must name the provider, a tracked GCC and a partnership word ([lib/providers.py](lib/providers.py)). |

## Architecture

```
 Public news URLs (data/article_urls.csv)
        │  scripts/collect_news.py      fetch, clean to text, de-duplicate by content hash
        ▼
 Supabase: articles ──────────────────────────────┐
        │  scripts/extract_signals.py             │  scripts/embed_articles.py
        │  Gemini → JSON signals (6 fixed types,  │  Voyage voyage-3 embeddings
        │  strength rubric, exact evidence quote) │
        │  CODE CHECKS: evidence must appear in   │
        │  the article, headcount must appear,    │
        │  dates must be sane                     │
        ▼                                         ▼
 Supabase: signals                     articles.embedding + full-text index
        │  scripts/rescore.py (rule-based strength caps)
        │  scripts/manual_corrections.py (recorded human fixes)
        ▼                                         │
 Streamlit app (app.py), read-only anon key      │
   Sales view / Company Check: signals grouped    │
   into events (lib/events.py)                    │
   Ask: question → Voyage → hybrid search (semantic + keyword, Reciprocal Rank Fusion,
        sql/03_search_fns.sql) → top 5 articles → Gemini answer with [n] citations
        → CODE CHECKS: each statement's quote must be in the cited article, and every
          city and number it states must be in that quote's sentence (lib/ask.py)
```

**Design choices worth knowing**

- **AI does the reading; code does the trusting.** Every signal carries an exact quote, and the code drops a signal whose quote isn't in the article. The Ask box applies the same rule to each statement in its answer. Every drop is logged ([data/dropped_signals.csv](data/dropped_signals.csv)).
- **AI scores are capped by rules.** Strength follows a written rubric (in [lib/prompts.py](lib/prompts.py)), and [scripts/rescore.py](scripts/rescore.py) caps scores the AI over-rates. For example, global layoff news with no India number is capped at 3. Changes are logged with the old score.
- **Each event appears once.** The same news usually comes from 2–3 articles. Signals for the same company within 14 days form one card that lists all its sources.
- **Extraction runs offline.** The live site only reads Supabase. The Ask box is the only live AI call, and its answers are cached.

## Run it locally

```bash
/usr/local/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-scripts.txt     # website + laptop scripts
cp .env.example .env                         # then fill in your keys
streamlit run app.py
```

To rebuild the data from scratch: run `sql/01`, `02` and `03` in the Supabase SQL editor. Then run these in order: `collect_news.py`, `extract_signals.py`, `embed_articles.py`, `manual_corrections.py`, `rescore.py` (all in `scripts/`).

`requirements.txt` holds only what the website needs; Streamlit Cloud installs that file. The laptop scripts need the extra packages in `requirements-scripts.txt`.

## Known limits

- **Small, hand-picked coverage.** 21 companies and 41 articles from mid-July to early October 2026, giving 57 signals in 22 events. This is a prototype dataset, not a full market scan.
- **Free-tier AI quotas.**
  - Gemini allows about 20 requests per model per day. The app falls back from gemini-3.8-flash to 3.5-flash to 3.5-flash-lite, and if all are used up, the Ask box shows a friendly message (the other views keep working).
  - Voyage's free tier, without a payment method, allows only 3 searches per minute. Adding a card raises this; the free tokens still apply.
- **The read-only key is public by design.** The website reads Supabase with the anon key, so a technical user could query the tables directly and see strength scores the job seeker view hides. A production version would serve each audience through its own API, or through row-level security tied to a real login.
- **AI scores are only partly checked.** Evidence, headcounts, cities and numbers are verified in code. Strength scores and summaries are AI-written and only rule-capped, so a few summaries were corrected by hand (recorded in `scripts/manual_corrections.py`).
- **"Verified GCC" means a public source calls it a GCC.** Five companies are marked "not verified" because their sources say "tech centre", "talent hub" and similar. The Company Check says so honestly.
- **No Flexiple private data.** Everything comes from public news.
