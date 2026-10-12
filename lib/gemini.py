"""
gemini.py: one Gemini call with free-tier safety, shared by extraction and the Ask box.

Free tier = ~20 requests/day PER MODEL. When a model's daily quota is used up, the
next model in the chain is used, and the used-up one is skipped for an hour (so a
long-running website tries it again later instead of forgetting it forever).
"Busy" errors (503, per-minute 429) and timeouts are retried with a short wait; if a
model is still busy after that, the next model is tried.

Callers choose the patience: extraction (offline) retries for up to ~2 minutes per model;
the Ask box (a person is waiting) gives each model one try with a hard timeout.
The SDK's own hidden retries are switched off, so the timeouts here are the real ones.
"""

import os
import re
import time

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv()

FALLBACK_MODELS = ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
RETRY_WAITS = [10, 30, 60]       # seconds to wait after a busy error before trying again
SKIP_SECONDS = 3600              # how long to skip a model whose daily quota is used up

_exhausted: dict[str, float] = {}   # model -> time its daily quota ran out
_client: genai.Client | None = None


class GeminiUnavailable(RuntimeError):
    """No model could answer right now (quota used up, or all busy)."""


class AllModelsExhausted(GeminiUnavailable):
    """Every model's daily free quota is used up."""


def models() -> list[str]:
    chain = [os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")] + FALLBACK_MODELS
    return list(dict.fromkeys(chain))          # keep order, drop duplicates


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _is_daily_quota(e: Exception) -> bool:
    """A per-day limit says 'retry in 16h..'; a per-minute limit says 'retry in 30s'."""
    return isinstance(e, errors.APIError) and e.code == 429 and re.search(r"retry in \d+h", str(e)) is not None


def _is_busy(e: Exception) -> bool:
    return isinstance(e, httpx.TimeoutException) or (
        isinstance(e, errors.APIError) and e.code in (429, 500, 503))


def _call_one(model: str, prompt: str, config: types.GenerateContentConfig, waits: list[int]):
    for attempt, wait in enumerate([0] + waits):
        time.sleep(wait)
        try:
            return _get_client().models.generate_content(model=model, contents=prompt, config=config)
        except Exception as e:
            if _is_daily_quota(e) or not _is_busy(e) or attempt == len(waits):
                raise
            print(f"    {model} busy ({getattr(e, 'code', 'timeout')}), retrying in {waits[attempt]}s")


def generate(prompt: str, schema=None, waits: list[int] = RETRY_WAITS, timeout_s: int = 120) -> tuple:
    """Returns (response, model_used). schema = a pydantic class for JSON output, or None."""
    config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json" if schema else None,
        response_schema=schema,
        http_options=types.HttpOptions(
            timeout=timeout_s * 1000,                                   # milliseconds
            retry_options=types.HttpRetryOptions(attempts=1),           # no hidden SDK retries
        ),
    )
    busy = False
    for model in models():
        if time.time() - _exhausted.get(model, 0) < SKIP_SECONDS:
            continue
        try:
            return _call_one(model, prompt, config, waits), model
        except Exception as e:
            if _is_daily_quota(e):
                _exhausted[model] = time.time()
                print(f"    {model} daily quota used up, switching to next model")
            elif _is_busy(e):
                busy = True
                print(f"    {model} still busy, switching to next model")
            else:
                raise
    if busy:
        raise GeminiUnavailable("all Gemini models are busy or out of quota right now")
    raise AllModelsExhausted("all Gemini models have used up their daily free quota")
