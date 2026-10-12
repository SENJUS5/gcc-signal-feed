"""
manual_corrections.py: human review fixes to AI output, kept in code so every edit is
recorded with its reason. Safe to re-run: each fix checks the evidence first, so it only
touches the signal it was written for.

Run from the project root:  python scripts/manual_corrections.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.db import get_client   # noqa: E402

# (company, signal_type, evidence starts with, reason)
DELETE = [
    ("Billtrust", "office_lease", "The 40,000-square-foot facility",
     "Article describes office size, not a lease."),
]

# (company, signal_type, evidence starts with, new summary, reason)
REWRITE_SUMMARY = [
    ("ServiceNow", "layoff", "ServiceNow has cut several hundred jobs",
     "ServiceNow cut several hundred jobs globally; India teams reportedly among the first affected.",
     "AI summary said the cuts were 'in India'; the source says global cuts."),
    ("ServiceNow", "layoff", "Posts on social media claimed",
     "Unverified social media posts claim cuts could reach 3,000 globally, with India teams hit first.",
     "AI summary stated layoffs as fact; the source is a social media claim."),
    ("Visa", "layoff", "Visa has cut about 2,600 jobs globally",
     "Visa cut about 2,600 jobs globally; India's tech hubs reported among the most affected.",
     "AI summary implied a confirmed India impact; the source gives no India number."),
]


def _find(db, company: str, signal_type: str, evidence_start: str) -> list[dict]:
    rows = (db.table("signals").select("id,summary,evidence,gccs!inner(name)")
              .eq("gccs.name", company).eq("signal_type", signal_type).execute().data)
    return [r for r in rows if (r["evidence"] or "").startswith(evidence_start)]


def main() -> None:
    db = get_client(write=True)
    for company, stype, ev, reason in DELETE:
        for r in _find(db, company, stype, ev):
            db.table("signals").delete().eq("id", r["id"]).execute()
            print(f"deleted  #{r['id']} {company} {stype}: {reason}")

    for company, stype, ev, new, reason in REWRITE_SUMMARY:
        for r in _find(db, company, stype, ev):
            if r["summary"] != new:
                db.table("signals").update({"summary": new}).eq("id", r["id"]).execute()
                print(f"rewrote  #{r['id']} {company} {stype}\n   was: {r['summary']}\n   now: {new}")
    print("done")


if __name__ == "__main__":
    main()
