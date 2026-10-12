"""
app.py: GCC Signal Feed (Streamlit).

Sales view: every GCC change in India as one event card, with strength, sources and a
suggested next action. Job seeker view comes in Step 5.

Reads Supabase with the anon (read-only) key: from .env locally, st.secrets when deployed.
Run:  streamlit run app.py
"""

import html
import os
from collections import Counter
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

from lib.events import TYPE_LABELS, TYPE_PRIORITY, group_events

load_dotenv()

st.set_page_config(page_title="GCC Signal Feed", page_icon="📡", layout="wide")

NEW_DAYS = 7     # "New this week" = event started within this many days of today

# Badge colours per signal type: cool = growing, warm = shrinking.
BADGE = {
    "new_centre":   ("#E7F6EC", "#1B7F3B"),
    "expansion":    ("#E6F1FB", "#1F5FA8"),
    "hiring_push":  ("#EEF0FD", "#4338CA"),
    "office_lease": ("#F3EEFC", "#6B3FB8"),
    "layoff":       ("#FDF1E4", "#B45309"),
    "closure":      ("#FDE8E8", "#B42318"),
}

CSS = """
<style>
.block-container {padding-top: 2rem; max-width: 1100px;}
h1 {font-weight: 700; letter-spacing: -0.02em; margin-bottom: 0;}
.tagline {color: #5B6472; font-size: 0.95rem; margin: 0.2rem 0 1.2rem 0;}
div[data-testid="stMetric"] {background: #FFFFFF; border: 1px solid #E4E7EC;
    border-radius: 10px; padding: 0.7rem 1rem;}
div[data-testid="stMetricLabel"] p {color: #5B6472; font-size: 0.8rem;
    text-transform: uppercase; letter-spacing: 0.04em;}
div[data-testid="stMetricValue"] {font-size: 1.6rem; font-weight: 650;}
.coverage {color: #8A94A6; font-size: 0.8rem; margin: 0.4rem 0 1.1rem 0;}
.countline {color: #344054; font-size: 0.92rem; padding-top: 0.45rem;}
.card-head {display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem;}
.company {font-size: 1.12rem; font-weight: 650; color: #1C2430;}
.new {display: inline-block; background: #1F4E79; color: #FFFFFF; font-size: 0.68rem;
    font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; padding: 0.1rem 0.45rem;
    border-radius: 4px; margin-left: 0.5rem; vertical-align: 3px;}
.meta {color: #5B6472; font-size: 0.86rem; margin-top: 0.3rem;}
.badge {display: inline-block; padding: 0.12rem 0.55rem; border-radius: 999px;
    font-size: 0.75rem; font-weight: 600; margin-right: 0.3rem; vertical-align: 2px;}
.dots {font-size: 1rem; letter-spacing: 2px; white-space: nowrap;}
.dots .on {color: #1F4E79;} .dots .off {color: #D0D5DD;}
.dots-label {display: block; text-align: right; color: #8A94A6; font-size: 0.7rem;}
.summary {font-size: 0.97rem; color: #1C2430; margin: 0.55rem 0 0.35rem 0;}
.action {font-size: 0.86rem; color: #344054; background: #F2F4F7; border-radius: 6px;
    padding: 0.35rem 0.6rem; display: inline-block;}
.action b {color: #1F4E79;}
.quote {border-left: 3px solid #D0D5DD; padding-left: 0.7rem; color: #344054;
    font-style: italic; margin: 0.2rem 0 0.8rem 0; font-size: 0.9rem;}
.src {font-size: 0.86rem;}
</style>
"""


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def _secret(name: str) -> str | None:
    """st.secrets on Streamlit Cloud, .env locally."""
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name)


def _db():
    return create_client(_secret("SUPABASE_URL"), _secret("SUPABASE_ANON_KEY"))


