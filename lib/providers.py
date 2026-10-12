"""
providers.py: which service providers are named as setup or hiring partners for GCCs.

Rule-based, no AI. A provider counts for a company only when ONE sentence of an article
  1. names the provider,
  2. names a GCC company from our list (and the provider isn't that company itself), and
  3. contains a partnership word ("in collaboration with", "engaged", "working with", "MoU"...).
So "Cambium fired KPMG as its accounting firm" doesn't count, and neither does
"according to CBRE data". The exact sentence is kept as evidence.
"""

import re

# Name in our list -> (pattern to find it, what kind of provider it is)
PROVIDERS = {
    "ANSR": (r"\bANSR\b", "GCC setup partner"),
    "HCLTech": (r"\bHCL ?Tech(nologies)?\b", "IT services / build-operate"),
    "Accenture": (r"\bAccenture\b", "Consulting / IT services"),
    "TeamLease": (r"\bTeamLease\b", "Staffing"),
    "Deloitte": (r"\bDeloitte\b", "Consulting"),
    "EY": (r"\bEY\b|\bErnst & Young\b", "Consulting"),
    "KPMG": (r"\bKPMG\b", "Consulting"),
    "PwC": (r"\bPwC\b|\bPricewaterhouseCoopers\b", "Consulting"),
    "CBRE": (r"\bCBRE\b", "Real estate"),
    "JLL": (r"\bJLL\b", "Real estate"),
    "Colliers": (r"\bColliers\b", "Real estate"),
    "Cushman & Wakefield": (r"\bCushman (&|and) Wakefield\b", "Real estate"),
    "Xpheno": (r"\bXpheno\b", "Staffing"),
    "Inductus": (r"\bInductus\b", "GCC setup partner"),
    "Guidance Tamil Nadu": (r"\bGuidance Tamil Nadu\b", "State investment agency"),
}

PARTNER_WORDS = re.compile(
    r"collaborat|partner|engag|working with|work with|works with|support from|supported by|"
    r"powered by|advis|in association|\bMoU\b|memorandum|tie-up|helped|help (establish|build|set up|scale)",
    re.I,
)

# Don't end a sentence after these: "Abercrombie & Fitch Co. has engaged ANSR", "Thiru C. Joseph Vijay".
_ABBREV = (r"(?<!\bCo\.)(?<!\bInc\.)(?<!\bLtd\.)(?<!\bCorp\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)"
           r"(?<!\bSt\.)(?<!\bvs\.)(?<!\b[A-Z]\.)")
_SPLIT = re.compile(_ABBREV + r"(?<=[.!?])\s+|(?<=[.!?][\"\u201d\u2019])\s+")   # also after a closing quote


def sentences(text: str) -> list[str]:
    return [" ".join(s.split()) for s in _SPLIT.split(text or "") if s.strip()]


def _company_key(name: str) -> str:
    """'Danaher (DHR Holding India)' -> 'danaher', 'Abercrombie & Fitch' -> 'abercrombie'"""
    return name.split("(")[0].split()[0].lower()


def _strength(sentence: str) -> int:
    """Prefer the clearest proof: an explicit link beats a vague 'partnership' mention."""
    strong = re.search(r"collaboration with|engaged|working with|MoU|memorandum|powered by", sentence, re.I)
    return (2 if strong else 1, -len(sentence))


def find_providers(articles: list[dict], companies: dict[int, str]) -> list[dict]:
    """articles: dicts with gcc_id, url, title, publisher, published_at, content.
    companies: {gcc_id: name}. Returns one entry per provider, most companies first."""
    found: dict[str, dict] = {}            # provider -> {company -> best evidence}
    for a in articles:
        company = companies.get(a["gcc_id"])
        if not company:
            continue
        key = _company_key(company)
        for sent in sentences(f"{a['title'] or ''}. {a['content']}"):
            low = sent.lower()
            if key not in low or not PARTNER_WORDS.search(sent):
                continue
            for name, (pattern, _) in PROVIDERS.items():
                if _company_key(name) == key or not re.search(pattern, sent):
                    continue                  # e.g. JLL's own GCC is not JLL acting as a partner
                pair = found.setdefault(name, {})
                best = pair.get(company)
                src = {"url": a["url"], "publisher": a["publisher"], "published_at": a["published_at"]}
                if best is None:
                    pair[company] = {"company": company, "evidence": sent, "source": src, "sources": [src]}
                else:
                    if src["url"] not in {s["url"] for s in best["sources"]}:
                        best["sources"].append(src)
                    if _strength(sent) > _strength(best["evidence"]):
                        best.update(evidence=sent, source=src)

    out = [{"provider": name, "kind": PROVIDERS[name][1], "links": sorted(pairs.values(), key=lambda x: x["company"])}
           for name, pairs in found.items()]
    return sorted(out, key=lambda p: (-len(p["links"]), p["provider"]))
