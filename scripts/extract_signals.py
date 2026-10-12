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
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.db import get_client                                              # noqa: E402
from lib.prompts import EXTRACTION_PROMPT, SIGNAL_TYPES, STRENGTH_RUBRIC   # noqa: E402

# Free tier = ~20 requests/day PER MODEL. When one model's daily quota is used up,
# move to the next. Each signal records the model that produced it (extracted_by).
MODELS = [os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"), "gemini-3.5-flash", "gemini-3.5-flash-lite"]
PAUSE_BETWEEN_ARTICLES = 6        # seconds; keeps us well under free-tier requests/minute
RETRY_WAITS = [10, 30, 60]        # seconds to wait after a 429 / 5xx before trying again
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
def _normalise(text: str) -> str:
    """Lowercase, unify curly quotes/dashes/spaces so a faithful copy still matches."""
    text = text.lower()
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), (" ", " ")):
        text = text.replace(a, b)
    text = re.sub(r"\s+", " ", text)
    # Pages that put links on their own line leave "Corporation , has": drop space before punctuation.
    return re.sub(r" ([,.;:!?)])", r"\1", text).strip()


def evidence_found(evidence: str, article: str) -> bool:
    return len(evidence.split()) >= 3 and _normalise(evidence) in _normalise(article)


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
# Gemini call with retries for free-tier rate limits
# ---------------------------------------------------------------------------
class DailyQuotaUsedUp(Exception):
    pass


def _is_daily_quota(e: errors.APIError) -> bool:
    """A per-day limit says 'retry in 16h..'; a per-minute limit says 'retry in 30s'."""
    return e.code == 429 and re.search(r"retry in \d+h", str(e)) is not None


def _call_one_model(client: genai.Client, model: str, prompt: str) -> Extraction:
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=Extraction,
        temperature=0,
    )
    for attempt, wait in enumerate([0] + RETRY_WAITS):
        time.sleep(wait)
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=config)
            return resp.parsed if isinstance(resp.parsed, Extraction) \
                else Extraction.model_validate_json(resp.text)
        except errors.APIError as e:
            if _is_daily_quota(e):
                raise DailyQuotaUsedUp(model) from e
            retryable = e.code in (429, 500, 503)
            if not retryable or attempt == len(RETRY_WAITS):
                raise
            print(f"    {model} {e.code}, retrying in {RETRY_WAITS[attempt]}s")


def call_gemini(client: genai.Client, prompt: str) -> tuple[Extraction, str]:
    """Try the current model; on a used-up daily quota, drop it and use the next one."""
    while MODELS:
        try:
            return _call_one_model(client, MODELS[0], prompt), MODELS[0]
        except DailyQuotaUsedUp:
            print(f"    {MODELS[0]} daily quota used up, switching to next model")
            MODELS.pop(0)
    raise RuntimeError("all Gemini models have used up their daily free quota")


def process_article(db, client, art: dict) -> tuple[int, int]:
    company = art["gccs"]["name"]
    prompt = EXTRACTION_PROMPT.format(
        company=company, url=art["url"], published_at=art["published_at"] or "unknown",
        signal_types=SIGNAL_TYPES, rubric=STRENGTH_RUBRIC, content=art["content"],
    )
    result, model = call_gemini(client, prompt)

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
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    todo = (db.table("articles")
              .select("id,gcc_id,url,published_at,content,gccs(name)")
              .is_("processed_at", "null").order("id").execute().data)
    print(f"Models (in order): {', '.join(MODELS)}. Articles to process: {len(todo)}\n")

    kept_total = dropped_total = failed = 0
    for i, art in enumerate(todo, 1):
        name = art["gccs"]["name"]
        try:
            kept, dropped = process_article(db, client, art)
            kept_total += kept
            dropped_total += dropped
            print(f"[{i:2}/{len(todo)}] {name:30} kept {kept}, dropped {dropped}")
        except RuntimeError as e:          # every model's daily quota is gone: stop, retry tomorrow
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
