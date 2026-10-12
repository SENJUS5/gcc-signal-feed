"""
rescore.py: apply rule-based caps to signal strength so scores follow the rubric.

The AI sometimes scores too generously (especially the lite model). These rules only
LOWER a score, never raise it, so running this twice changes nothing the second time.
Every change is written to data/rescore_log.csv, so the original AI score is kept.

Caps (the lowest matching cap wins):
  1. layoff with headcount under 500, or no headcount            -> max 4
  2. layoff/closure where the number isn't company-confirmed     -> max 3
     (evidence says "sources", "people familiar", "reported", ...)
  3. evidence mentions social media posts or unverified claims   -> max 2
  4. office_lease or expansion with no headcount                 -> max 4

Run from the project root:  python scripts/rescore.py
"""

import csv
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.db import get_client   # noqa: E402

LOG = ROOT / "data" / "rescore_log.csv"

NOT_CONFIRMED = re.compile(r"\bsources?\b|people familiar|\breported\b|social media|\bclaimed\b", re.I)
UNVERIFIED = re.compile(r"social media|\bunverified\b|\bclaim(s|ed)?\b|\brumou?rs?\b|reddit", re.I)


def cap_for(s: dict) -> tuple[int, list[str]]:
    """Return the cap for one signal and the names of the rules that applied."""
    caps = []
    t, hc, ev = s["signal_type"], s["headcount"], s["evidence"] or ""
    if t == "layoff" and (hc is None or hc < 500):
        caps.append((4, "layoff under 500 / no headcount"))
    if t in ("layoff", "closure") and NOT_CONFIRMED.search(ev):
        caps.append((3, "India number not company-confirmed"))
    if UNVERIFIED.search(ev):
        caps.append((2, "social media / unverified claim"))
    if t in ("office_lease", "expansion") and hc is None:
        caps.append((4, "lease/expansion without headcount"))
    if not caps:
        return 5, []
    lowest = min(c for c, _ in caps)
    return lowest, [name for c, name in caps if c == lowest]


def main() -> None:
    db = get_client(write=True)
    signals = (db.table("signals")
                 .select("id,signal_type,strength,headcount,evidence,gccs(name)")
                 .execute().data)
    before = Counter(s["strength"] for s in signals)

    changes = []
    for s in signals:
        cap, rules = cap_for(s)
        if s["strength"] > cap:
            db.table("signals").update({"strength": cap}).eq("id", s["id"]).execute()
            changes.append({"signal_id": s["id"], "company": s["gccs"]["name"],
                            "signal_type": s["signal_type"], "old": s["strength"], "new": cap,
                            "rule": "; ".join(rules)})
            s["strength"] = cap
    after = Counter(s["strength"] for s in signals)

    if changes:
        new_file = not LOG.exists()
        with open(LOG, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(changes[0].keys()))
            if new_file:
                w.writeheader()
            w.writerows(changes)

    print("strength  before  after")
    for k in range(5, 0, -1):
        print(f"   {k}       {before.get(k, 0):>3}    {after.get(k, 0):>3}")
    print(f"\n{len(changes)} signals lowered:")
    for c in changes:
        print(f"  {c['company']:28} {c['signal_type']:12} {c['old']} -> {c['new']}  ({c['rule']})")


if __name__ == "__main__":
    main()
