"""Keep a copy of every report and compare the next run with it.

build_report.py copies summary.json, insights.json and the HTML report into
<history dir>/<timestamp>/. The history dir is, in order of precedence, --history-dir, the
PROMPT_INSIGHTS_HISTORY environment variable, or ~/.claude/prompt-insights/history. It is one flat
folder for all projects; each snapshot records its --project filter and the next run only compares
with a snapshot of the same scope.
The next analyze_sessions.py run picks the newest such snapshot that is older than the newest
analysed session, then measures the sessions started since that report against the sessions the
report was built from, and checks whether the lines it proposed for agent files are on disk now.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from redact import truncate

HISTORY_DIR = "history"  # name of the legacy per-project folder inside prompt-insights/
ENV_VAR = "PROMPT_INSIGHTS_HISTORY"
DEFAULT_HISTORY = "~/.claude/prompt-insights/history"


def _dt(s):
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def resolve_history_dir(cli=None) -> Path:
    """--history-dir beats the environment variable, which beats the user-level default."""
    return Path(cli or os.environ.get(ENV_VAR) or DEFAULT_HISTORY).expanduser().resolve()


def _scope(project) -> str:
    return (project or "").strip().lower()


def snapshot(history_dir: Path, summary_path: Path, insights_path: Path, html_path=None) -> Path:
    S = json.loads(summary_path.read_text())
    gen = (S.get("meta") or {}).get("generated_at") or datetime.now(timezone.utc).isoformat()
    d = history_dir / stamp_of(gen)
    d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(summary_path, d / "summary.json")
    shutil.copyfile(insights_path, d / "insights.json")
    if html_path and Path(html_path).is_file():
        shutil.copyfile(html_path, d / "claude-prompt-insights.html")
    return d


def stamp_of(generated_at) -> str:
    """Sortable UTC timestamp such as 20261018T120301 for file and folder names."""
    gen = _dt(generated_at) or datetime.now(timezone.utc)
    return gen.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S")


def migrate_legacy(legacy_out_dir: Path, history_dir: Path) -> int:
    """Copy snapshots from an older ./prompt-insights/history/ into history_dir (never overwrites)."""
    legacy = legacy_out_dir / HISTORY_DIR
    if not legacy.is_dir() or legacy.resolve() == history_dir.resolve():
        return 0
    n = 0
    for d in sorted(p for p in legacy.iterdir() if p.is_dir()):
        dest = history_dir / d.name
        if dest.exists():
            continue
        shutil.copytree(d, dest)
        n += 1
    return n


def find_previous(history_dir: Path, newest_session_start, project=None):
    """Newest snapshot of the same scope generated before the newest analysed session started; None if none."""
    if not history_dir.is_dir() or newest_session_start is None:
        return None
    for d in sorted((p for p in history_dir.iterdir() if p.is_dir()), reverse=True):
        try:
            S = json.loads((d / "summary.json").read_text())
            I = json.loads((d / "insights.json").read_text()) if (d / "insights.json").is_file() else {}
        except Exception:
            continue
        M = S.get("meta") or {}
        if _scope((M.get("filters") or {}).get("project")) != _scope(project):
            continue
        gen = _dt(M.get("generated_at"))
        if gen and gen < newest_session_start:
            return d, S, I, gen
    return None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _pct(flags):
    flags = [f for f in flags if f is not None]
    return round(100 * sum(1 for f in flags if f) / len(flags), 1) if flags else None


def _pq(s, k):
    pq = s.get("prompt_quality")
    return pq.get(k) if isinstance(pq, dict) else None


def _cost(s):
    c = s.get("cost")
    return c.get("total_usd") if isinstance(c, dict) else None


def _verified(s):
    o = s.get("outcome")
    return o.get("verified_finish") if isinstance(o, dict) else None


# key, label, which direction is better (None: just report the change), function over sessions
METRICS = [
    ("typed_prompts", "Typed prompts per session", "lower", lambda ss: _mean(s.get("user_turns") for s in ss)),
    ("corrections_pct", "Sessions with a correction or interrupt (%)", "lower",
     lambda ss: _pct(bool(s.get("corrections") or s.get("interruptions")) for s in ss)),
    ("friction_per_turn", "Friction per typed prompt", "lower", lambda ss: _mean(s.get("friction_per_turn") for s in ss)),
    ("has_done_criteria", "First prompts that name a done check (%)", "higher", lambda ss: _pct(_pq(s, "has_done_criteria") for s in ss)),
    ("has_goal_why", "First prompts that give the goal or why (%)", "higher", lambda ss: _pct(_pq(s, "has_goal_why") for s in ss)),
    ("has_scope", "First prompts that set scope (%)", "higher", lambda ss: _pct(_pq(s, "has_scope") for s in ss)),
    ("has_context_pointer", "First prompts that point at files or docs (%)", "higher",
     lambda ss: _pct(_pq(s, "has_context_pointer") for s in ss)),
    ("asks_plan_first", "First prompts that ask for a plan first (%)", "higher", lambda ss: _pct(_pq(s, "asks_plan_first") for s in ss)),
    ("plan_mode", "Sessions using plan mode (%)", None, lambda ss: _pct(s.get("plan_mode_used") for s in ss)),
    ("verified_finish", "Sessions with edits that ended on a passing check (%)", "higher", lambda ss: _pct(_verified(s) for s in ss)),
    ("rejected_tool_calls", "Rejected tool calls per session", "lower", lambda ss: _mean(s.get("rejected_tool_calls") for s in ss)),
    ("compactions", "Context compactions per session", "lower", lambda ss: _mean(s.get("compactions") for s in ss)),
    ("cost_per_session", "Est. cost per session, USD at list price", "lower", lambda ss: _mean(_cost(s) for s in ss)),
]
METRIC_KEYS = [m[0] for m in METRICS]


def _norm(s: str) -> str:
    s = re.sub(r"[`*_>#\"'“”‘’]", "", (s or "").lower())
    s = re.sub(r"^\s*(?:[-+]|\d+[.)])\s+", "", s, flags=re.M)
    return re.sub(r"\s+", " ", s).strip()


def _words(s):
    return set(re.findall(r"[a-z0-9][a-z0-9_\-./]{2,}", (s or "").lower()))


def _landed(line: str, text: str) -> bool:
    n = _norm(line)
    if len(n) < 8 or not text:
        return False
    if n[:160] in _norm(text):
        return True
    w = _words(line)
    if len(w) < 3:
        return False
    for tl in re.split(r"\n+", text):
        tw = _words(tl)
        if tw and len(w & tw) / len(w | tw) >= 0.6:
            return True
    return False


def _targets(target: str, files):
    t = (target or "").strip().lstrip("./").lower()
    if not t or t in ("hook", "hooks", "settings.json"):
        return []
    hits = [f for f in files if f[0].lower().endswith(t)]
    if hits:
        return hits
    if "/" not in t:
        return [f for f in files if Path(f[0]).name.lower() == Path(t).name]
    p = Path(target.strip()).expanduser()  # a file of a project outside this run's sample: read it directly
    if p.is_absolute() and p.is_file():
        try:
            return [(target.strip(), p.read_text(errors="replace")[:300_000])]
        except Exception:
            return []
    return []


def check_advice(prev_insights: dict, files, hooks_text: str) -> list:
    """files: [(path, text)] of the agent files on disk now. Status per proposed line: landed, not found, target missing."""
    out = []
    af = prev_insights.get("agent_files") or {}
    for rc in af.get("repeated_corrections") or []:
        line = rc.get("proposed_line") or ""
        target = rc.get("target_file") or ""
        hook = rc.get("hook") if isinstance(rc.get("hook"), dict) else None
        if rc.get("enforcement") == "hook" or target.lower() in ("hook", "hooks"):
            ok = bool(hook and _landed(hook.get("command", ""), hooks_text))
            out.append({"kind": "hook", "item": truncate(rc.get("theme") or line, 90), "target": "settings hooks",
                        "status": "landed" if ok else "not found", "where": "settings" if ok else None})
            continue
        cands = _targets(target, files)
        pool = cands or files
        where = next((p for p, t in pool if _landed(line, t)), None)
        status = "landed" if where else ("target missing" if target and not cands and "/" in target else "not found")
        out.append({"kind": "standing rule", "item": truncate(rc.get("theme") or line, 90), "target": target or "?",
                    "status": status, "where": where})
    for rw in af.get("rewrites") or []:
        path = rw.get("path") or ""
        cands = _targets(path, files)
        if rw.get("action") == "remove":
            out.append({"kind": "remove", "item": truncate(path, 90), "target": path,
                        "status": "landed" if not cands else "not found", "where": None})
            continue
        if not cands:
            out.append({"kind": rw.get("action") or "rewrite", "item": truncate(path, 90), "target": path,
                        "status": "target missing", "where": None})
            continue
        lines = [x for x in (rw.get("proposed_text") or "").splitlines() if len(_norm(x)) >= 8]
        text = cands[0][1]
        share = sum(1 for x in lines if _landed(x, text)) / len(lines) if lines else 0
        out.append({"kind": rw.get("action") or "rewrite", "item": truncate(path, 90), "target": path,
                    "status": "landed" if share >= 0.6 else ("partly" if share > 0 else "not found"), "where": cands[0][0]})
    qw = prev_insights.get("quick_win") or {}
    if qw.get("do_this"):
        where = next((p for p, t in files if _landed(qw["do_this"], t)), None)
        out.append({"kind": "quick win", "item": truncate(qw.get("title") or qw["do_this"], 90), "target": "any agent file",
                    "status": "landed" if where else "not in a file (fine if it was a prompt habit)", "where": where})
    return out


def followup(prev, sessions_now, files, hooks_text) -> dict:
    """prev: result of find_previous. sessions_now: current session dicts with a '_start' datetime."""
    d, S_prev, I_prev, gen = prev
    before = [s for s in S_prev.get("sessions") or [] if s.get("user_turns")]
    after = [s for s in sessions_now if s.get("_start") and s["_start"] > gen and s.get("user_turns")]
    qmetric = (I_prev.get("quick_win") or {}).get("metric")
    rows = []
    for key, label, better, fn in METRICS:
        b, a = fn(before), fn(after)
        if b is None and a is None:
            continue
        rows.append({"key": key, "label": label, "better": better, "before": b, "after": a, "quick_win": key == qmetric})
    M = S_prev.get("meta") or {}
    plan = (I_prev.get("action_plan") or {}).get("now") or []
    return {
        "previous_report": {"generated_at": M.get("generated_at"), "sessions_analyzed": M.get("sessions_analyzed"),
                            "date_range": M.get("date_range"), "quick_win": (I_prev.get("quick_win") or {}).get("title"),
                            "quick_win_metric": qmetric, "snapshot": d.name},
        "previous_roots": S_prev.get("project_roots") or [],
        "previous_files": [{"path": f.get("path"), "scope": f.get("scope"), "hints": f.get("hints") or [],
                            "possibly_dead_references": f.get("possibly_dead_references") or [],
                            "status": next((x.get("status") for x in (I_prev.get("agent_files") or {}).get("findings", [])
                                            if x.get("path") == f.get("path")), None)}
                           for f in S_prev.get("agent_files") or []],
        "sessions_since": len(after),
        "sessions_since_ids": [s["id"] for s in after][:30],
        "metrics": rows,
        "advice": check_advice(I_prev, files, hooks_text),
        "previous_now_items": [truncate(x.get("text", "") if isinstance(x, dict) else str(x), 200) for x in plan][:8],
        "note": ("'before' is the sample the previous report was built from; 'after' is the sessions in this run that "
                 "started after that report. Small groups move a lot by chance."),
    }
