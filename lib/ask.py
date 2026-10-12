"""
ask.py: the Ask box. Question in, short cited answer out, from our tracked articles only.

Flow:
  1. Embed the question with Voyage (input_type='query').
  2. Hybrid search (semantic + keyword, Reciprocal Rank Fusion) in Postgres -> top 5 articles.
  3. Send ONLY those 5 articles to Gemini. It answers as a list of short statements; each
     statement cites article numbers AND copies an exact quote that proves it.
  4. Check every statement in code, not trusted to the model:
       - citations must point to articles we actually sent
       - the quote must appear word-for-word in a cited article
       - the statement must name the company that article is about
       - every city and number in the statement must appear in the quote's sentence
         (stops "has an office in Bengaluru" turning into "cut jobs in Bengaluru")
       - statements about the same company are merged
     Statements that fail are dropped. Nothing left -> "Not found in our tracked news."
"""

import re

from pydantic import BaseModel

from lib import gemini
from lib.embed import embed_query
from lib.events import CITY_NAMES
from lib.textcheck import numbers_in, sentence_around

TOP_K = 5
MAX_ARTICLE_CHARS = 3500      # per article sent to Gemini: keeps the prompt small for the free tier
NOT_FOUND = "Not found in our tracked news."
_CITY_RE = re.compile(r"\b(" + "|".join(CITY_NAMES) + r")\b", re.I)

ASK_PROMPT = """\
You answer questions about Global Capability Centres (GCCs) in India, using ONLY the
numbered news articles below. Our tracked news covers mid-July to early October 2026.

Answer as a short list of statements (1 to 5), one company per statement.

RULES:
- Use only facts stated in these articles. No outside knowledge, no guesses.
- Do not add any city, number or detail about a company unless the cited article states it
  for that company. If an article says "India teams", say "India teams", not a specific city.
- A company having an office in a city does NOT mean an event happened there. Only link an
  event (hiring, layoffs, opening) to a city if the article says that event happened in that city.
- For each statement give:
    text:      one plain sentence. Do not put [1]-style numbers in it.
    citations: the article number(s) it comes from, e.g. [2] or [2, 4]
    quote:     a short phrase (5 to 40 words) COPIED EXACTLY from the first cited article
               that proves the statement. The quote must contain every city and every
               number that the statement mentions.
- If the articles do not answer the question, set found to false and return no statements.

QUESTION: {question}

ARTICLES:
{articles}
"""


class Point(BaseModel):
    text: str
    citations: list[int]
    quote: str


class Answer(BaseModel):
    found: bool
    points: list[Point]


def search(db, question: str, k: int = TOP_K) -> list[dict]:
    rows = db.rpc("article_hybrid_search", {
        "query_text": question,
        "query_embedding": embed_query(question),
        "match_count": k,
    }).execute().data
    return [{**r, "n": i} for i, r in enumerate(rows, 1)]


def _format_articles(articles: list[dict]) -> str:
    parts = []
    for a in articles:
        head = f"[{a['n']}] {a['title']} ({a['publisher'] or 'unknown'}, {a['published_at'] or 'date unknown'})"
        parts.append(f"{head}\n{a['content'][:MAX_ARTICLE_CHARS]}")
    return "\n\n".join(parts)


def _cities(text: str) -> set[str]:
    return {CITY_NAMES[m.lower()] for m in _CITY_RE.findall(text)}


def _company_key(name: str) -> str:
    """'Danaher (DHR Holding India)' -> 'danaher', 'JLL Business Services' -> 'jll'"""
    return name.split("(")[0].split()[0].lower()


def check_points(points: list[Point], articles: dict[int, dict]) -> tuple[list[dict], list[dict]]:
    """articles: {number: {"content", "company"}}. Returns (kept, dropped with a reason).

    A statement is kept only if its quote is really in a cited article, it names that
    article's company, and every city and number it states appears in the quote's sentence.
    Statements about the same company are merged into one line.
    """
    kept: dict[str, dict] = {}
    dropped = []
    for p in points:
        text = re.sub(r"\s*\[\d+\]", "", p.text).strip()        # code adds the [n] markers itself
        cites = sorted({c for c in p.citations if c in articles})
        sentence = next((s for c in cites if (s := sentence_around(p.quote, articles[c]["content"]))), None)
        company = next((articles[c]["company"] for c in cites
                        if _company_key(articles[c]["company"]) in text.lower()), None)
        missing_cities = _cities(text) - _cities(sentence or "")
        missing_numbers = numbers_in(text) - numbers_in(sentence or "")

        if not cites:
            reason = "no valid citation"
        elif not sentence or len(p.quote.split()) < 3:
            reason = "quote not found in the cited article"
        elif not company:
            reason = "doesn't name the company its source is about"
        elif missing_cities:
            reason = f"city not stated in the source sentence ({', '.join(sorted(missing_cities))})"
        elif missing_numbers:
            reason = f"number not stated in the source sentence ({', '.join(sorted(missing_numbers))})"
        else:
            reason = None
        if reason:
            dropped.append({"text": text, "reason": reason})
        elif company in kept:                                     # same company again: add its sources
            kept[company]["citations"] = sorted(set(kept[company]["citations"]) | set(cites))
        else:
            # Restore the company's own spelling ("Jll" -> "JLL", "Doordash" -> "DoorDash").
            proper = company.split("(")[0].split()[0]
            text = re.sub(rf"\b{re.escape(_company_key(company))}\b", proper, text, flags=re.I)
            kept[company] = {"text": text, "citations": cites, "quote": p.quote}
    return list(kept.values()), dropped


def ask(db, question: str) -> dict:
    """Returns {found, points, cited, dropped, sources, model}. Raises gemini.GeminiUnavailable."""
    articles = search(db, question)
    sources = [{k: a[k] for k in ("n", "url", "title", "publisher", "published_at")} for a in articles]
    not_found = {"found": False, "points": [], "cited": [], "dropped": [], "sources": sources, "model": None}
    if not articles:
        return not_found

    prompt = ASK_PROMPT.format(question=question, articles=_format_articles(articles))
    resp, model = gemini.generate(prompt, schema=Answer, waits=[], timeout_s=20)
    result = resp.parsed if isinstance(resp.parsed, Answer) else Answer.model_validate_json(resp.text)

    names = {g["id"]: g["name"] for g in db.table("gccs").select("id,name").execute().data}
    # Headline + body: Gemini sees both, so a quote from the headline is a real quote too.
    by_number = {a["n"]: {"content": f"{a['title'] or ''}. {a['content']}", "company": names.get(a["gcc_id"], "")}
                 for a in articles}
    kept, dropped = check_points(result.points, by_number) if result.found else ([], [])
    if not kept:
        return {**not_found, "dropped": dropped, "model": model}
    cited = sorted({c for p in kept for c in p["citations"]})
    return {"found": True, "points": kept, "cited": cited, "dropped": dropped, "sources": sources, "model": model}

