"""
collect_news.py: Step 2. Load companies and news articles into Supabase.

  1. Upsert every company in data/gccs.csv into the gccs table.
  2. For every URL in data/article_urls.csv:
       - skip it if that URL is already in the articles table
       - fetch + clean it (lib/fetch.py)
       - skip it if it's older than the window, or the same text is already stored
       - insert it into articles
  3. Write data/fetch_log.csv (one line per URL: saved / skipped / failed + why).

Safe to re-run: it only fetches URLs it hasn't saved yet.
Run from the project root:  python scripts/collect_news.py
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.db import get_client          # noqa: E402
from lib.fetch import load_article     # noqa: E402

DATA = ROOT / "data"
WINDOW_START = "2026-07-01"            # anything published before this is out of scope


def read_csv(name: str) -> list[dict]:
    with open(DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def upsert_gccs(db) -> dict[str, int]:
    rows = []
    for r in read_csv("gccs.csv"):
        rows.append({
            "name": r["name"],
            "parent_company": r["parent_company"] or None,
            "hq_country": r["hq_country"] or None,
            "industry": r["industry"] or None,
            "india_cities": [c.strip() for c in r["india_cities"].split(";") if c.strip()],
            "website": r["website"] or None,
            "is_verified_gcc": r["is_verified_gcc"].strip().lower() == "true",
            "verified_source": r["verified_source"] or None,
        })
    db.table("gccs").upsert(rows, on_conflict="name").execute()
    saved = db.table("gccs").select("id,name").execute().data
    return {g["name"]: g["id"] for g in saved}


def main() -> None:
    db = get_client(write=True)

    gcc_ids = upsert_gccs(db)
    print(f"gccs: {len(gcc_ids)} companies in the table\n")

    existing = db.table("articles").select("url,content_hash").execute().data
    seen_urls = {a["url"] for a in existing}
    seen_hashes = {a["content_hash"] for a in existing}

    log = []
    for row in read_csv("article_urls.csv"):
        company, url = row["company"], row["url"]
        entry = {"company": company, "url": url, "status": "", "chars": "", "published_at": "", "note": ""}

        if company not in gcc_ids:
            entry.update(status="failed", note="company not in gccs.csv")
        elif url in seen_urls:
            entry.update(status="skipped", note="already saved")
        else:
            try:
                art = load_article(url)
                published = art.published_at or row["published_at"] or None
                entry.update(chars=len(art.content), published_at=published or "")

                if published and published < WINDOW_START:
                    entry.update(status="skipped", note=f"too old ({published})")
                elif art.content_hash in seen_hashes:
                    entry.update(status="skipped", note="same text already saved from another URL")
                else:
                    db.table("articles").insert({
                        "gcc_id": gcc_ids[company],
                        "url": url,
                        "title": art.title,
                        "publisher": row["publisher"] or None,
                        "published_at": published,
                        "content": art.content,
                        "content_hash": art.content_hash,
                    }).execute()
                    seen_urls.add(url)
                    seen_hashes.add(art.content_hash)
                    entry.update(status="saved")
            except Exception as e:      # network error, 403 block, paywall, bad HTML...
                entry.update(status="failed", note=str(e)[:150])

        log.append(entry)
        print(f"[{entry['status']:7}] {company:32} {entry['note'] or entry['chars']}")

    with open(DATA / "fetch_log.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(log[0].keys()))
        writer.writeheader()
        writer.writerows(log)

    counts = {s: sum(1 for e in log if e["status"] == s) for s in ("saved", "skipped", "failed")}
    print(f"\nDone. {counts}. Details in data/fetch_log.csv")


if __name__ == "__main__":
    main()
