"""
extract_signals.py: Step 3. Turn each saved article into structured signals with Gemini.

For every article where processed_at is null:
  1. Send it to Gemini with a fixed JSON schema (lib/prompts.py has the prompt + strength rubric).
  2. Check every signal in code:
       - evidence must appear word-for-word in the article text, else the signal is DROPPED
       - headcount must appear as a number in the article text, else it is set to null
       - city names are standardised (Bangalore -> Bengaluru, ...)
  3. Save the surviving signals; set processed_at (or extract_error if Gemini failed).
  4. If the article had no date in its page metadata, store the date Gemini read from the text.

Dropped signals and cleared headcounts are logged to data/dropped_signals.csv.
Safe to re-run: processed articles are skipped; failed ones are retried.
Run from the project root:  python scripts/extract_signals.py
"""

import csv
import re
import sys
import time
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib import gemini                                                     # noqa: E402
from lib.db import get_client                                              # noqa: E402
from lib.textcheck import evidence_found                                    # noqa: E402
from lib.prompts import EXTRACTION_PROMPT, SIGNAL_TYPES, STRENGTH_RUBRIC   # noqa: E402

# Free tier = ~20 requests/day PER MODEL: lib/gemini.py moves to the next model when one
# runs out. Each signal records the model that produced it (extracted_by).
PAUSE_BETWEEN_ARTICLES = 6        # seconds; keeps us well under free-tier requests/minute
DROP_LOG = ROOT / "data" / "dropped_signals.csv"
EARLIEST_SIGNAL_DATE = "2026-06-01"   # a bit before the article window: articles can report slightly older events

CITY_ALIASES = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru",
    "gurgaon": "Gurugram", "gurugram": "Gurugram",
    "bombay": "Mumbai", "madras": "Chennai",
    "new delhi": "Delhi", "delhi ncr": "Delhi NCR",
}


# ---------------------------------------------------------------------------
# The JSON shape Gemini must return. Enum = only the 6 allowed types can come back.
# ---------------------------------------------------------------------------
class SignalType(str, Enum):
    new_centre = "new_centre"
    expansion = "expansion"
    hiring_push = "hiring_push"
    office_lease = "office_lease"
    layoff = "layoff"
    closure = "closure"


class Signal(BaseModel):
    signal_type: SignalType
    city: Optional[str]
    signal_date: str
    summary: str
    strength: int = Field(ge=1, le=5)
    headcount: Optional[int]
    evidence: str


class Extraction(BaseModel):
    article_date: Optional[str]
    signals: list[Signal]


# ---------------------------------------------------------------------------
# Checks done in code, not trusted to the model
# ---------------------------------------------------------------------------
def headcount_found(n: int, article: str) -> bool:
    """True if the number appears in the text as 3000, 3,000 or 3 000."""
    digits = re.sub(r"[,\s]", "", article)
    return f"{n:,}" in article or str(n) in digits


def clean_city(city: Optional[str]) -> Optional[str]:
    if not city:
        return None
    return CITY_ALIASES.get(city.strip().lower(), city.strip())


def valid_date(s: Optional[str]) -> Optional[str]:
    try:
        return date.fromisoformat(s).isoformat() if s else None
    except ValueError:
        return None


def log_drop(row: dict) -> None:
    new_file = not DROP_LOG.exists()
    with open(DROP_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["article_id", "company", "signal_type", "reason", "evidence"])
        if new_file:
            w.writeheader()
        w.writerow(row)


# ---------------------------------------------------------------------------
# Gemini call: model fallback + retries live in lib/gemini.py (shared with the Ask box)
# ---------------------------------------------------------------------------
def call_gemini(prompt: str) -> tuple[Extraction, str]:
    resp, model = gemini.generate(prompt, schema=Extraction)
    parsed = resp.parsed if isinstance(resp.parsed, Extraction) else Extraction.model_validate_json(resp.text)
    return parsed, model


