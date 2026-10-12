"""
fetch.py: download a news article and clean it to plain text.

Adapted from multimodal-rag-project/ingest/loaders/doc_loaders.py (load_link)
and ingest/core.py (sha256 content hash). Changes for news pages:
  * browser-like User-Agent (many news sites block unknown bots)
  * keep only the article body (<article> / <p> tags), not menus and sidebars
  * pull the publish date from page metadata when present
  * no chunking: one article = one row
"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
MIN_CHARS = 400        # less than this usually means a paywall, block page or empty shell
MAX_CHARS = 20000      # news articles are short; cap junk-heavy pages


@dataclass
class Article:
    url: str
    title: str
    content: str
    published_at: Optional[str]   # YYYY-MM-DD or None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def _to_iso(raw: str) -> Optional[str]:
    """Turn any date string ("2026-10-06T..", "Tue, 06 Oct 2026 ..") into YYYY-MM-DD."""
    try:
        return date_parser.parse(raw, fuzzy=True).date().isoformat()
    except (ValueError, OverflowError):
        return None


def _published_date(soup: BeautifulSoup) -> Optional[str]:
    """Look for the publish date in the usual meta tags and JSON-LD."""
    raw = _raw_published_date(soup)
    return _to_iso(raw) if raw else None


def _raw_published_date(soup: BeautifulSoup) -> Optional[str]:
    for attrs in (
        {"property": "article:published_time"},
        {"property": "og:published_time"},
        {"name": "publish-date"},
        {"name": "pubdate"},
        {"itemprop": "datePublished"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"]

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for item in items:
            if isinstance(item, dict) and item.get("datePublished"):
                return str(item["datePublished"])

    time_tag = soup.find("time", datetime=True)
    if time_tag:
        return time_tag["datetime"]
    return None


def _body_text(soup: BeautifulSoup) -> str:
    """Prefer the <article> block; fall back to all real paragraphs on the page."""
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()

    container = soup.find("article") or soup
    paras = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    paras = [p for p in paras if len(p) > 40]          # drop captions, bylines, buttons
    text = "\n\n".join(paras)

    if len(text) < MIN_CHARS:                           # odd markup: take all visible text
        text = re.sub(r"\n{3,}", "\n\n", container.get_text("\n")).strip()
    return text[:MAX_CHARS]


def load_article(url: str) -> Article:
    """Fetch and clean one article. Raises on network errors or too-short pages."""
    resp = requests.get(url, timeout=25, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    og_title = soup.find("meta", property="og:title")
    title = (og_title.get("content") if og_title else None) or (
        soup.title.string if soup.title else url
    )
    published = _published_date(soup)
    content = _body_text(soup)

    if len(content) < MIN_CHARS:
        raise ValueError(f"page text too short ({len(content)} chars): likely blocked or paywalled")

    return Article(url=url, title=title.strip(), content=content, published_at=published)
