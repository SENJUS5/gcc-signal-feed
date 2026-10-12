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
import voyageai
from dotenv import load_dotenv
from supabase import create_client

from lib import gemini
from lib.ask import NOT_FOUND, ask
from lib.company_check import (CLOSED_MEANING, MEANING, closed_on, direction, find_company,
                               not_verified_note, parent_line,
                               people_lines)
from lib.events import TYPE_LABELS, TYPE_PRIORITY, group_events
from lib.providers import PROVIDERS, find_providers

load_dotenv()

st.set_page_config(page_title="GCC Signal Feed", page_icon="📡", layout="wide")


def _secret(name: str) -> str | None:
    """st.secrets on Streamlit Cloud, .env locally."""
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name)


# The Ask box's helpers (lib/embed.py, lib/gemini.py) read keys from the environment.
# On Streamlit Cloud the keys live in st.secrets, so copy just these over.
# The Supabase service key is never used by the website.
for _key in ("VOYAGE_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL"):
    if not os.environ.get(_key) and _secret(_key):
        os.environ[_key] = _secret(_key)

NEW_DAYS = 7     # "New this week" = event started within 7 days of the LATEST signal in the data
                 # (not today), so the label still makes sense when the app is opened later

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
/* Company Check (job seeker view) */
.cc-name {font-size: 1.5rem; font-weight: 700; color: #1C2430; letter-spacing: -0.01em;}
.cc-meta {color: #5B6472; font-size: 0.92rem; margin: 0.2rem 0 0.9rem 0;}
.cc-row {display: flex; gap: 0.8rem; flex-wrap: wrap; margin-bottom: 0.9rem;}
.cc-box {flex: 1 1 260px; border: 1px solid #E4E7EC; border-radius: 10px; padding: 0.75rem 0.9rem;
    background: #FFFFFF;}
.cc-label {color: #8A94A6; font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.05em; margin-bottom: 0.3rem;}
.cc-status {font-size: 1.05rem; font-weight: 650;}
.cc-note {color: #5B6472; font-size: 0.85rem; margin-top: 0.25rem;}
.cc-meaning {background: #F2F6FB; border-left: 4px solid #1F4E79; border-radius: 6px;
    padding: 0.65rem 0.9rem; font-size: 0.95rem; color: #1C2430; margin-bottom: 0.9rem;}
.tl-item {display: flex; gap: 0.9rem; padding: 0.55rem 0; border-bottom: 1px solid #F0F2F5;}
.tl-date {flex: 0 0 92px; color: #5B6472; font-size: 0.85rem; padding-top: 0.1rem;}
.tl-dot {flex: 0 0 10px; height: 10px; border-radius: 50%; margin-top: 0.38rem;}
.tl-body {font-size: 0.94rem; color: #1C2430;}
.tl-src {font-size: 0.8rem; color: #5B6472; margin-top: 0.15rem;}
.disclaimer {color: #8A94A6; font-size: 0.8rem; margin-top: 1.4rem;}
/* Providers */
.pv-name {font-size: 1.12rem; font-weight: 650; color: #1C2430;}
.pv-kind {display: inline-block; background: #F2F4F7; color: #344054; font-size: 0.72rem;
    font-weight: 600; padding: 0.1rem 0.5rem; border-radius: 999px; margin-left: 0.5rem; vertical-align: 2px;}
.pv-with {color: #5B6472; font-size: 0.88rem; margin: 0.25rem 0 0.6rem 0;}
.pv-company {font-weight: 600; font-size: 0.9rem; color: #1C2430; margin-top: 0.3rem;}
/* Ask */
.answer {font-size: 1rem; line-height: 1.6; color: #1C2430;}
.answer ul {margin: 0; padding-left: 1.2rem;} .answer li {margin-bottom: 0.4rem;}
.cite {display: inline-block; font-size: 0.72rem; font-weight: 700; color: #1F4E79;
    background: #E6F1FB; border-radius: 4px; padding: 0 0.3rem; margin-left: 0.15rem;
    text-decoration: none; vertical-align: 2px;}
.notfound {font-size: 1rem; color: #5B6472;}
.srclist {margin-top: 0.4rem;}
.srcrow {font-size: 0.87rem; padding: 0.3rem 0; border-bottom: 1px solid #F0F2F5;}
.srcrow .num {display: inline-block; width: 1.8rem; font-weight: 700; color: #1F4E79;}
.srcrow.unused {color: #98A2B3;} .srcrow.unused .num {color: #98A2B3;}
.srcrow.unused a {color: #98A2B3;}
</style>
"""


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
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
def load_gccs() -> list[dict]:
    return (_db().table("gccs")
              .select("id,name,parent_company,hq_country,industry,india_cities,is_verified_gcc,verified_source")
              .order("name").execute().data)


@st.cache_data(ttl=600, show_spinner=False)
def load_articles() -> list[dict]:
    return (_db().table("articles")
              .select("gcc_id,url,title,publisher,published_at,content").execute().data)


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


def render_card(ev: dict) -> None:
    with st.container(border=True):
        badges = "".join(badge(t) for t in ev["types"])
        new_tag = '<span class="new">New this week</span>' if ev["is_new"] else ""
        details = [esc(", ".join(ev["cities"])) if ev["cities"] else "City not stated",
                   f"{ev['date']:%d %b %Y}"]
        if ev["headcount_text"]:
            details.append(esc(ev["headcount_text"]))
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
        "cities": ", ".join(e["cities"]),
        "date": e["date"].isoformat(),
        "new_this_week": "yes" if e["is_new"] else "",
        "strength": e["strength"],
        "headcount": e["headcount_text"] or "",
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
    cities = sorted({c for e in events for c in e["cities"]})
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
             if (not city_sel or set(city_sel) & set(e["cities"]))
             and (not type_sel or set(type_sel) & set(e["types"]))
             and (direction == "All" or e["direction"] == direction.lower())
             and e["strength"] >= min_strength
             and e["date"] <= end and e["last_date"] >= start]     # event overlaps the range
    return shown, active


def summary_row(events: list[dict]) -> None:
    cities = Counter(c for e in events for c in e["cities"])
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
    for ev in events:
        ev["is_new"] = ev["date"] >= last - timedelta(days=NEW_DAYS)
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


DIRECTION_STYLE = {   # (text colour, background) for the plain-words direction
    "Growing": ("#1B7F3B", "#E7F6EC"),
    "Shrinking": ("#B42318", "#FDE8E8"),
    "Mixed": ("#B45309", "#FDF1E4"),
    "No recent news": ("#5B6472", "#F2F4F7"),
}


def render_company(company: dict, events: list[dict]) -> None:
    trend = direction(events)
    fg, bg = DIRECTION_STYLE[trend]
    meta = [m for m in (parent_line(company["name"], company["parent_company"]),
                        company["hq_country"] and f"HQ: {company['hq_country']}",
                        company["industry"],
                        company["india_cities"] and "India: " + ", ".join(company["india_cities"])) if m]

    closed = closed_on(events)
    link = (f' · <a href="{esc(company["verified_source"])}" target="_blank">source</a>'
            if company["verified_source"] else "")
    if closed:
        status = "Was a GCC" if company["is_verified_gcc"] else "India centre"
        gcc = (f'<div class="cc-status" style="color:#B42318">{status} · centre closed ({closed:%d %b %Y})</div>'
               f'<div class="cc-note">Public news reports this India centre has been shut down{link}</div>')
    elif company["is_verified_gcc"]:
        gcc = (f'<div class="cc-status" style="color:#1B7F3B">✓ Verified GCC</div>'
               f'<div class="cc-note">A public source describes it as a Global Capability Centre{link}</div>')
    else:
        gcc = (f'<div class="cc-status" style="color:#5B6472">Not verified as a GCC</div>'
               f'<div class="cc-note">{esc(not_verified_note(company["name"]))}</div>')

    st.markdown(f"""
<div class="cc-name">{esc(company["name"])}</div>
<div class="cc-meta">{" · ".join(esc(m) for m in meta)}</div>
<div class="cc-row">
  <div class="cc-box"><div class="cc-label">Is it a real GCC?</div>{gcc}</div>
  <div class="cc-box" style="background:{bg};border-color:{bg}">
    <div class="cc-label">Direction (last 90 days)</div>
    <div class="cc-status" style="color:{fg}">{trend}</div>
    <div class="cc-note">{"<br>".join(esc(l) for l in people_lines(events)) or "No headcount numbers stated in the news."}</div>
  </div>
</div>
<div class="cc-meaning"><b>What this means for you:</b> {esc(CLOSED_MEANING if closed else MEANING[trend])}</div>
""", unsafe_allow_html=True)

    if events:
        st.markdown("**Recent news**")
        items = []
        for ev in sorted(events, key=lambda e: e["date"], reverse=True):
            dot = DIRECTION_STYLE["Shrinking" if ev["direction"] == "shrinking" else "Growing"][0]
            links = " · ".join(f'<a href="{esc(s["url"])}" target="_blank">{esc(s["publisher"] or "source")}</a>'
                               for s in ev["sources"])
            items.append(f'<div class="tl-item"><div class="tl-date">{ev["date"]:%d %b %Y}</div>'
                         f'<div class="tl-dot" style="background:{dot}"></div>'
                         f'<div><div class="tl-body">{esc(ev["summary"])}</div>'
                         f'<div class="tl-src">Source: {links}</div></div></div>')
        st.markdown("".join(items), unsafe_allow_html=True)


def job_seeker_view() -> None:
    """Company Check: one company at a time. No scores, no sales actions, no full feed."""
    gccs = load_gccs()
    names = [g["name"] for g in gccs]
    st.markdown("#### Company Check")
    st.caption("Got an offer or interview at a GCC? Check if it's a real GCC and whether it's growing or shrinking.")
    signals = load_signals()
    latest = max((date.fromisoformat(s["signal_date"]) for s in signals), default=None)
    as_of = f"Data as of {latest:%d %b %Y} · " if latest else ""
    st.markdown(f'<div class="coverage">{as_of}{len(names)} companies · public news only</div>',
                unsafe_allow_html=True)

    query = st.selectbox("Company", names, index=None, accept_new_options=True,
                         placeholder="Type a company name, e.g. DoorDash",
                         label_visibility="collapsed")
    if query:
        name = find_company(query, names)
        if name is None:
            st.warning(f"We don't track this company yet. We currently cover {len(names)} companies "
                       "from public news.")
        else:
            company = next(g for g in gccs if g["name"] == name)
            events = [e for e in group_events(signals) if e["gcc_id"] == company["id"]]
            with st.container(border=True):
                render_company(company, events)

    st.markdown('<div class="disclaimer">Based on public news only. Not career or financial advice.</div>',
                unsafe_allow_html=True)


EXAMPLE_QUESTIONS = [
    "Which companies are hiring in Hyderabad?",
    "Any layoffs in Bengaluru?",
    "Which GCCs opened in Pune recently?",
]


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def cached_answer(question: str) -> dict:
    """Same question (after tidying) -> same answer, without spending free-tier quota.
    Errors aren't cached, so a quota failure is retried next time."""
    return ask(_db(), question)


def _set_question(q: str) -> None:
    st.session_state["ask_q"] = q
    st.session_state["ask_go"] = True


def render_answer(result: dict) -> None:
    sources = {s["n"]: s for s in result["sources"]}
    with st.container(border=True):
        if result["found"]:
            def chips(nums):
                return "".join(f'<a class="cite" href="{esc(sources[n]["url"])}" target="_blank">{n}</a>'
                               for n in nums)
            items = "".join(f"<li>{esc(p['text'])} {chips(p['citations'])}</li>" for p in result["points"])
            st.markdown(f'<div class="answer"><ul>{items}</ul></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="notfound">{esc(NOT_FOUND)} The articles below were the '
                        "closest matches, but none answers this question.</div>", unsafe_allow_html=True)
        if result["dropped"]:
            n = len(result["dropped"])
            st.caption(f"{n} AI statement{'s were' if n > 1 else ' was'} removed because "
                       f"{'their sources' if n > 1 else 'its source'} didn't support {'them' if n > 1 else 'it'}.")

        if result["sources"]:
            label = "Sources" if result["found"] else "Closest articles searched"
            rows = []
            for s in result["sources"]:
                used = s["n"] in result["cited"]
                when = f" · {date.fromisoformat(s['published_at']):%d %b %Y}" if s["published_at"] else ""
                rows.append(f'<div class="srcrow{"" if used or not result["found"] else " unused"}">'
                            f'<span class="num">[{s["n"]}]</span><b>{esc(s["publisher"] or "Source")}</b>{when} · '
                            f'<a href="{esc(s["url"])}" target="_blank">{esc(s["title"])}</a>'
                            f'{"" if used or not result["found"] else " · not cited"}</div>')
            st.markdown(f'**{label}**<div class="srclist">{"".join(rows)}</div>', unsafe_allow_html=True)


def ask_view() -> None:
    st.markdown("#### Ask the news")
    st.caption("Plain-English questions, answered only from our tracked public news, with sources. "
               "If the news doesn't say, we say so.")

    cols = st.columns(len(EXAMPLE_QUESTIONS))
    for col, q in zip(cols, EXAMPLE_QUESTIONS):
        col.button(q, on_click=_set_question, args=(q,), use_container_width=True)

    with st.form("ask_form", border=False):
        st.text_input("Question", key="ask_q", placeholder="e.g. Which companies opened new centres in Chennai?",
                      label_visibility="collapsed")
        submitted = st.form_submit_button("Ask", type="primary")

    question = " ".join((st.session_state.get("ask_q") or "").split())
    if (submitted or st.session_state.pop("ask_go", False)) and question:
        try:
            with st.spinner("Searching the news and writing an answer…"):
                result = cached_answer(question.lower().rstrip("?") + "?")
            render_answer(result)
        except gemini.GeminiUnavailable:
            st.info("The AI has used up today's free quota. Please try again later. "
                    "The Sales view and Company Check still work.")
        except voyageai.error.RateLimitError:
            st.info("Lots of questions right now (the free search tier allows a few per minute). "
                    "Please wait a minute and ask again.")
        except Exception:
            st.warning("Sorry, something went wrong while answering. Please try again in a minute.")

    st.markdown('<div class="disclaimer">Answers are AI-written from public news articles and checked for '
                "citations. Always open the source to confirm.</div>", unsafe_allow_html=True)


def providers_view() -> None:
    """Rule-based (no AI): providers named as setup or hiring partners, with the proving sentence."""
    st.markdown("#### Who actually delivers")
    st.markdown('<div class="tagline">Who actually delivers: providers named in public GCC news, with proof.</div>',
                unsafe_allow_html=True)
    articles = load_articles()
    gccs = {g["id"]: g["name"] for g in load_gccs()}
    found = find_providers(articles, gccs)

    for p in found:
        with st.container(border=True):
            companies = ", ".join(l["company"] for l in p["links"])
            blocks = []
            for l in p["links"]:
                src = l["source"]
                when = f" · {date.fromisoformat(src['published_at']):%d %b %Y}" if src["published_at"] else ""
                more = f" · +{len(l['sources']) - 1} more" if len(l["sources"]) > 1 else ""
                blocks.append(
                    f'<div class="pv-company">{esc(l["company"])}</div>'
                    f'<div class="quote">“{esc(l["evidence"])}”</div>'
                    f'<div class="src" style="margin:-0.5rem 0 0.6rem 0"><a href="{esc(src["url"])}" target="_blank">'
                    f'{esc(src["publisher"] or "Source")}</a>{when}{more}</div>')
            st.markdown(f'<div class="pv-name">{esc(p["provider"])}<span class="pv-kind">{esc(p["kind"])}</span></div>'
                        f'<div class="pv-with">Worked with: {esc(companies)}</div>{"".join(blocks)}',
                        unsafe_allow_html=True)

    missing = [name for name in PROVIDERS if name not in {p["provider"] for p in found}]
    if missing:
        st.caption("Also searched for, but not named as a partner in our articles: " + ", ".join(missing) + ".")
    st.markdown(f'<div class="disclaimer">Based on {len(articles)} articles; a provider not listed may simply '
                "not be in our news yet. Found by fixed rules (no AI): a sentence must name the provider, a "
                "tracked GCC and a partnership word.</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
st.markdown(CSS, unsafe_allow_html=True)
st.title("GCC Signal Feed")
st.markdown('<div class="tagline">Every signal is AI-extracted from public news and verified '
            "against its source.</div>", unsafe_allow_html=True)

view = st.segmented_control("View", ["Sales view", "Job seeker view", "Ask", "Providers"],
                            default="Sales view",
                            label_visibility="collapsed")

if view == "Job seeker view":
    job_seeker_view()
elif view == "Ask":
    ask_view()
elif view == "Providers":
    providers_view()
else:
    sales_view()