@st.cache_data(ttl=600, show_spinner=False)
def load_signals() -> list[dict]:
    rows = (_db().table("signals")
              .select("signal_type,city,signal_date,summary,strength,headcount,evidence,"
                      "gccs(id,name),articles(url,title,publisher,published_at)")
              .execute().data)
    return [{
        "company": r["gccs"]["name"], "gcc_id": r["gccs"]["id"],
        "signal_type": r["signal_type"], "city": r["city"], "signal_date": r["signal_date"],
        "summary": r["summary"], "strength": r["strength"], "headcount": r["headcount"],
        "evidence": r["evidence"], "url": r["articles"]["url"], "title": r["articles"]["title"],
        "publisher": r["articles"]["publisher"], "published_at": r["articles"]["published_at"],
    } for r in rows]


@st.cache_data(ttl=600, show_spinner=False)
def load_coverage() -> dict:
    db = _db()
    return {
        "companies": db.table("gccs").select("id", count="exact").limit(1).execute().count,
        "articles": db.table("articles").select("id", count="exact").limit(1).execute().count,
    }


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
def esc(text) -> str:
    """Escape for HTML, and stop Streamlit treating '$' as LaTeX."""
    return html.escape(str(text or "")).replace("$", "&#36;")


def badge(signal_type: str) -> str:
    bg, fg = BADGE[signal_type]
    return f'<span class="badge" style="background:{bg};color:{fg}">{TYPE_LABELS[signal_type]}</span>'


def dots(n: int) -> str:
    return ('<span class="dots">' + '<span class="on">●</span>' * n
            + '<span class="off">●</span>' * (5 - n) + "</span>")


def is_new(ev: dict) -> bool:
    return ev["date"] >= date.today() - timedelta(days=NEW_DAYS)


def render_card(ev: dict) -> None:
    with st.container(border=True):
        badges = "".join(badge(t) for t in ev["types"])
        new_tag = '<span class="new">New this week</span>' if is_new(ev) else ""
        details = [esc(ev["city"]) if ev["city"] else "City not stated", f"{ev['date']:%d %b %Y}"]
        if ev["headcount"]:
            noun = "jobs affected" if ev["direction"] == "shrinking" else "people planned"
            details.append(f"{ev['headcount']:,} {noun}")
        st.markdown(f"""
<div class="card-head">
  <div>
    <div class="company">{esc(ev["company"])}{new_tag}</div>
    <div class="meta">{badges}{" · ".join(details)}</div>
  </div>
  <div>{dots(ev["strength"])}<span class="dots-label">strength {ev["strength"]}/5</span></div>
</div>
<div class="summary">{esc(ev["summary"])}</div>
<div class="action"><b>Suggested next action:</b> {esc(ev["next_action"])}</div>
""", unsafe_allow_html=True)

        n = len(ev["sources"])
        with st.expander(f"{n} source{'s' if n > 1 else ''}"):
            for src in ev["sources"]:
                when = f" · {date.fromisoformat(src['published_at']):%d %b %Y}" if src["published_at"] else ""
                st.markdown(
                    f'<div class="src"><b>{esc(src["publisher"] or "Source")}</b>{when} · '
                    f'<a href="{esc(src["url"])}" target="_blank">{esc(src["title"] or src["url"])}</a></div>'
                    f'<div class="quote">“{esc(src["evidence"])}”</div>',
                    unsafe_allow_html=True,
                )


