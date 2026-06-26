"""Request pacing & anti-throttle helpers.

Douyin's risk control reacts to two things: how fast you call, and how
*regular* the cadence looks. When it kicks in, the search endpoints usually
still return HTTP 200 — but with `status_code == 0` and an **empty `data`
array** (or a non-zero `status_code`). A naive scraper reads that empty page as
"no more results" and stops early, silently truncating the crawl.

This module centralizes the mitigation so every entry point behaves the same:

- **Jittered delays** — randomize each wait around the base `REQUEST_DELAY` so
  requests don't fire on a robotic fixed beat.
- **Exponential backoff** — growing waits between retries (transport errors and
  soft "blocked" responses alike).
- **Empty/blocked retry** (`fetch_json`) — treat an unexpectedly empty payload
  as a throttle signal and retry the same request a few times with backoff
  before concluding the results are genuinely exhausted.

All timing knobs come from `config.settings` (env-overridable).
"""
import asyncio
import random

from config.settings import (
    REQUEST_DELAY,
    REQUEST_JITTER,
    BACKOFF_FACTOR,
    BACKOFF_MAX,
    EMPTY_RETRY,
)


def jittered_delay(base: float = None) -> float:
    """Return ``base`` seconds perturbed by ±``REQUEST_JITTER`` (never < 0)."""
    base = REQUEST_DELAY if base is None else base
    spread = base * REQUEST_JITTER
    return max(0.0, base + random.uniform(-spread, spread))


async def polite_sleep(base: float = None) -> None:
    """Sleep for a jittered base delay between successive requests."""
    await asyncio.sleep(jittered_delay(base))


def backoff_delay(attempt: int, base: float = None) -> float:
    """Exponential backoff for retry ``attempt`` (1-based), with upward jitter.

    delay = min(base * FACTOR**(attempt-1), BACKOFF_MAX) + random[0, 0.5*base]
    """
    base = REQUEST_DELAY if base is None else base
    raw = min(base * (BACKOFF_FACTOR ** max(0, attempt - 1)), BACKOFF_MAX)
    return raw + random.uniform(0, base * 0.5)


def _has_payload(data: dict, item_keys) -> bool:
    if not isinstance(data, dict):
        return False
    for k in item_keys:
        v = data.get(k)
        if v:
            return True
    return False


async def fetch_json(client, url, params=None, *, item_keys=("data",),
                     empty_retries: int = None, label: str = "") -> dict:
    """GET JSON via ``client``, retrying empty/blocked responses with backoff.

    A response counts as "good" when ``status_code == 0`` AND at least one of
    ``item_keys`` holds a truthy value. Anything else (non-zero status, or an
    empty payload) is treated as a soft throttle signal: we back off and retry
    up to ``empty_retries`` times, then return the last response so the caller's
    own end-of-results handling still applies.

    ``client`` must expose ``async get(url, params=...) -> dict`` (DouyinClient),
    which already applies its own jittered base delay before each call.
    """
    empty_retries = EMPTY_RETRY if empty_retries is None else empty_retries
    last = {}
    for attempt in range(empty_retries + 1):
        data = await client.get(url, params=params)
        last = data or {}
        if last.get("status_code") == 0 and _has_payload(last, item_keys):
            return last
        # Soft failure — likely rate limiting. Back off unless out of retries.
        if attempt < empty_retries:
            delay = backoff_delay(attempt + 1)
            sc = last.get("status_code")
            tag = f"{label} " if label else ""
            print(f"  [throttle?] {tag}empty/blocked (status={sc}); "
                  f"backoff {delay:.1f}s, retry {attempt + 1}/{empty_retries}")
            await asyncio.sleep(delay)
    return last
