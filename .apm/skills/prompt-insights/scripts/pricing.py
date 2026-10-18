"""List prices for the cost estimate.

Source: https://platform.claude.com/docs/en/about-claude/pricing (copied on PRICES_AS_OF).
These are Claude API list prices. They are NOT what the user pays: a Claude subscription, a negotiated
discount, a cloud provider's price list or free credits all change the real bill. Every cost figure the
skill shows is an estimate made from these numbers and the token counts in the transcripts.
Update the table (and PRICES_AS_OF) when the pricing page changes; --prices overrides it per run.
"""
from __future__ import annotations

import re

PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICES_AS_OF = "2026-10-18"
DISCLAIMER = ("Estimate only: token counts from your transcripts priced at Claude API list prices from "
              f"{PRICING_URL} (as of {PRICES_AS_OF}). This is not your actual cost; a subscription, discounts "
              "or cloud provider pricing change what you really pay.")

# USD per million tokens: (input, 5m cache write, 1h cache write, cache read, output)
_OPUS_45 = (5, 6.25, 10, 0.50, 25)
_OPUS_41 = (15, 18.75, 30, 1.50, 75)
_SONNET_45 = (3, 3.75, 6, 0.30, 15)
PRICES = {
    ("fable", "5.1"): (10, 12.50, 20, 0.25, 50),
    ("mythos", "5.1"): (10, 12.50, 20, 0.25, 50),
    ("fable", "5"): (10, 12.50, 20, 1, 50),
    ("mythos", "5"): (10, 12.50, 20, 1, 50),
    ("opus", "5.5"): (4, 5, 8, 0.20, 20),
    ("opus", "5"): _OPUS_45, ("opus", "4.8"): _OPUS_45, ("opus", "4.7"): _OPUS_45,
    ("opus", "4.6"): _OPUS_45, ("opus", "4.5"): _OPUS_45,
    ("opus", "4.1"): _OPUS_41, ("opus", "4"): _OPUS_41,
    ("sonnet", "5.5"): (2, 2.50, 4, 0.10, 10),
    ("sonnet", "5"): (2, 2.50, 4, 0.20, 10),
    ("sonnet", "4.6"): _SONNET_45, ("sonnet", "4.5"): _SONNET_45, ("sonnet", "4"): _SONNET_45,
    ("haiku", "5.5"): (0.10, 0.125, 0.20, 0.01, 0.50),
    ("haiku", "4.5"): (1, 1.25, 2, 0.10, 5),
    ("haiku", "3.5"): (0.80, 1, 1.60, 0.08, 4),
}
# Haiku 5.5 charges more for a request whose prompt (input + cache reads + cache writes) is over 100,000 tokens.
HAIKU_55_LONG = (0.50, 0.625, 1, 0.05, 2.50)
HAIKU_55_LONG_FROM = 100_000
# Fast mode (input, output); the cache multipliers apply on top of these.
FAST = {("opus", "5.5"): (8, 40), ("opus", "5"): (10, 50), ("opus", "4.8"): (10, 50)}
CACHE_READ_MULT = {("fable", "5.1"): 0.025, ("mythos", "5.1"): 0.025, ("opus", "5.5"): 0.05, ("sonnet", "5.5"): 0.05}
WEB_SEARCH_USD_PER_1K = 10
US_GEO_MULT = 1.1  # inference_geo "us" on Claude 4.6 and later

_ID_NEW = re.compile(r"claude-(fable|mythos|opus|sonnet|haiku)-(\d+)(?:-(\d{1,2}))?(?!\d)")
_ID_OLD = re.compile(r"claude-(\d)-(\d)-(opus|sonnet|haiku)")


def model_key(model_id):
    """('opus', '5.5') from 'claude-opus-5-5', 'claude-sonnet-4-5-20250929', 'us.anthropic.claude-haiku-4-5-v1:0', ..."""
    m = (model_id or "").lower()
    x = _ID_NEW.search(m)
    if x:
        fam, major, minor = x.groups()
        return fam, major + ("." + minor if minor else "")
    x = _ID_OLD.search(m)
    if x:
        return x.group(3), f"{x.group(1)}.{x.group(2)}"
    return None


def _version(v: str) -> tuple:
    return tuple(int(p) for p in v.split("."))


def _override_row(model_id, overrides):
    """--prices file: {model-substring: {input, output, cache_read, cache_write, cache_write_1h}} in USD per 1M tokens."""
    mid = (model_id or "").lower()
    for k, p in (overrides or {}).items():
        if k.lower() in mid:
            cw = p.get("cache_write", 0)
            return (p.get("input", 0), cw, p.get("cache_write_1h", cw), p.get("cache_read", 0), p.get("output", 0))
    return None


def price_usage(model_id, usage, overrides=None):
    """Estimated USD for one API request, split by part; None when the model has no known price."""
    if not isinstance(usage, dict):
        return None
    key = model_key(model_id)
    row = _override_row(model_id, overrides)
    custom = row is not None
    if row is None:
        row = PRICES.get(key)
    if row is None:
        return None
    inp = usage.get("input_tokens") or 0
    out = usage.get("output_tokens") or 0
    cr = usage.get("cache_read_input_tokens") or 0
    cw = usage.get("cache_creation_input_tokens") or 0
    cc = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    cw5, cw1h = cc.get("ephemeral_5m_input_tokens") or 0, cc.get("ephemeral_1h_input_tokens") or 0
    if cw and not (cw5 or cw1h):
        cw5 = cw  # no TTL breakdown: price as 5-minute writes, the cheaper of the two
    if not custom:
        if key == ("haiku", "5.5") and inp + cr + cw > HAIKU_55_LONG_FROM:
            row = HAIKU_55_LONG
        if usage.get("speed") == "fast" and key in FAST:
            fi, fo = FAST[key]
            row = (fi, fi * 1.25, fi * 2, fi * CACHE_READ_MULT.get(key, 0.1), fo)
    mult = 1.0
    if not custom and usage.get("inference_geo") == "us" and key and _version(key[1]) >= (4, 6):
        mult = US_GEO_MULT
    parts = {
        "input": inp * row[0] / 1e6 * mult,
        "cache_write": (cw5 * row[1] + cw1h * row[2]) / 1e6 * mult,
        "cache_read": cr * row[3] / 1e6 * mult,
        "output": out * row[4] / 1e6 * mult,
    }
    stu = usage.get("server_tool_use") if isinstance(usage.get("server_tool_use"), dict) else {}
    searches = stu.get("web_search_requests") or 0
    if searches:
        parts["web_search"] = searches * WEB_SEARCH_USD_PER_1K / 1000
    return parts


def context_tokens(usage) -> int:
    """Prompt size of one request: what the model had to read."""
    if not isinstance(usage, dict):
        return 0
    return sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