def events_csv(events: list[dict]) -> bytes:
    rows = [{
        "company": e["company"],
        "signal_types": "; ".join(TYPE_LABELS[t] for t in e["types"]),
        "direction": e["direction"],
        "city": e["city"] or "",
        "date": e["date"].isoformat(),
        "new_this_week": "yes" if is_new(e) else "",
        "strength": e["strength"],
        "headcount": e["headcount"] or "",
        "summary": e["summary"],
        "suggested_next_action": e["next_action"],
        "source_count": len(e["sources"]),
        "sources": " | ".join(s["url"] for s in e["sources"]),
    } for e in events]
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def sidebar_filters(events: list[dict], first: date, last: date) -> tuple[list[dict], bool]:
    """Returns (filtered events, whether any filter is narrowing the list)."""
    st.sidebar.header("Filters")
    cities = sorted({e["city"] for e in events if e["city"]})
    city_sel = st.sidebar.multiselect("City", cities, placeholder="All cities")
    type_sel = st.sidebar.multiselect("Signal type", TYPE_PRIORITY, format_func=TYPE_LABELS.get,
                                      placeholder="All types")
    direction = st.sidebar.radio("Direction", ["All", "Growing", "Shrinking"], horizontal=True)
    min_strength = st.sidebar.slider("Minimum strength", 1, 5, value=1)

    # Defaults cover all data: earliest to latest SIGNAL date.
    picked = st.sidebar.date_input("Date range", value=(first, last), min_value=first, max_value=last)
    start, end = picked if isinstance(picked, tuple) and len(picked) == 2 else (first, last)

    st.sidebar.caption("Strength: 5 = company-confirmed big move · 1 = rumour. "
                       "Scores are AI-assigned, then capped by rubric rules.")

    active = bool(city_sel or type_sel or direction != "All" or min_strength > 1
                  or (start, end) != (first, last))
    shown = [e for e in events
             if (not city_sel or e["city"] in city_sel)
             and (not type_sel or set(type_sel) & set(e["types"]))
             and (direction == "All" or e["direction"] == direction.lower())
             and e["strength"] >= min_strength
             and e["date"] <= end and e["last_date"] >= start]     # event overlaps the range
    return shown, active


def summary_row(events: list[dict]) -> None:
    cities = Counter(e["city"] for e in events if e["city"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Events", len(events))
    c2.metric("New centres", sum("new_centre" in e["types"] for e in events))
    c3.metric("Layoffs / closures", sum(e["direction"] == "shrinking" for e in events))
    c4.metric("Top city", cities.most_common(1)[0][0] if cities else "–")


def sales_view() -> None:
    signals = load_signals()
    if not signals:
        st.info("No signals yet. Run scripts/extract_signals.py first.")
        return
    events = group_events(signals)
    dates = [date.fromisoformat(s["signal_date"]) for s in signals]
    first, last = min(dates), max(dates)
    shown, active = sidebar_filters(events, first, last)

    summary_row(shown)
    cov = load_coverage()
    st.markdown(f'<div class="coverage">Data as of {last:%d %b %Y} · {cov["companies"]} companies · '
                f'{cov["articles"]} articles · public sources only</div>', unsafe_allow_html=True)

    left, mid, right = st.columns([3, 1.1, 1.1])
    if active:
        count = f"Showing <b>{len(shown)}</b> of {len(events)} events ({len(signals)} signals)"
    else:
        count = f"Showing all <b>{len(events)}</b> events ({len(signals)} signals)"
    left.markdown(f'<div class="countline">{count}</div>', unsafe_allow_html=True)
    order = mid.selectbox("Sort by", ["Newest first", "Strongest first"], label_visibility="collapsed")
    right.download_button("Download CSV", events_csv(shown) if shown else b"",
                          file_name=f"gcc_signal_feed_{date.today():%Y-%m-%d}.csv",
                          mime="text/csv", disabled=not shown, use_container_width=True)

    if order == "Newest first":
        shown.sort(key=lambda e: (e["date"], e["strength"]), reverse=True)
    else:
        shown.sort(key=lambda e: (e["strength"], e["date"]), reverse=True)

    if not shown:
        st.info("No events match these filters.")
    for ev in shown:
        render_card(ev)


def job_seeker_view() -> None:
    st.info("Company Check for job seekers is coming in Step 5.")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
st.markdown(CSS, unsafe_allow_html=True)
st.title("GCC Signal Feed")
st.markdown('<div class="tagline">Every signal is AI-extracted from public news and verified '
            "against its source.</div>", unsafe_allow_html=True)

view = st.segmented_control("View", ["Sales view", "Job seeker view"], default="Sales view",
                            label_visibility="collapsed")

if view == "Job seeker view":
    job_seeker_view()
else:
    sales_view()
