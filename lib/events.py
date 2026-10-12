"""
events.py: group signals into events for the feed.

The same event is often reported by 2-3 articles, and each article gives its own signal row.
Rule: same company + same signal type + dates within 14 days of the event's FIRST date
= one event. (Measured from the first date, so a long chain of reports can't merge
two separate events a month apart.)

An event shows: the earliest date, the highest strength, the summary of its strongest
signal, the most common city, and every distinct source with its evidence quote.
"""

from collections import Counter
from datetime import date

WINDOW_DAYS = 14

TYPE_LABELS = {
    "new_centre": "New centre",
    "expansion": "Expansion",
    "hiring_push": "Hiring push",
    "office_lease": "Office lease",
    "layoff": "Layoff",
    "closure": "Closure",
}

NEXT_ACTION = {
    "new_centre": "New entrant: offer setup and first-hires support",
    "hiring_push": "Scaling: offer hiring support",
    "expansion": "Growing: offer scale-up hiring",
    "office_lease": "Growing: offer scale-up hiring",
    "layoff": "Shrinking: talent now available to recruit; flag account risk",
    "closure": "Shrinking: talent now available to recruit; flag account risk",
}

SHRINKING = {"layoff", "closure"}


def _new_event(s: dict, d: date) -> dict:
    return {"company": s["company"], "gcc_id": s["gcc_id"], "signal_type": s["signal_type"],
            "first_date": d, "last_date": d, "signals": []}


def group_events(signals: list[dict]) -> list[dict]:
    """signals: flat dicts with company, gcc_id, signal_type, signal_date, city, summary,
    strength, headcount, evidence, url, publisher, title, published_at."""
    ordered = sorted(signals, key=lambda s: (s["gcc_id"], s["signal_type"], s["signal_date"]))
    events: list[dict] = []
    for s in ordered:
        d = date.fromisoformat(s["signal_date"])
        ev = events[-1] if events else None
        if (ev is None or ev["gcc_id"] != s["gcc_id"] or ev["signal_type"] != s["signal_type"]
                or (d - ev["first_date"]).days > WINDOW_DAYS):
            ev = _new_event(s, d)
            events.append(ev)
        ev["signals"].append(s)
        ev["last_date"] = max(ev["last_date"], d)

    return [_summarise(ev) for ev in events]


def _summarise(ev: dict) -> dict:
    sigs = ev["signals"]
    best = max(sigs, key=lambda s: (s["strength"], -date.fromisoformat(s["signal_date"]).toordinal()))
    cities = Counter(s["city"] for s in sigs if s["city"])
    headcounts = [s["headcount"] for s in sigs if s["headcount"]]

    sources, seen = [], set()
    for s in sorted(sigs, key=lambda s: s["signal_date"]):
        if s["url"] in seen:
            continue
        seen.add(s["url"])
        sources.append({"url": s["url"], "publisher": s["publisher"], "title": s["title"],
                        "published_at": s["published_at"], "evidence": s["evidence"]})

    t = ev["signal_type"]
    return {
        "company": ev["company"],
        "gcc_id": ev["gcc_id"],
        "signal_type": t,
        "type_label": TYPE_LABELS[t],
        "direction": "shrinking" if t in SHRINKING else "growing",
        "city": cities.most_common(1)[0][0] if cities else None,
        "date": ev["first_date"],
        "strength": best["strength"],
        "summary": best["summary"],
        "headcount": max(headcounts) if headcounts else None,
        "next_action": NEXT_ACTION[t],
        "sources": sources,
    }
