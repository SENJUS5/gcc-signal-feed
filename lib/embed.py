"""
embed.py: Voyage embeddings.

Adapted from multimodal-rag-project/ingest/core.py (embed_texts) and
ingest/retrieval.py (_embed_query). Same model and dimensions, so the
hybrid-search SQL from that project works unchanged later.
"""

import os
import time

import voyageai
from dotenv import load_dotenv

load_dotenv()

EMBED_MODEL = "voyage-3"      # 1024-dim, must match vector(1024) in the schema
MAX_BATCH_CHARS = 28000       # ~7k tokens per request: stays under the free-tier 10k tokens/min
RATE_LIMIT_WAIT = 21          # free tier without a card = 3 requests/min

_voyage: voyageai.Client | None = None


def _client() -> voyageai.Client:
    """Created on first use, so the key can come from .env or (on Streamlit Cloud) st.secrets."""
    global _voyage
    if _voyage is None:
        _voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    return _voyage


def _embed_with_retry(texts: list[str], input_type: str, attempts: int = 4,
                      wait: int = RATE_LIMIT_WAIT) -> list[list[float]]:
    for attempt in range(attempts):
        try:
            return _client().embed(texts, model=EMBED_MODEL, input_type=input_type).embeddings
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(wait * (attempt + 1))   # back off on rate limit / transient


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed corpus documents in small batches, pausing between batches for the free tier."""
    out: list[list[float]] = []
    batch: list[str] = []
    size = 0
    for t in texts:
        if batch and size + len(t) > MAX_BATCH_CHARS:
            out.extend(_embed_with_retry(batch, "document"))
            time.sleep(RATE_LIMIT_WAIT)
            batch, size = [], 0
        batch.append(t)
        size += len(t)
    if batch:
        out.extend(_embed_with_retry(batch, "document"))
    return out


def embed_query(q: str) -> list[float]:
    # input_type='query' (not 'document'): Voyage embeds queries asymmetrically, which helps recall.
    # A person is waiting (Ask box): one quick retry, not the long batch back-off.
    return _embed_with_retry([q], "query", attempts=2, wait=3)[0]
