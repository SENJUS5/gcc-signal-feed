"""
textcheck.py: "is this quote really in the article?" checks, shared by signal extraction
and the Ask box. The AI must copy an exact phrase; code confirms it, never the model.
"""

import re


def normalise(text: str) -> str:
    """Lowercase, unify curly quotes/dashes/spaces so a faithful copy still matches."""
    text = text.lower()
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), (" ", " ")):
        text = text.replace(a, b)
    text = re.sub(r"\s+", " ", text)
    # Pages that put links on their own line leave "Corporation , has": drop space before punctuation.
    return re.sub(r" ([,.;:!?)])", r"\1", text).strip()


def evidence_found(evidence: str, article: str) -> bool:
    return len(evidence.split()) >= 3 and normalise(evidence) in normalise(article)


def sentence_around(quote: str, article: str) -> str | None:
    """The full sentence(s) of the article that contain the quote (normalised), or None."""
    na, nq = normalise(article), normalise(quote)
    i = na.find(nq)
    if i < 0:
        return None
    prev = max(na.rfind(b, 0, i) for b in (". ", "? ", "! "))
    start = prev + 2 if prev >= 0 else 0
    ends = [j for j in (na.find(b, i + len(nq)) for b in (". ", "? ", "! ")) if j >= 0]
    return na[start:min(ends) + 1 if ends else len(na)]


def numbers_in(text: str) -> set[str]:
    """'1,600 people and 3,000 jobs' -> {'1600', '3000'}"""
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}
