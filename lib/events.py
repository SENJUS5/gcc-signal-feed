"""
events.py: group signals into events for the feed.

The same news is often reported by 2-3 articles, and one announcement often carries
several signal types (e.g. a new centre AND a hiring plan). Rule:
  same company + dates within 14 days of the event's FIRST date = one event (one card).
Measured from the first date, so a long chain of reports can't merge two separate
events a month apart.

An event shows: all its signal types as badges (most important first), the earliest
date, the highest strength, the summary of its most important signal, the largest
stated headcount, the next action of its most important type, and every distinct
source with its evidence quote.
"""

from collections import Counter
from datetime import date

WINDOW_DAYS = 14

# Most important first: decides badge order, the summary shown and the next action.
TYPE_PRIORITY = ["new_centre", "closure", "layoff", "hiring_push", "expansion", "office_lease"]

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


def group_events(signals: list[dict]) -> list[dict]:
    """signals: flat dicts with company, gcc_id, signal_type, signal_date, city, summary,
    strength, headcount, evidence, url, publisher, title, published_at."""
    ordered = sorted(signals, key=lambda s: (s["gcc_id"], s["signal_date"]))
    groups: list[dict] = []
    for s in ordered:
        d = date.fromisoformat(s["signal_date"])
        g = groups[-1] if groups else None
        if g is None or g["gcc_id"] != s["gcc_id"] or (d - g["first_date"]).days > WINDOW_DAYS:
            g = {"gcc_id": s["gcc_id"], "first_date": d, "signals": []}
            groups.append(g)
        g["signals"].append(s)
    return [_summarise(g) for g in groups]


def _summarise(g: dict) -> dict:
    sigs = g["signals"]
    types = sorted({s["signal_type"] for s in sigs}, key=TYPE_PRIORITY.index)
    main = types[0]
    direction = "shrinking" if main in SHRINKING else "growing"

    # Summary: strongest signal of the most important type (earliest wins a tie).
    main_sigs = [s for s in sigs if s["signal_type"] == main]
    best = max(main_sigs, key=lambda s: (s["strength"], -date.fromisoformat(s["signal_date"]).toordinal()))

    # Headcount: largest stated number on the same side (don't mix hires with layoffs).
    same_side = [s["headcount"] for s in sigs
                 if s["headcount"] and (s["signal_type"] in SHRINKING) == (direction == "shrinking")]
    cities = Counter(s["city"] for s in sigs if s["city"])

    sources, seen = [], set()
    for s in sorted(sigs, key=lambda s: (s["signal_date"], TYPE_PRIORITY.index(s["signal_type"]))):
        if s["url"] in seen:
            continue                       # one entry per article, with its first evidence quote
        seen.add(s["url"])
        sources.append({"url": s["url"], "publisher": s["publisher"], "title": s["title"],
                        "published_at": s["published_at"], "evidence": s["evidence"]})

    return {
        "company": sigs[0]["company"],
        "gcc_id": g["gcc_id"],
        "types": types,
        "main_type": main,
        "direction": direction,
        "city": cities.most_common(1)[0][0] if cities else None,
        "date": g["first_date"],
        "last_date": max(date.fromisoformat(s["signal_date"]) for s in sigs),
        "strength": max(s["strength"] for s in sigs),
        "summary": best["summary"],
        "headcount": max(same_side) if same_side else None,
        "next_action": NEXT_ACTION[main],
        "signal_count": len(sigs),
        "sources": sources,
    }
