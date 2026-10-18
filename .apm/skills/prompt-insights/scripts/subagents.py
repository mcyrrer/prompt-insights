"""Read the subagent and workflow-agent transcripts that sit next to a session file.

Layout (Claude Code 2.1.x):
  <project>/<session-id>.jsonl                                          the main conversation
  <project>/<session-id>/subagents/agent-<id>.jsonl (+ .meta.json)        Agent tool runs
  <project>/<session-id>/subagents/workflows/wf_<id>/agent-<id>.jsonl     workflow agents
The .meta.json next to each transcript carries agentType and, for workflow agents, workflowPhase.
Older versions wrote subagent messages into the main file as isSidechain entries instead;
analyze_sessions.py still counts those.

These files can add up to gigabytes, so only assistant lines and failed tool results are parsed.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from pricing import context_tokens, price_usage
from redact import redact, truncate

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Commands that check work: tests, builds, type checks and linters. A heuristic, kept narrow on purpose.
CHECK_RE = re.compile(
    r"(?i)(?:^|[\s;&|(])(?:pytest|py\.test|tox|nox|jest|vitest|mocha|rspec|phpunit|ctest|tsc|eslint|ruff|mypy|flake8|pyright"
    r"|python3?\s+-m\s+(?:pytest|unittest|py_compile|compileall)|node\s+--test|bun\s+test|deno\s+test"
    r"|(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:test|build|lint|check|typecheck|verify)\b|npx\s+(?:jest|vitest|playwright|tsc|eslint)"
    r"|playwright\s+test|go\s+(?:test|build|vet)|cargo\s+(?:test|build|check|clippy)|mvn\s|gradlew?\s|make(?:\s+(?:test|check|lint|build|all))?\s*(?:$|[;&|])"
    r"|swift\s+(?:test|build)|xcodebuild|dotnet\s+(?:test|build)|bazel\s+(?:test|build)|terraform\s+(?:validate|plan)|helm\s+lint|shellcheck)")


def _ts(e):
    return e.get("timestamp") if isinstance(e.get("timestamp"), str) else None


def parse_agent(path: Path, workflow, overrides=None) -> dict:
    """One subagent transcript: models, tokens, estimated cost, effort, tools, edits and checks."""
    meta = {}
    mp = path.with_suffix(".meta.json")
    if mp.is_file():
        try:
            meta = json.loads(mp.read_text(errors="replace"))
        except Exception:
            meta = {}
    msgs, tools, checks, err_ids = {}, {}, [], set()
    last_edit = None
    times = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            is_asst = '"assistant"' in line
            if not is_asst and '"is_error":true' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not isinstance(e, dict):
                continue
            msg = e.get("message") if isinstance(e.get("message"), dict) else {}
            content = msg.get("content") if isinstance(msg.get("content"), list) else []
            if e.get("type") == "user":
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                        err_ids.add(b.get("tool_use_id"))
                continue
            if e.get("type") != "assistant":
                continue
            ts = _ts(e)
            if ts:
                times.append(ts)
            mid = msg.get("id") or e.get("uuid") or f"m{len(msgs)}"
            usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
            out = usage.get("output_tokens") or 0
            rec = msgs.get(mid)
            if rec is None or out >= rec["out"]:
                msgs[mid] = {"model": msg.get("model"), "usage": usage, "out": out, "effort": e.get("effort")}
            for b in content:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                tid = b.get("id") or f"t{len(tools)}"
                if tid in tools:
                    continue
                name = b.get("name")
                tools[tid] = name
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                if name in EDIT_TOOLS and ts and (last_edit is None or ts > last_edit):
                    last_edit = ts
                elif name == "Bash" and CHECK_RE.search(str(inp.get("command", ""))):
                    checks.append((tid, ts))

    by_model = defaultdict(lambda: {"msgs": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0})
    parts, effort, unpriced, peak = Counter(), Counter(), 0, 0
    for m in msgs.values():
        mid = m["model"]
        if not mid or str(mid).startswith("<"):
            continue
        u = m["usage"]
        d = by_model[mid]
        d["msgs"] += 1
        d["input"] += u.get("input_tokens") or 0
        d["output"] += u.get("output_tokens") or 0
        d["cache_read"] += u.get("cache_read_input_tokens") or 0
        d["cache_write"] += u.get("cache_creation_input_tokens") or 0
        p = price_usage(mid, u, overrides)
        if p is None:
            unpriced += 1
        else:
            d["cost"] += sum(p.values())
            parts.update(p)
        if m["effort"]:
            effort[str(m["effort"])] += 1
        peak = max(peak, context_tokens(u))
    return {
        "agent_type": str(meta.get("agentType") or "unknown"),
        "phase": redact(truncate(meta.get("workflowPhase") or "", 40)) or None,
        "workflow": workflow,
        "models": {k: dict(v) for k, v in by_model.items()},
        "cost_parts": dict(parts),
        "unpriced_msgs": unpriced,
        "effort": dict(effort),
        "tool_calls": len(tools),
        "tool_errors": len(err_ids & set(tools)),
        "edit_calls": sum(1 for n in tools.values() if n in EDIT_TOOLS),
        "last_edit": last_edit,
        "checks": [(ts, tid not in err_ids) for tid, ts in checks],
        "start": min(times) if times else None,
        "end": max(times) if times else None,
        "peak_context": peak,
    }


def read_subagents(session_file: Path, overrides=None) -> list:
    base = session_file.with_suffix("") / "subagents"
    if not base.is_dir():
        return []
    runs = [parse_agent(f, None, overrides) for f in sorted(base.glob("agent-*.jsonl"))]
    wf_root = base / "workflows"
    if wf_root.is_dir():
        for wf in sorted(p for p in wf_root.glob("wf_*") if p.is_dir()):
            runs += [parse_agent(f, wf.name, overrides) for f in sorted(wf.glob("agent-*.jsonl"))]
    return runs


def summarize(runs, family) -> dict:
    """Roll the runs of one session up by agent type, by workflow and by model family."""
    def tok():
        return {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}

    by_type = {}
    wfs = {}
    models, cost_by_model, tokens = Counter(), Counter(), defaultdict(tok)
    parts, effort, ids = Counter(), Counter(), defaultdict(set)
    total = 0.0
    for r in runs:
        run_cost = 0.0
        run_models = Counter()
        for mid, d in r["models"].items():
            f = family(mid)
            ids[f].add(mid)
            run_models[f] += d["msgs"]
            cost_by_model[f] += d["cost"]
            run_cost += d["cost"]
            for k in ("input", "output", "cache_read", "cache_write"):
                tokens[f][k] += d[k]
        total += run_cost
        models.update(run_models)
        parts.update(r["cost_parts"])
        effort.update(r["effort"])
        t = by_type.setdefault(r["agent_type"], {"runs": 0, "models": Counter(), "effort": Counter(), "cost_usd": 0.0,
                                                 "tool_calls": 0, "tool_errors": 0, "edit_calls": 0, "unpriced_msgs": 0})
        t["runs"] += 1
        t["models"].update(run_models)
        t["effort"].update(r["effort"])
        t["cost_usd"] += run_cost
        for k in ("tool_calls", "tool_errors", "edit_calls", "unpriced_msgs"):
            t[k] += r[k]
        if r["workflow"]:
            w = wfs.setdefault(r["workflow"], {"id": r["workflow"][:11], "runs": 0, "phases": Counter(), "types": Counter(),
                                               "models": Counter(), "cost_usd": 0.0})
            w["runs"] += 1
            w["phases"][r["phase"] or "-"] += 1
            w["types"][r["agent_type"]] += 1
            w["models"].update(run_models)
            w["cost_usd"] += run_cost
    for t in by_type.values():
        t["models"], t["effort"], t["cost_usd"] = dict(t["models"]), dict(t["effort"]), round(t["cost_usd"], 4)
    for w in wfs.values():
        w["phases"], w["types"], w["models"], w["cost_usd"] = (dict(w["phases"]), dict(w["types"]), dict(w["models"]),
                                                               round(w["cost_usd"], 4))
    return {
        "runs": len(runs),
        "workflow_runs": sum(1 for r in runs if r["workflow"]),
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1]["runs"])),
        "workflows": sorted(wfs.values(), key=lambda w: -w["runs"]),
        "models": dict(models),
        "tokens": {k: dict(v) for k, v in tokens.items()},
        "cost_by_model": {k: round(v, 4) for k, v in cost_by_model.items()},
        "cost_usd": round(total, 4),
        "cost_parts": {k: round(v, 4) for k, v in parts.items()},
        "unpriced_msgs": sum(r["unpriced_msgs"] for r in runs),
        "effort": dict(effort),
        "tool_calls": sum(r["tool_calls"] for r in runs),
        "tool_errors": sum(r["tool_errors"] for r in runs),
        "edit_calls": sum(r["edit_calls"] for r in runs),
        "peak_context": max((r["peak_context"] for r in runs), default=0),
        # used by analyze_sessions.py and removed before writing summary.json
        "model_ids": {k: sorted(v) for k, v in ids.items()},
        "_last_edit":max((r["last_edit"] for r in runs if r["last_edit"]), default=None),
        "_checks": [c for r in runs for c in r["checks"]],
    }