def process_article(db, art: dict) -> tuple[int, int]:
    company = art["gccs"]["name"]
    prompt = EXTRACTION_PROMPT.format(
        company=company, url=art["url"], published_at=art["published_at"] or "unknown",
        signal_types=SIGNAL_TYPES, rubric=STRENGTH_RUBRIC, content=art["content"],
    )
    result, model = call_gemini(prompt)

    # Point 5: no metadata date -> use the date Gemini read from the text.
    published = art["published_at"] or valid_date(result.article_date)
    update = {"processed_at": datetime.now(timezone.utc).isoformat(), "extract_error": None}
    if not art["published_at"] and published:
        update["published_at"] = published

    rows, dropped, seen_types = [], 0, set()
    for s in result.signals:
        base = {"article_id": art["id"], "company": company, "signal_type": s.signal_type.value}
        if s.signal_type in seen_types:
            continue                                   # one signal per type per article
        if not evidence_found(s.evidence, art["content"]):
            log_drop({**base, "reason": "evidence not in article", "evidence": s.evidence})
            dropped += 1
            continue
        headcount = s.headcount
        if headcount is not None and not headcount_found(headcount, art["content"]):
            log_drop({**base, "reason": f"headcount {headcount} not in article (set to null)",
                      "evidence": s.evidence})
            headcount = None
        # Dates outside a sane range are model guesses (e.g. "2026-01-01"): use the article date instead.
        signal_date = valid_date(s.signal_date)
        if signal_date and not (EARLIEST_SIGNAL_DATE <= signal_date <= date.today().isoformat()):
            log_drop({**base, "reason": f"signal_date {signal_date} out of range (replaced by article date)",
                      "evidence": s.evidence})
            signal_date = None
        signal_date = signal_date or published
        if not signal_date:
            log_drop({**base, "reason": "no reliable date in article or metadata", "evidence": s.evidence})
            dropped += 1
            continue
        seen_types.add(s.signal_type)
        rows.append({
            "gcc_id": art["gcc_id"],
            "article_id": art["id"],
            "signal_type": s.signal_type.value,
            "city": clean_city(s.city),
            "signal_date": signal_date,
            "summary": s.summary.strip(),
            "strength": s.strength,
            "headcount": headcount,
            "evidence": s.evidence.strip(),
            "extracted_by": model,
        })

    if rows:
        db.table("signals").upsert(
            rows, on_conflict="article_id,gcc_id,signal_type", ignore_duplicates=True
        ).execute()
    db.table("articles").update(update).eq("id", art["id"]).execute()
    return len(rows), dropped


def main() -> None:
    db = get_client(write=True)

    todo = (db.table("articles")
              .select("id,gcc_id,url,published_at,content,gccs(name)")
              .is_("processed_at", "null").order("id").execute().data)
    print(f"Models (in order): {', '.join(gemini.models())}. Articles to process: {len(todo)}\n")

    kept_total = dropped_total = failed = 0
    for i, art in enumerate(todo, 1):
        name = art["gccs"]["name"]
        try:
            kept, dropped = process_article(db, art)
            kept_total += kept
            dropped_total += dropped
            print(f"[{i:2}/{len(todo)}] {name:30} kept {kept}, dropped {dropped}")
        except gemini.AllModelsExhausted as e:   # every model's daily quota is gone: stop, retry tomorrow
            print(f"\nStopping: {e}. {len(todo) - i + 1} articles left for the next run.")
            break
        except Exception as e:
            failed += 1
            db.table("articles").update({"extract_error": str(e)[:500]}).eq("id", art["id"]).execute()
            print(f"[{i:2}/{len(todo)}] {name:30} FAILED: {str(e)[:120]}")
        if i < len(todo):
            time.sleep(PAUSE_BETWEEN_ARTICLES)

    print(f"\nDone. Signals kept: {kept_total}, dropped by evidence check: {dropped_total}, "
          f"articles failed: {failed}")


if __name__ == "__main__":
    main()
