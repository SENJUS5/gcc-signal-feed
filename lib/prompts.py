"""
prompts.py: the signal-extraction prompt, kept apart from the code so it's easy to read and tune.
"""

STRENGTH_RUBRIC = """\
5 = company-confirmed, big move: a new centre opening, a closure, or 500+ jobs
4 = company-confirmed, medium move: an expansion, a new office or lease, a hiring plan under 500, layoffs under 500
3 = credible news report (not confirmed by the company), and the India impact is clear
2 = single secondary source, OR global news where the India impact is unclear
1 = rumour or unverified claim (e.g. anonymous social media posts, "sources say")

"Company-confirmed" means: a company press release, a named company spokesperson or executive
quoted, an official company statement, or an inauguration by a government minister."""

SIGNAL_TYPES = """\
new_centre   = the company opens (or signs to open) its first centre in a city
expansion    = an existing centre grows: new floor/campus/office, new functions, more scope
hiring_push  = a stated plan to hire or grow headcount
office_lease = a signed office lease or property deal
layoff       = job cuts that affect India staff
closure      = an India centre is shut down"""

EXTRACTION_PROMPT = """\
You read news about Global Capability Centres (GCCs) in India and extract structured signals.

COMPANY: {company}
ARTICLE URL: {url}
ARTICLE PUBLISHED DATE (from page metadata): {published_at}

Extract every distinct signal about {company}'s operations IN INDIA from the article below.
Ignore other companies mentioned in the article. Return an empty list if there is no such signal.
One article can hold several signals (e.g. a new centre AND a hiring plan), but give at most
one signal per signal_type.

SIGNAL TYPES (use only these exact values):
{signal_types}

FIELDS for each signal:
- signal_type: one of the values above
- city: the Indian city, or null if the article names none. If several cities, pick the main one.
- signal_date: YYYY-MM-DD. The date the event happened or was announced, if the text says so.
  Otherwise use the article's published date.
- summary: one plain, factual line, max 20 words. No hype words.
- strength: integer 1 to 5, using this rubric:
{rubric}
- headcount: an integer ONLY if the article states a number of people/jobs for this signal
  (e.g. "plans to hire 3,000" -> 3000). Otherwise null. Never estimate.
- evidence: a short phrase (5 to 30 words) COPIED EXACTLY, character for character, from the
  article text, that proves this signal. Do not paraphrase, fix typos, or join separate sentences.

ALSO RETURN:
- article_date: the article's publish date as YYYY-MM-DD, read from the article text
  (e.g. a dateline like "Pune, October 9:"). null if the text does not state it.

ARTICLE TEXT:
\"\"\"
{content}
\"\"\"
"""
