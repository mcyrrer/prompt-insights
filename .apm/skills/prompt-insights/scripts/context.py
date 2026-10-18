"""Context-window measurements from transcript data (see references/context-window.md).

Everything here is MEASURED from usage fields and timestamps, or a labelled rule of thumb. The
thresholds are this skill's own defaults, not Anthropic's: they are written into every flag so the
report can say "flagged because ...".
"""
import re
from pathlib import Path

SUBSCRIPTION_TTL_S = 3600   # prompt-cache lifetime of the main conversation on a subscription
API_TTL_S = 300             # ... on an API key or cloud provider (and for subagents)
BIG_CONTEXT = 200_000
VERY_BIG_CONTEXT = 400_000
SWITCH_CONTEXT = 100_000
BASELINE_FLAG = 30_000
LONG_LIVED_SHARE = 0.30
BIG_RESULT_TOKENS = 20_000
SERIES_POINTS = 40
CHARS_PER_TOKEN = 4         # rough: used only for tool-result sizes, which the transcript does not count

_NATIVE_1M = re.compile(r"fable|mythos|sonnet-[5-9]|haiku-[5-9]|opus-[5-9]|opus-4-[7-9]", re.I)


def context_window(model_id, peak=0):
    """(window_tokens, how) for a model id. Unknown ids fall back on what the data shows."""
    mid = str(model_id or "")
    if mid and _NATIVE_1M.search(mid):
        return 1_000_000, "native 1M model"
    if peak > 200_000:
        return 1_000_000, "inferred: a request was larger than 200K"
    if mid.startswith("claude"):
        return 200_000, "200K unless the 1M variant is used (opus[1m] / sonnet[1m] are not visible in transcripts)"
    return None, "unknown model"


def result_tokens(content) -> int:
    """Rough token size of a tool_result block's content (chars / 4)."""
    if isinstance(content, str):
        n = len(content)
    elif isinstance(content, list):
        n = sum(len(b.get("text") or "") for b in content if isinstance(b, dict))
    else:
        n = 0
    return n // CHARS_PER_TOKEN


def _ttl_of(usage, last_ttl):
    cc = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    if (cc.get("ephemeral_1h_input_tokens") or 0) > 0:
        return 3600, "1h"
    if (cc.get("ephemeral_5m_input_tokens") or 0) > 0:
        return 300, "5m"
    return last_ttl or (SUBSCRIPTION_TTL_S, "assumed 1h")


def _downsample(points, n=SERIES_POINTS):
    if len(points) <= n:
        return points
    step = (len(points) - 1) / (n - 1)
    return [points[round(i * step)] for i in range(n)]


def session_context(main, ctx_of, slash, big_results, tool_result_tokens, subagent_runs, strong_corrections):
    """main: ordered main-conversation messages [{model, usage, effort, ts}]; ctx_of: usage -> prompt size."""
    sizes = [ctx_of(m["usage"]) for m in main]
    sizes_ok = [(m, s) for m, s in zip(main, sizes) if s > 0]
    if not sizes_ok:
        return None
    peak = max(s for _, s in sizes_ok)
    model = sizes_ok[-1][0]["model"]
    window, window_how = context_window(model, peak)
    n = len(sizes_ok)
    above = lambda t: sum(1 for _, s in sizes_ok if s > t)  # noqa: E731

    cold = []          # idle gaps longer than the cache lifetime that were followed by a big request
    switches_big = 0
    prev_m = prev_s = last_ttl = None
    for m, s in sizes_ok:
        ttl, ttl_label = _ttl_of(m["usage"], last_ttl)
        last_ttl = (ttl, ttl_label) if ttl_label in ("1h", "5m") else last_ttl
        if prev_m is not None:
            gap = (m["ts"] - prev_m["ts"]).total_seconds() if m.get("ts") and prev_m.get("ts") else 0
            written = m["usage"].get("cache_creation_input_tokens") or 0
            if gap > ttl and s >= 50_000 and written >= 0.5 * s:
                cold.append({"gap_minutes": round(gap / 60), "context_tokens": s, "ttl": ttl_label, "tokens_rewritten": written})
            if prev_s > SWITCH_CONTEXT and (m["model"] != prev_m["model"] or (m.get("effort") != prev_m.get("effort") and m.get("effort"))):
                switches_big += 1
        prev_m, prev_s = m, s

    series = [[m["ts"].strftime("%H:%M") if m.get("ts") else "", s] for m, s in sizes_ok]
    hygiene = {k: slash.get(k, 0) for k in ("clear", "compact", "rewind", "btw")}
    top_tools = sorted(tool_result_tokens.items(), key=lambda kv: -kv[1])[:5]
    return {
        "window_tokens": window, "window_basis": window_how,
        "baseline_tokens": sizes_ok[0][1],
        "peak_tokens": peak, "peak_pct_of_window": round(100 * peak / window, 1) if window else None,
        "requests": n,
        "requests_above_100k": above(SWITCH_CONTEXT), "requests_above_200k": above(BIG_CONTEXT), "requests_above_400k": above(VERY_BIG_CONTEXT),
        "share_above_200k": round(above(BIG_CONTEXT) / n, 2),
        "cold_restarts": cold[:5], "cold_restart_count": len(cold),
        "switches_at_large_context": switches_big,
        "hygiene_commands": hygiene,
        "big_tool_results": sorted(big_results, key=lambda r: -r["tokens"])[:5],
        "tool_result_tokens_top": [{"tool": k, "tokens": v} for k, v in top_tools],
        "subagent_runs": subagent_runs,
        "strong_corrections": strong_corrections,
        "series": _downsample(series),
    }


