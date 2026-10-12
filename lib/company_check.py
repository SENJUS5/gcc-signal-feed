"""
company_check.py: rules for the job seeker view (Company Check).

Deliberately shows LESS than the sales view: a direction in plain words, no strength
scores, no sales actions, no full feed. All rules here are fixed, no AI.
"""

from lib.events import headcount_text

# What our sources call the centre, for companies NOT verified as a GCC.
# Taken from the wording of the saved articles (see data/article_urls.csv).
SOURCE_WORDING = {
    "Kuehne+Nagel": "a tech centre",
    "DoorDash": "a talent hub / global technology hub",
    "Imagine Learning": "a new centre for AI and product work",
    "Mythic AI": "a centre of excellence",
    "Litmos": "a new office",
}

MEANING = {
    "Growing": "Actively expanding. Good time to ask about team growth and new roles.",
    "Shrinking": "Recent job cuts reported. Ask about team stability and role security in your interview.",
    "Mixed": "Both growth and cuts reported. Ask which teams are growing.",
    "No recent news": "We found no recent public news. Ask the recruiter about the team's plans.",
}


def direction(events: list[dict]) -> str:
    sides = {e["direction"] for e in events}
    if not sides:
        return "No recent news"
    if sides == {"growing"}:
        return "Growing"
    if sides == {"shrinking"}:
        return "Shrinking"
    return "Mixed"


def not_verified_note(company: str) -> str:
    wording = SOURCE_WORDING.get(company)
    if wording:
        return f"Our sources call it {wording}, not a GCC. It may still be the company's own centre: ask the recruiter."
    return "None of our sources describes it as a GCC. Ask the recruiter how the India team is set up."


def people_lines(events: list[dict]) -> list[str]:
    """Plain-language headcount lines, only where an article states a number."""
    lines = []
    grow = [e["headcount"] for e in events if e["headcount"] and e["direction"] == "growing"]
    cut = [e["headcount"] for e in events if e["headcount"] and e["direction"] == "shrinking"]
    if grow:
        lines.append(headcount_text(max(grow), "growing"))
    if cut:
        lines.append(headcount_text(max(cut), "shrinking"))
    return lines


def find_company(query: str, names: list[str]) -> str | None:
    """Match typed text to a tracked company name (case-insensitive, partial)."""
    q = (query or "").strip().lower()
    if not q:
        return None
    exact = [n for n in names if n.lower() == q]
    if exact:
        return exact[0]
    partial = [n for n in names if q in n.lower() or n.lower().split(" (")[0] in q]
    return partial[0] if len(partial) == 1 else None
