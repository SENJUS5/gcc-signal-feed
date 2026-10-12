"""
ask.py: the Ask box. Question in, short cited answer out, from our tracked articles only.

Flow:
  1. Embed the question with Voyage (input_type='query').
  2. Hybrid search (semantic + keyword, Reciprocal Rank Fusion) in Postgres -> top 5 articles.
  3. Send ONLY those 5 articles to Gemini; it must cite them as [1]..[5].
  4. Check in code, not trusted to the model:
       - drop any line that has no valid [n] citation
       - remove citation numbers that don't exist
       - if nothing cited is left -> "Not found in our tracked news"
"""

import re

from pydantic import BaseModel

from lib import gemini
from lib.embed import embed_query

TOP_K = 5
MAX_ARTICLE_CHARS = 3500      # per article sent to Gemini: keeps the prompt small for the free tier
NOT_FOUND = "Not found in our tracked news."

ASK_PROMPT = """\
You answer questions about Global Capability Centres (GCCs) in India, using ONLY the
numbered news articles below. Our tracked news covers mid-July to early October 2026.

RULES:
- Use only facts stated in these articles. No outside knowledge, no guesses.
- End every sentence or bullet with the article number(s) it comes from, like [1] or [2][4].
- Keep it short: 2 to 5 sentences, or a short bullet list (one company per bullet).
- Name the companies. Mention cities and numbers only if the article states them.
- If the articles do not answer the question, set found to false and leave answer empty.

QUESTION: {question}

ARTICLES:
{articles}
"""


class Answer(BaseModel):
    found: bool
    answer: str


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


def check_citations(answer: str, n_articles: int) -> tuple[str, list[int]]:
    """Keep only lines with a valid citation; strip citations to articles that don't exist."""
    kept, cited = [], set()
    for line in answer.strip().splitlines():
        if not line.strip():
            continue
        nums = [int(x) for x in re.findall(r"\[(\d+)\]", line)]
        valid = [x for x in nums if 1 <= x <= n_articles]
        line = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_articles else "", line)
        if valid or line.rstrip().endswith(":"):    # a short lead-in line ("Companies hiring:") is fine
            kept.append(line.rstrip())
            cited.update(valid)
    if not cited:
        return "", []
    while kept and kept[-1].endswith(":"):          # a lead-in with nothing after it
        kept.pop()
    return "\n".join(kept), sorted(cited)


def ask(db, question: str) -> dict:
    """Returns {found, answer, cited, sources, model}. Raises gemini.AllModelsExhausted."""
    articles = search(db, question)
    sources = [{k: a[k] for k in ("n", "url", "title", "publisher", "published_at")} for a in articles]
    if not articles:
        return {"found": False, "answer": NOT_FOUND, "cited": [], "sources": [], "model": None}

    prompt = ASK_PROMPT.format(question=question, articles=_format_articles(articles))
    resp, model = gemini.generate(prompt, schema=Answer, waits=[], timeout_s=20)
    result = resp.parsed if isinstance(resp.parsed, Answer) else Answer.model_validate_json(resp.text)

    text, cited = check_citations(result.answer, len(articles)) if result.found else ("", [])
    if not cited:
        return {"found": False, "answer": NOT_FOUND, "cited": [], "sources": sources, "model": model}
    return {"found": True, "answer": text, "cited": cited, "sources": sources, "model": model}