def context_flags(sessions):
    """Sample-level flags, each with the numbers that triggered it. Rules of thumb, not verdicts."""
    flags = []

    def add(key, title, rule, hits, evidence):
        if hits:
            flags.append({"key": key, "title": title, "rule": rule, "sessions": hits, "evidence": evidence})

    rows = [(s, s.get("context")) for s in sessions if s.get("context")]
    # startup baseline: the lowest first-request size per project is the best estimate of fixed overhead
    # (a resumed session starts with its old history, which inflates its first request)
    base = {}
    for s, c in rows:
        p = s.get("project", "?")
        if p not in base or c["baseline_tokens"] < base[p][0]:
            base[p] = (c["baseline_tokens"], s["id"])
    add("high_baseline", "Large startup context", f"first request of a session over {BASELINE_FLAG // 1000}K tokens (lowest per project)",
        [sid for b, sid in base.values() if b > BASELINE_FLAG],
        {p: b for p, (b, _) in base.items() if b > BASELINE_FLAG})
    add("long_lived_big", "Long time spent in a big context",
        f"{int(LONG_LIVED_SHARE * 100)}% or more of a session's requests above {BIG_CONTEXT // 1000}K tokens",
        [s["id"] for s, c in rows if c["share_above_200k"] >= LONG_LIVED_SHARE],
        {s["id"]: c["share_above_200k"] for s, c in rows if c["share_above_200k"] >= LONG_LIVED_SHARE})
    add("very_large", "Very large peak context", f"peak above {VERY_BIG_CONTEXT // 1000}K tokens",
        [s["id"] for s, c in rows if c["peak_tokens"] > VERY_BIG_CONTEXT],
        {s["id"]: c["peak_tokens"] for s, c in rows if c["peak_tokens"] > VERY_BIG_CONTEXT})
    nohyg = [s for s, c in rows if c["peak_tokens"] > BIG_CONTEXT and not any(c["hygiene_commands"].values()) and not s["compactions"]]
    add("no_hygiene", "Big session with no /clear, /compact or /rewind",
        f"peak above {BIG_CONTEXT // 1000}K tokens and none of those commands, no compaction", [s["id"] for s in nohyg],
        {s["id"]: s["context"]["peak_tokens"] for s in nohyg})
    spiral = [s for s, c in rows if c["strong_corrections"] >= 3 and not (c["hygiene_commands"]["clear"] or c["hygiene_commands"]["rewind"])]
    add("correction_spiral", "Corrections piling up in one context",
        "3 or more strong corrections and no /clear or /rewind in the same session", [s["id"] for s in spiral],
        {s["id"]: s["context"]["strong_corrections"] for s in spiral})
    add("cache_cold", "Returning to a big context after the cache expired",
        "2 or more idle gaps longer than the cache lifetime, each followed by a request of 50K+ tokens that rewrote the cache",
        [s["id"] for s, c in rows if c["cold_restart_count"] >= 2],
        {s["id"]: c["cold_restart_count"] for s, c in rows if c["cold_restart_count"] >= 2})
    add("switch_big", "Model or effort switched in a big context",
        f"model or effort changed while the previous request was above {SWITCH_CONTEXT // 1000}K tokens (the cache is per model)",
        [s["id"] for s, c in rows if c["switches_at_large_context"]],
        {s["id"]: c["switches_at_large_context"] for s, c in rows if c["switches_at_large_context"]})
    heavy = [s for s, c in rows if c["big_tool_results"] and not c["subagent_runs"]]
    add("heavy_reads", "Large tool results in the main conversation",
        f"a single tool result over {BIG_RESULT_TOKENS // 1000}K tokens (estimated) and no subagent used in the session", [s["id"] for s in heavy],
        {s["id"]: s["context"]["big_tool_results"][0] for s in heavy})
    return flags
