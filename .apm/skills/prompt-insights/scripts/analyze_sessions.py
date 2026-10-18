#!/usr/bin/env python3
"""Summarize Claude Code session transcripts into one compact, redacted JSON file.

Read-only on ~/.claude. Standard library only. Writes only the --out file.

Modes
  (default)         analyze sessions and write summary.json
  --schema          print the observed JSONL structure (keys only, no values) and exit
  --show <id>       print a redacted, truncated transcript of one session (to verify a flagged turn)

Everything it reports is either MEASURED (counts, tokens, timestamps, tool calls) or a
HEURISTIC (task type, correction flags, prompt-quality flags). Heuristics are candidates
for the model to confirm, not conclusions. Costs are ESTIMATES: measured token counts priced
at the list prices in pricing.py, never the user's real bill.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True  # keep the installed skill folder free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
from context import BIG_RESULT_TOKENS, context_flags, result_tokens, session_context  # noqa: E402
from history import ENV_VAR, find_previous, followup, migrate_legacy, resolve_history_dir  # noqa: E402
from outdir import DEFAULT_DIR, ensure_output_dir  # noqa: E402
from pricing import DISCLAIMER, PRICES_AS_OF, PRICING_URL, context_tokens, price_usage  # noqa: E402
from redact import compile_extra, redact, tilde, truncate  # noqa: E402
from settings_scan import scan_settings  # noqa: E402
from subagents import CHECK_RE, EDIT_TOOLS, read_subagents, summarize  # noqa: E402

SCHEMA_VERSION = 3
ACTIVE_GAP_S = 300
INTERRUPT_PREFIX = "[Request interrupted by user"
INJECTED_PREFIXES = (
    "<system-reminder", "<local-command", "<command-message", "<command-name",
    "<user-prompt-submit-hook", "<bash-input", "<bash-stdout", "<bash-stderr",
    "Caveat:", "This session is being continued",
)
# Entries written by the harness or by other sessions, not typed by the user.
AUTO_PREFIXES = ("<task-notification", "Another Claude session")
PASTED_RE = re.compile(r"</?pasted_content[^>]*>")
# Slash commands that run harness features; every other /command is a skill or custom command
# whose <command-args> text is a prompt the user really typed.
BUILTIN_CMDS = {"model", "clear", "compact", "sandbox", "reload-plugins", "help", "config", "resume", "status",
                "cost", "doctor", "login", "logout", "mcp", "agents", "permissions", "memory", "init", "exit",
                "usage", "context", "fast", "effort", "plugin", "hooks", "ide", "vim", "theme", "rewind",
                "export", "copy", "skills", "tasks", "workflows", "artifacts", "feedback"}
# Entry types that carry no prompt or usage data; listed so the warning stays about real surprises.
KNOWN_IGNORED_TYPES = {"user", "assistant", "summary", "system", "file-history-snapshot", "queue-operation",
                       "mode", "attachment", "atis-latch", "last-prompt", "file-history-delta", "ai-title",
                       "permission-mode", "cost-state", "frame-link", "artifact-comment-monitor",
                       "artifact-autoreact-ledger", "custom-title", "agent-name", "progress", "bridge-session", "pr-link",
                       "continued-in", "api-request", "api-request-shape", "api-request-blob"}
TASK_TYPES = ["bugfix", "feature", "refactor", "docs", "review", "infra-ci", "scripting", "exploration",
              "chore", "other"]
CMD_RE = re.compile(r"<command-name>\s*(/?[\w:\-]+)\s*</command-name>")
CMD_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)

TIER = {"haiku": 1, "sonnet": 2, "opus": 3, "mythos": 4, "fable": 4}

AGENT_FILE_RE = re.compile(
    r"(?:^|/)(?:CLAUDE(?:\.local)?\.md|AGENTS\.md|SKILL\.md|copilot-instructions\.md"
    r"|\.claude/(?:rules|commands|agents|skills)/.+|\.github/instructions/.+)$", re.I)
AGENT_FILE_IN_CMD_RE = re.compile(
    r"[\w./~\-]*(?:CLAUDE(?:\.local)?\.md|AGENTS\.md|SKILL\.md|copilot-instructions\.md"
    r"|\.claude/(?:rules|commands|agents|skills)/[\w./\-]+)", re.I)
# A write operator must sit right before the path, otherwise `cat CLAUDE.md` or `grep x SKILL.md` would count.
WRITE_BEFORE_RE = re.compile(
    r"(?:>>?|\btee\b(?:\s+-a)?|\bsed\s+-i\S*(?:\s+(?:'[^']*'|\"[^\"]*\"|-e\s+\S+))*|\bcp\b(?:\s+-\S+)*(?:\s+\S+)?|\bmv\b(?:\s+-\S+)*(?:\s+\S+)?"
    r"|\bperl\s+-pi\S*(?:\s+'[^']*')?)\s*['\"]?$")
BASH_WRITE_RE = re.compile(r"(sed\s+-i|>>|[^>]>[^>&]|\btee\b|cat\s*<<|\bmv\b|\bcp\b|\brm\b|\bperl\s+-pi)")
COMMIT_RE = re.compile(r"\bgit\b[^|;&\n]*\bcommit\b")
PUSH_RE = re.compile(r"\bgit\b[^|;&\n]*\bpush\b")
PR_RE = re.compile(r"\bgh\s+pr\s+create\b")
# Tools whose "approval" is the user answering a question or a plan, not a permission prompt.
INTERACTIVE_TOOLS = {"AskUserQuestion", "ExitPlanMode", "EnterPlanMode"}
ASKS_UPDATE_RE = re.compile(
    r"(?i)\b(update|add (this|that|it)|put (this|that|it)|remember|save)\b.{0,50}"
    r"(CLAUDE\.md|AGENTS\.md|\brules?\b|\bskills?\b|\bmemory\b|instructions)")

NO_PHRASES_RE = re.compile(r"(?i)\bno (problem|worries|rush|need|idea|doubt)\b|\bnot a problem\b")
STRONG_RE = re.compile(
    r"(?i)\b(wrong|not that|not what i|that'?s not|incorrect|undo|revert|roll ?back|stop|"
    r"i (said|asked|told you)|why did you|you (broke|missed|forgot|ignored)|didn'?t (work|ask))\b")
WEAK_RE = re.compile(
    r"(?i)(^\s*no\b|\bnope\b|\bdon'?t\b|\bdo not\b|\bagain\b|\binstead\b|"
    r"\bstill (not|fail\w*|broken|wrong|doesn))")

GOAL_RE = re.compile(r"(?i)\b(so that|because|in order to|the goal|goal is|to avoid|to prevent|so we can|so it can|the reason)\b")
SCOPE_RE = re.compile(
    r"(?i)\b(only|don'?t (touch|change|modify|edit)|do not (touch|change|modify|edit)|"
    r"without (changing|touching|modifying)|keep the diff|minimal|limit(ed)? to|must not)\b")
CONTEXT_RE = re.compile(
    r"(`[^`]+`|@\S+|\b[\w\-.]+/[\w\-./]+|\b[\w\-]+\.(?:py|js|ts|tsx|go|rs|java|kt|yml|yaml|json|md|sh|tf|groovy|swift|cs|rb)\b|https?://)")
DONE_RE = re.compile(
    r"(?i)\b(tests? (pass|should)|run (the )?(tests?|lint|build|make|npm|pytest|pnpm|yarn|go test)|"
    r"make (test|lint|build)|verify|done when|when (done|finished)|lint(er)?|should (output|return|print|pass)|expected|acceptance|until (it|the|all) )\b")
PLAN_RE = re.compile(
    r"(?i)\b(plan first|make a plan|propose|outline (an )?approach|before (you )?(edit|code|change|writing)|"
    r"don'?t (edit|write|change) (anything )?yet|think (it )?through|step by step|list the files)\b")

TASK_RULES = [
    ("review", r"\b(review|pull request|\bpr\b|audit|critique)\b"),
    ("docs", r"\b(readme|docs?|documentation|changelog|docstring|comment(s)?)\b"),
    ("refactor", r"\b(refactor|rename|restructure|clean ?up|extract|simplif\w+|migrate|move .* to)\b"),
    ("infra-ci", r"\b(jenkins|github actions|docker\w*|helm|kubernetes|k8s|aks|terraform|ingress)\b"),
    ("bugfix", r"\b(fix|bug|error|fails?|failing|broken|crash\w*|exception|traceback|not working|doesn'?t work|does not|regression)\b"),
    ("scripting", r"\b(script|bash|one-?liner|cli|automate|cron)\b"),
    ("chore", r"(\b1:1\b|\b(copy|clone|install|download|commit|push|set ?up)\b)"),
    ("feature", r"\b(add|implement|create|build|new|support|introduce)\b"),
    ("exploration", r"(\?|\b(explain|understand|investigate|look at|find out|how does|what is|why does|where is)\b)"),
]
# Words that suggest infra work only when several show up together (one hit is usually noise).
WEAK_INFRA_RE = re.compile(r"(?i)\b(pipeline|workflow|runner|pod|yaml|deploy\w*|ci)\b")
TASK_RULES = [(n, re.compile(rx, re.I)) for n, rx in TASK_RULES]

STOP = set("""the and for that this with from have what when where which would could should about into your you are was were
will can not but all any out use using please make sure then than them they there here just also like need want let get got
its it's i'm don't dont does did how why who has had been being some more most only over under again still instead""".split())


# ----------------------------------------------------------------------------- helpers

def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def family(model):
    m = (model or "").lower()
    for k in TIER:
        if k in m:
            return k
    return m or "unknown"


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def content_tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z][a-z0-9_\-]{2,}", (text or "").lower()) if w not in STOP}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def iter_entries(path: Path):
    """Yield parsed JSON objects; yield None for lines that fail to parse."""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                yield obj if isinstance(obj, dict) else None
            except Exception:
                yield None


def classify_task(prompts):
    """Heuristic task type from the first substantive prompts (first 400 chars each)."""
    if not prompts:
        return "other"
    if prompts[0].rstrip().endswith("?") and len(prompts[0].split()) < 25:
        return "exploration"
    blob = " ".join(p[:400] for p in prompts[:3]).lower()
    for name, rx in TASK_RULES:
        if rx.search(blob):
            return name
    if len({m.lower() for m in WEAK_INFRA_RE.findall(blob)}) >= 2:
        return "infra-ci"
    return "other"


def clean_prompt(text: str) -> str:
    """Remove <pasted_content> wrapper tags; the pasted text itself is kept."""
    return PASTED_RE.sub("", text or "").strip()


def classify_user(e, msg):
    """Return (kind, text, extra) for a non-sidechain user entry.

    kind: empty | interrupt | command | auto | human. Used by both the analyzer and --show
    so that turn numbers always agree. Newer versions say where a prompt came from in
    promptSource (typed, queued, sdk, system); older ones are recognised by their prefixes.
    """
    text = text_of(msg.get("content")).strip()
    if not text:
        return "empty", "", None
    if text.startswith(INTERRUPT_PREFIX):
        return "interrupt", text, None
    m = CMD_RE.search(text)
    if m and text.startswith("<command"):
        a = CMD_ARGS_RE.search(text)
        return "command", text, (m.group(1).lstrip("/"), (a.group(1).strip() if a else ""))
    origin = e.get("origin") if isinstance(e.get("origin"), dict) else {}
    source = e.get("promptSource")
    if (origin.get("kind") and origin["kind"] != "human") or text.startswith(AUTO_PREFIXES):
        return "auto", text, origin.get("kind") or "other-session"
    if source == "system":
        return "auto", text, "system"
    if source in ("typed", "queued", "sdk"):  # sdk: the desktop app sends what the user typed through the SDK
        return "human", text, None
    if text.startswith(INJECTED_PREFIXES):
        return "auto", text, "injected"
    return "human", text, None


def norm_agent_path(p, cwd):
    """Normalise a path seen in a tool call. None for temp/scratch paths and non-.md targets."""
    p = (p or "").strip().strip("\"'")
    if not p or "TMPDIR" in p or p.startswith(("/tmp/", "/private/tmp", "/var/folders")) or "/tmp/claude" in p:
        return None
    if p.startswith("~"):
        p = os.path.expanduser(p)
    elif not p.startswith("/") and cwd:
        p = os.path.join(cwd, p)
    p = tilde(os.path.normpath(p))
    return p if p.lower().endswith(".md") else None


def prompt_quality(text: str) -> dict:
    return {
        "words": len(text.split()),
        "has_goal_why": bool(GOAL_RE.search(text)),
        "has_scope": bool(SCOPE_RE.search(text)),
        "has_context_pointer": bool(CONTEXT_RE.search(text)),
        "has_done_criteria": bool(DONE_RE.search(text)),
        "asks_plan_first": bool(PLAN_RE.search(text)),
    }


# ----------------------------------------------------------------------------- per-session parsing

def add_agent_edit(store, path, tool, ts):
    """Record one agent-file write, merging repeats of the same (path, tool) into a count."""
    if not path:
        return
    rec = store.setdefault((path, tool), {"path": path, "tool": tool, "ts": ts, "count": 0})
    rec["count"] += 1


def parse_session(path: Path, extra, labels: dict, overrides=None, with_subagents=True) -> dict:
    sid = path.stem
    bad_lines = 0
    total_lines = 0
    types = Counter()
    cwd_counter = Counter()
    versions = Counter()
    ts_all = []
    typed = []
    interruptions = 0
    auto_turns = Counter()
    default_saved = 0
    slash = Counter()
    slash_models = []
    slash_effort = []
    msgs = {}
    tools = {}
    err_ids = set()
    plan_mode = False
    modes = Counter()
    denials, denied_tools = Counter(), Counter()
    approvals, approval_cmds, blocked = Counter(), Counter(), Counter()
    compact_boundaries = compact_summaries = api_errors = 0
    tool_res_tokens, big_results = Counter(), []
    turn_ms = []
    hooks = {"runs": 0, "errors": 0, "blocked_stop": 0}
    title = custom_title = None
    prs = 0
    cost_state = None

    for e in iter_entries(path):
        total_lines += 1
        if e is None:
            bad_lines += 1
            continue
        t = e.get("type")
        types[t] += 1
        ts = parse_ts(e.get("timestamp"))
        if ts:
            ts_all.append(ts)
        if e.get("cwd"):
            cwd_counter[e["cwd"]] += 1
        if e.get("version"):
            versions[e["version"]] += 1
        if e.get("permissionMode") == "plan":
            plan_mode = True
        side = bool(e.get("isSidechain"))
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}

        if t == "permission-mode" and e.get("permissionMode"):
            modes[str(e["permissionMode"])] += 1
            plan_mode = plan_mode or e["permissionMode"] == "plan"
        elif t == "ai-title" and e.get("aiTitle"):
            title = e["aiTitle"]
        elif t == "custom-title" and e.get("customTitle"):
            custom_title = e["customTitle"]
        elif t == "pr-link":
            prs += 1
        elif t == "cost-state":
            cost_state = e
        elif t == "system":
            st = e.get("subtype")
            if st == "compact_boundary":
                compact_boundaries += 1
            elif st == "turn_duration" and isinstance(e.get("durationMs"), (int, float)):
                turn_ms.append(e["durationMs"])
            elif st == "api_error":
                api_errors += 1
            elif st == "stop_hook_summary":
                hooks["runs"] += e.get("hookCount") or 1
                hooks["errors"] += len(e["hookErrors"]) if isinstance(e.get("hookErrors"), list) else 0
                hooks["blocked_stop"] += 1 if e.get("preventedContinuation") else 0

        if t == "user":
            content = msg.get("content")
            results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"] if isinstance(content, list) else []
            for b in results:
                if b.get("is_error"):
                    err_ids.add(b.get("tool_use_id") or f"err{len(err_ids)}")
            if results and not side:
                names = [(tools.get(b.get("tool_use_id")) or {}).get("name") or "?" for b in results]
                for b, n in zip(results, names):
                    rt = result_tokens(b.get("content"))
                    tool_res_tokens[n] += rt
                    if rt >= BIG_RESULT_TOKENS:
                        big_results.append({"tool": n, "tokens": rt})
                if e.get("toolDenialKind"):
                    denials[str(e["toolDenialKind"])] += 1
                    if e["toolDenialKind"] == "user-rejected":
                        denied_tools.update(names)
                pd = e.get("permissionDecision") if isinstance(e.get("permissionDecision"), dict) else {}
                if str(pd.get("source", "")).startswith("user"):
                    for b, n in zip(results, names):
                        if n in INTERACTIVE_TOOLS:
                            continue
                        approvals[n] += 1
                        if n == "Bash":
                            cmd = str(((tools.get(b.get("tool_use_id")) or {}).get("input") or {}).get("command", ""))
                            approval_cmds[" ".join(cmd.split()[:2])] += 1
                elif pd.get("decision") == "reject":
                    blocked[str(pd.get("reasonType") or pd.get("source") or "rule")] += 1
            if e.get("isCompactSummary"):
                compact_summaries += 1
            if side or e.get("isMeta") or e.get("isCompactSummary"):
                continue
            kind, text, extra_ = classify_user(e, msg)
            if kind == "empty":
                continue
            if kind == "interrupt":
                interruptions += 1
            elif kind == "auto":
                auto_turns[extra_] += 1
                if "default for new sessions" in text:
                    default_saved += 1
            elif kind == "command":
                name, args = extra_
                slash[name] += 1
                if name == "model":
                    if args:
                        slash_models.append(truncate(args, 40))
                elif name == "effort":
                    if args:
                        slash_effort.append(truncate(args, 20))
                elif name not in BUILTIN_CMDS and args:
                    # a skill or custom command: the args are a prompt the user typed
                    typed.append({"text": args, "ts": ts, "via": "/" + name})
            else:
                typed.append({"text": text, "ts": ts, "via": None})

        elif t == "assistant":
            mid = msg.get("id") or e.get("uuid") or f"m{len(msgs)}"
            usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
            out = usage.get("output_tokens") or 0
            rec = msgs.get(mid)
            if rec is None or out >= rec["out"]:
                msgs[mid] = {"model": msg.get("model"), "usage": usage, "out": out, "side": side,
                             "effort": e.get("effort"), "ts": (rec or {}).get("ts") or ts, "order": len(msgs) if rec is None else rec["order"]}
            content = msg.get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tid = b.get("id") or f"t{len(tools)}"
                        if tid not in tools:
                            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                            tools[tid] = {"name": b.get("name"), "input": inp, "ts": ts, "side": side}

    # --- models and tokens (deduplicated by message id)
    real = [m for m in sorted(msgs.values(), key=lambda x: x["order"])
            if m["model"] and not str(m["model"]).startswith("<")]
    main = [m for m in real if not m["side"]]
    fam_msgs, sub_models, tokens, model_ids = Counter(), Counter(), defaultdict(Counter), defaultdict(set)
    cost_by_model, parts, effort = Counter(), Counter(), Counter()
    main_cost = side_cost = 0.0
    unpriced = peak = 0
    for m in real:
        f = family(m["model"])
        model_ids[f].add(m["model"])
        u = m["usage"]
        tk = tokens[f]
        tk["input"] += u.get("input_tokens") or 0
        tk["output"] += u.get("output_tokens") or 0
        tk["cache_read"] += u.get("cache_read_input_tokens") or 0
        tk["cache_write"] += u.get("cache_creation_input_tokens") or 0
        p = price_usage(m["model"], u, overrides)
        c = sum(p.values()) if p else 0.0
        if p is None:
            unpriced += 1
        else:
            parts.update(p)
            cost_by_model[f] += c
        if m["side"]:
            sub_models[f] += 1
            side_cost += c
        else:
            fam_msgs[f] += 1
            main_cost += c
            peak = max(peak, context_tokens(u))
            if m["effort"]:
                effort[str(m["effort"])] += 1
    switches, prev = [], None
    for m in main:
        if prev and m["model"] != prev:
            switches.append({"from": prev, "to": m["model"]})
        prev = m["model"]

    # --- tools
    cwd_main = cwd_counter.most_common(1)[0][0] if cwd_counter else None
    tool_counts, edited, agent_edits = Counter(), set(), {}
    bash_writes = 0
    skills, subagents = Counter(), Counter()
    exit_plan = False
    last_edit, checks = None, []
    committed = pushed = pr_cmds = 0
    for tid, tl in tools.items():
        name, inp = tl["name"], tl["input"]
        if not tl["side"]:
            tool_counts[name] += 1
        fp = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
        if name in EDIT_TOOLS and fp:
            if not tl["side"]:
                edited.add(fp)
                if tl["ts"] and (last_edit is None or tl["ts"] > last_edit):
                    last_edit = tl["ts"]
            if AGENT_FILE_RE.search(str(fp)):
                add_agent_edit(agent_edits, norm_agent_path(str(fp), cwd_main), name, tl["ts"])
        elif name == "Bash":
            cmd = str(inp.get("command", ""))
            if not tl["side"]:
                if CHECK_RE.search(cmd):
                    checks.append((tl["ts"], tid not in err_ids))
                committed += bool(COMMIT_RE.search(cmd))
                pushed += bool(PUSH_RE.search(cmd))
                pr_cmds += bool(PR_RE.search(cmd))
            if BASH_WRITE_RE.search(cmd):
                if not tl["side"]:
                    bash_writes += 1
                for m in AGENT_FILE_IN_CMD_RE.finditer(cmd):
                    if WRITE_BEFORE_RE.search(cmd[max(0, m.start() - 80):m.start()]):
                        add_agent_edit(agent_edits, norm_agent_path(m.group(0), cwd_main), "Bash", tl["ts"])
        elif name == "Skill":
            sk = inp.get("skill") or inp.get("command") or inp.get("name")
            if sk:
                skills[str(sk)] += 1
        elif name in ("Task", "Agent"):
            subagents[str(inp.get("subagent_type") or "general")] += 1
        elif name == "ExitPlanMode":
            exit_plan = True

    # --- prompts, friction, quality
    texts = [clean_prompt(p["text"]) for p in typed]
    pasted_first = False
    keep = [i for i, x in enumerate(texts) if x]
    texts = [texts[i] for i in keep]
    typed = [typed[i] for i in keep]
    # the first prompt worth judging: skip stray openers like "a" or "yes"
    first_idx = next((i for i, x in enumerate(texts) if len(x.split()) >= 4), 0)
    if texts:
        pasted_first = bool(PASTED_RE.search(typed[first_idx]["text"]))
    corrections, memory_shortcuts, asks_update = [], 0, 0
    toks = [content_tokens(x) for x in texts]
    for i, text in enumerate(texts):
        if text.lstrip().startswith("#") and not text.lstrip().startswith("##") and len(text) < 600:
            memory_shortcuts += 1
        if ASKS_UPDATE_RE.search(text[:400]):
            asks_update += 1
        if i == 0:
            continue
        head = NO_PHRASES_RE.sub(" ", text[:300])
        strength = "strong" if STRONG_RE.search(head) else ("weak" if (WEAK_RE.search(head) and len(text) < 400) else None)
        if strength:
            corrections.append({"turn": i, "strength": strength, "excerpt": redact(truncate(text, 160), extra)})
    repeat_pairs = 0
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if len(toks[i]) >= 4 and len(toks[j]) >= 4 and jaccard(toks[i], toks[j]) >= 0.6:
                repeat_pairs += 1

    n_turns = len(texts)
    strong = sum(1 for c in corrections if c["strength"] == "strong")
    weak = len(corrections) - strong
    rejected = denials.get("user-rejected", 0)  # the user said no to a tool call: a correction without words
    friction = strong * 2 + weak * 0.5 + interruptions * 1.5 + repeat_pairs * 2 + rejected * 1.5
    substantive = [x for x in texts if len(x.split()) >= 4]
    task = labels.get(sid) or classify_task(substantive or texts)

    ts_all.sort()
    active = 0.0
    for a, b in zip(ts_all, ts_all[1:]):
        gap = (b - a).total_seconds()
        if 0 < gap <= ACTIVE_GAP_S:
            active += gap
    cwd = cwd_counter.most_common(1)[0][0] if cwd_counter else None
    primary = fam_msgs.most_common(1)[0][0] if fam_msgs else None

    # --- subagent and workflow transcripts in <session-id>/subagents/
    sub = summarize(read_subagents(path, overrides), family) if with_subagents else summarize([], family)
    for f, msgs_n in sub_models.items():  # older versions: subagent messages inline as sidechain entries
        sub["models"][f] = sub["models"].get(f, 0) + msgs_n
    sub_cost = sub["cost_usd"] + side_cost

    # --- how the session ended: did a check pass after the last edit (here or in a subagent)?
    sub_last = parse_ts(sub.pop("_last_edit"))
    sub_checks = [(parse_ts(ts), ok) for ts, ok in sub.pop("_checks")]
    edits_at = [x for x in (last_edit, sub_last) if x]
    final_edit = max(edits_at) if edits_at else None
    all_checks = [c for c in checks + sub_checks if c[0]]
    verified = None
    if final_edit:
        verified = any(ok and ts >= final_edit for ts, ok in all_checks)
    outcome = {"edited": bool(final_edit), "checks_run": len(all_checks),
               "checks_after_last_edit": sum(1 for ts, _ in all_checks if final_edit and ts >= final_edit),
               "verified_finish": verified, "committed": committed > 0, "pushed": pushed > 0,
               "prs": max(prs, pr_cmds)}

    total_parts = Counter(parts)
    total_parts.update(sub["cost_parts"])
    cs = cost_state if isinstance(cost_state, dict) else {}
    cost = {"total_usd": round(main_cost + sub_cost, 4), "main_usd": round(main_cost, 4), "subagent_usd": round(sub_cost, 4),
            "by_model": {k: round(v + sub["cost_by_model"].get(k, 0), 4) for k, v in (cost_by_model + Counter()).items()},
            "parts": {k: round(v, 4) for k, v in total_parts.items()},
            "unpriced_msgs": unpriced + sub["unpriced_msgs"],
            "claude_code_reported_usd": round(cs["totalCostUSD"], 4) if isinstance(cs.get("totalCostUSD"), (int, float)) else None}
    for k, v in sub["cost_by_model"].items():
        cost["by_model"].setdefault(k, round(v, 4))
    for f, tk in sub["tokens"].items():  # tokens and model ids include subagents, like the cost
        for k, v in tk.items():
            tokens[f][k] += v
    for f, ids in sub.pop("model_ids").items():
        model_ids[f].update(ids)

    return {
        "id": sid,
        "session_id": sid,
        "_cwd": cwd,
        "_start": ts_all[0] if ts_all else None,
        "cwd": tilde(cwd) if cwd else None,
        "start": ts_all[0].isoformat() if ts_all else None,
        "end": ts_all[-1].isoformat() if ts_all else None,
        "duration_min": round((ts_all[-1] - ts_all[0]).total_seconds() / 60, 1) if len(ts_all) > 1 else 0,
        "active_min": round(active / 60, 1),
        "claude_code_version": versions.most_common(1)[0][0] if versions else None,
        "title": redact(truncate(custom_title or title, 80), extra) if (custom_title or title) else None,
        "user_turns": n_turns,
        "assistant_msgs": len(main),
        "first_prompt": redact(truncate(texts[first_idx], 400), extra) if texts else None,
        "first_prompt_turn": first_idx if texts else None,
        "first_prompt_pasted": pasted_first,
        "automated_turns": dict(auto_turns),
        "prompts": [{"turn": i, "via": typed[i]["via"], "text": redact(truncate(x, 300), extra)}
                    for i, x in enumerate(texts[:40])],
        "prompt_word_counts": [len(x.split()) for x in texts],
        "task_type": task,
        "task_type_source": "manual" if sid in labels else "heuristic",
        "prompt_quality": prompt_quality(texts[first_idx]) if texts else None,
        "models": dict(fam_msgs),
        "model_ids": {k: sorted(v) for k, v in model_ids.items()},
        "primary_model": primary,
        "model_switches": switches[:10],
        "slash_model_commands": slash_models,
        "model_default_saved": default_saved,
        "effort": dict(effort),
        "primary_effort": effort.most_common(1)[0][0] if effort else None,
        "slash_effort_commands": slash_effort,
        "subagent_models": sub["models"],
        "subagents": sub,
        "tokens": {k: dict(v) for k, v in tokens.items()},
        "cost": cost,
        "peak_context_tokens": peak,
        "context": session_context(main, context_tokens, slash, big_results, tool_res_tokens,
                                   (sub or {}).get("runs", 0) if isinstance(sub, dict) else 0, strong),
        "tool_counts": dict(tool_counts.most_common(10)),
        "tool_calls": sum(tool_counts.values()),
        "tool_errors": len(err_ids),
        "files_edited": len(edited),
        "bash_write_commands": bash_writes,
        "plan_mode_used": plan_mode or exit_plan,
        "interruptions": interruptions,
        "rejected_tool_calls": rejected,
        "tool_denials": dict(denials),
        "rejected_tools": dict(denied_tools),
        "manual_approvals": dict(approvals),
        "manual_approval_commands": {redact(k, extra): v for k, v in approval_cmds.most_common(10)},
        "blocked_by_policy": dict(blocked),
        "permission_modes": dict(modes),
        "compactions": max(compact_boundaries, compact_summaries),
        "turn_seconds": {"turns": len(turn_ms), "median": round(sorted(turn_ms)[len(turn_ms) // 2] / 1000, 1),
                         "max": round(max(turn_ms) / 1000, 1)} if turn_ms else None,
        "api_errors": api_errors,
        "hooks": hooks,
        "outcome": outcome,
        "lines_changed": {"added": cs.get("totalLinesAdded"), "removed": cs.get("totalLinesRemoved")} if cs else None,
        "corrections": corrections[:12],
        "corrections_strong": strong,
        "corrections_weak": weak,
        "repeat_prompt_pairs": repeat_pairs,
        "friction_score": round(friction, 2),
        "friction_per_turn": round(friction / n_turns, 3) if n_turns else 0,
        "memory_shortcut_prompts": memory_shortcuts,
        "asks_to_update_agent_files": asks_update,
        "agent_file_edits": [
            {"path": a["path"], "tool": a["tool"], "count": a["count"], "ts": a["ts"].isoformat() if a["ts"] else None}
            for a in agent_edits.values()
        ],
        "skills_triggered": dict(skills),
        "subagents_used": dict(subagents),
        "slash_commands": dict(slash),
        "_stats": {"lines": total_lines, "bad_lines": bad_lines, "types": dict(types)},
    }


# ----------------------------------------------------------------------------- agent file inventory

def read_text(p: Path, cap: int = 300_000) -> str:
    try:
        return p.read_text(errors="replace")[:cap]
    except Exception:
        return ""


def agent_file_candidates(base: Path, scope: str):
    out = []
    singles = [("CLAUDE.md", "CLAUDE.md"), ("CLAUDE.local.md", "CLAUDE.md"), ("AGENTS.md", "AGENTS.md"),
               (".github/copilot-instructions.md", "copilot-instructions")]
    for rel, kind in singles:
        out.append((base / rel, kind, scope))
    dirs = [(".claude/rules", "rule", "*.md"), (".claude/commands", "command", "*.md"), (".claude/agents", "subagent", "*.md")]
    for rel, kind, pat in dirs:
        d = base / rel
        if d.is_dir():
            for f in sorted(d.rglob(pat)):
                out.append((f, kind, scope))
    sk = base / ".claude" / "skills"
    if sk.is_dir():
        for f in sorted(sk.glob("*/SKILL.md")):
            out.append((f, "skill", scope))
    return out


DEAD_REF_TOKEN = re.compile(r"`([^`\s]{3,120})`")
DOMAIN_RE = re.compile(r"^[\w\-]+\.(com|io|net|org|dev|se|app|cloud)$", re.I)


def dead_refs(text: str, bases) -> list:
    found, seen = [], set()
    for tok in DEAD_REF_TOKEN.findall(text):
        if tok in seen or tok.startswith(("http", "-", "$", "<", "~/.", "/dev", "/tmp", "/etc", "/usr", "/var")):
            continue
        if any(c in tok for c in "*{}|=()@:;,\\"):
            continue
        if re.fullmatch(r"/[a-z][\w\-]*", tok):  # a slash command such as /loop, not a path
            continue
        # only path-like tokens: bare file names are often outputs, branch names or code symbols
        if "/" not in tok or tok.endswith("/") or DOMAIN_RE.match(tok) or re.search(r"YYYY|%|^claude/", tok):
            continue
        if tok.startswith("."):  # .team/, .cache/ and similar are usually folders created at run time
            continue
        seen.add(tok)
        p = Path(tok).expanduser()
        if p.is_absolute():
            exists = p.exists()
        else:
            exists = any((b / tok).exists() for b in bases if b)
        if not exists:
            found.append(tok)
        if len(found) >= 15:
            break
    return found


def build_inventory(sessions, scoped=False, used=frozenset()):
    home = Path.home()
    cwd_set = {}
    for s in sessions:
        if s["_cwd"]:
            cwd_set.setdefault(s["_cwd"], []).append(s)
    cands = agent_file_candidates(home, "global")
    for cwd in cwd_set:
        base = Path(cwd)
        if base.is_dir():
            cands += agent_file_candidates(base, project_name(cwd))
    # global rules/commands/agents/skills sit under ~/.claude
    g = home / ".claude"
    if g.is_dir():
        cands = [(p, k, sc) for p, k, sc in cands if not (sc == "global" and p.parent == home)]
        for rel, kind, pat in [("CLAUDE.md", "CLAUDE.md", None)]:
            cands.append((g / rel, kind, "global"))
        for sub, kind in [("rules", "rule"), ("commands", "command"), ("agents", "subagent")]:
            d = g / sub
            if d.is_dir():
                cands += [(f, kind, "global") for f in sorted(d.rglob("*.md"))]
        if (g / "skills").is_dir():
            cands += [(f, "skill", "global") for f in sorted((g / "skills").glob("*/SKILL.md"))]

    files, seen = [], set()
    now = datetime.now(timezone.utc)
    for p, kind, scope in cands:
        try:
            rp = p.resolve()
        except Exception:
            continue
        if rp in seen or not rp.is_file():
            continue
        seen.add(rp)
        st = rp.stat()
        mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        text = read_text(rp)
        lines = text.count("\n") + 1 if text else 0
        proj_cwd = next((c for c in cwd_set if project_name(c) == scope), None)
        relevant = cwd_set.get(proj_cwd, []) if proj_cwd else [s for ss in cwd_set.values() for s in ss]
        after = sum(1 for s in relevant if s["_start"] and s["_start"] > mtime)
        sp = str(rp)
        linked = scope == "global" and not sp.startswith(str(home / ".claude")) and not sp.startswith(("/opt/", "/usr/"))
        managed = sp.startswith(("/opt/", "/usr/")) or "/plugins/" in sp or "node_modules" in sp
        hints = []
        if (lines > 200 or st.st_size > 12_000) and not managed:
            hints.append("bloated?")
        if lines < 8:
            hints.append("thin?")
        age = (now - mtime).days
        if age > 90 and len(relevant) >= 5:
            hints.append("untouched-90d+")
        bases = [rp.parent, Path(proj_cwd) if proj_cwd else None, home]
        refs = dead_refs(text, bases)
        entry = {
            "managed": managed, "linked_from_project": linked,
            "path": tilde(str(rp)), "kind": kind, "scope": "plugin" if managed else scope,
            "size_bytes": st.st_size, "lines": lines,
            "last_modified": mtime.isoformat(), "days_since_modified": age,
            "sessions_after_last_edit": after, "hints": hints,
            "possibly_dead_references": refs,
        }
        if kind == "skill":
            fm = re.match(r"---\s*\n(.*?)\n---", text, re.S)
            name = desc = None
            if fm:
                nm = re.search(r"^name:\s*(.+)$", fm.group(1), re.M)
                ds = re.search(r"^description:\s*(.+?)(?:\n\w+:|\Z)", fm.group(1), re.M | re.S)
                name = nm.group(1).strip().strip("'\"") if nm else None
                desc = re.sub(r"\s+", " ", ds.group(1)).strip().strip("'\"") if ds else None
            entry["skill_name"] = name or rp.parent.name
            entry["skill_description"] = truncate(redact(desc or ""), 300)
            entry["supporting_files"] = sum(1 for x in rp.parent.rglob("*") if x.is_file()) - 1
        entry["_text"] = text
        files.append(entry)
    if scoped:
        # With --project, global skills/agents/commands only matter if the sample used them;
        # CLAUDE.md, AGENTS.md and rules are always loaded, so they stay.
        def used_here(f):
            names = {Path(f["path"]).stem.lower(), str(f.get("skill_name", "")).lower()}
            return bool(names & used)
        files = [f for f in files if f["scope"] not in ("global", "plugin") or f["kind"] in ("CLAUDE.md", "AGENTS.md", "rule", "copilot-instructions")
                 or used_here(f)]
    return files


def project_roots(sessions, root):
    """Check on disk which agent files and memory each project root really has."""
    out, seen = [], set()
    for s in sessions:
        cwd = s["_cwd"]
        if not cwd or cwd in seen:
            continue
        seen.add(cwd)
        base = Path(cwd)
        mem = None
        for d in root.iterdir() if root.is_dir() else []:
            if d.is_dir() and d.name == re.sub(r"[^A-Za-z0-9]", "-", cwd):
                mem = d / "memory"
        out.append({
            "project": project_name(cwd), "cwd": tilde(cwd), "exists": base.is_dir(),
            "claude_md": (base / "CLAUDE.md").is_file(), "claude_local_md": (base / "CLAUDE.local.md").is_file(),
            "agents_md": (base / "AGENTS.md").is_file(),
            "rules": len(list((base / ".claude" / "rules").glob("*.md"))) if (base / ".claude" / "rules").is_dir() else 0,
            "agents": len(list((base / ".claude" / "agents").glob("*.md"))) if (base / ".claude" / "agents").is_dir() else 0,
            "skills": len(list((base / ".claude" / "skills").glob("*/SKILL.md"))) if (base / ".claude" / "skills").is_dir() else 0,
            "memory_files": len(list(mem.glob("*.md"))) if mem and mem.is_dir() else 0,
            "memory_note_names": sorted(x.name for x in mem.glob("*.md"))[:12] if mem and mem.is_dir() else [],
            "sessions": sum(1 for x in sessions if x["_cwd"] == cwd),
        })
    return out


def project_name(cwd: str) -> str:
    parts = [x for x in Path(cwd).parts if x not in ("/", "")]
    return "/".join(parts[-2:]) if parts else cwd


# ----------------------------------------------------------------------------- aggregation

def cost_drivers(s) -> list:
    """Plain-language reasons a session cost what it did (largest shares first)."""
    c = s["cost"]
    tot = c["total_usd"] or 0
    if tot <= 0:
        return []
    out = []
    if c["subagent_usd"] / tot >= 0.4:
        bt = s["subagents"]["by_type"]
        top = max(bt.items(), key=lambda kv: kv[1]["cost_usd"]) if bt else None
        out.append(f"subagents {round(100 * c['subagent_usd'] / tot)}% of the cost"
                   + (f", mostly {top[0]} ({top[1]['runs']} runs)" if top else ""))
    for part, label in (("cache_write", "cache writes (context written to the cache)"), ("output", "output tokens"),
                        ("cache_read", "cache reads (context re-read every turn)"), ("input", "uncached input")):
        share = c["parts"].get(part, 0) / tot
        if share >= 0.35:
            out.append(f"{label} {round(100 * share)}%")
    if s["peak_context_tokens"] >= 150_000:
        out.append(f"peak context {s['peak_context_tokens'] // 1000}k tokens")
    if s["compactions"]:
        out.append(f"{s['compactions']} context compaction(s)")
    if s["primary_effort"] in ("xhigh", "max"):
        out.append(f"effort {s['primary_effort']}")
    return out[:5]


def aggregate(sessions, inventory, prices):
    n = len(sessions)
    with_turns = [s for s in sessions if s["user_turns"] > 0]
    A = {}
    A["totals"] = {
        "sessions": n,
        "sessions_with_typed_prompts": len(with_turns),
        "short_prompt_share_pct": round(100 * sum(1 for s in with_turns for w in s["prompt_word_counts"] if w <= 3)
                                        / max(1, sum(len(s["prompt_word_counts"]) for s in with_turns)), 1),
        "avg_user_turns": round(sum(s["user_turns"] for s in with_turns) / len(with_turns), 1) if with_turns else 0,
        "median_user_turns": sorted(s["user_turns"] for s in with_turns)[len(with_turns) // 2] if with_turns else 0,
        "sessions_with_correction_or_interrupt": sum(1 for s in with_turns if s["corrections"] or s["interruptions"]),
        "pct_sessions_with_correction_or_interrupt": round(
            100 * sum(1 for s in with_turns if s["corrections"] or s["interruptions"]) / len(with_turns), 1) if with_turns else 0,
        "pct_sessions_with_strong_correction": round(
            100 * sum(1 for s in with_turns if s["corrections_strong"]) / len(with_turns), 1) if with_turns else 0,
        "total_interruptions": sum(s["interruptions"] for s in sessions),
        "total_rejected_tool_calls": sum(s["rejected_tool_calls"] for s in sessions),
        "total_tool_errors": sum(s["tool_errors"] for s in sessions),
        "sessions_using_plan_mode": sum(1 for s in sessions if s["plan_mode_used"]),
        "sessions_with_subagents": sum(1 for s in sessions if s["subagents"]["runs"]),
        "subagent_runs": sum(s["subagents"]["runs"] for s in sessions),
        "workflow_agent_runs": sum(s["subagents"]["workflow_runs"] for s in sessions),
        "active_hours": round(sum(s["active_min"] for s in sessions) / 60, 1),
    }

    # models: sessions and assistant_msgs count the main conversation; tokens and cost include subagents
    by_model = {}

    def bm(f):
        return by_model.setdefault(f, {"sessions": 0, "primary_in_sessions": 0, "assistant_msgs": 0, "subagent_msgs": 0,
                                       "tokens": Counter(), "ids": set(), "cost": 0.0})
    for s in sessions:
        for f, cnt in s["models"].items():
            d = bm(f)
            d["sessions"] += 1
            d["assistant_msgs"] += cnt
        for f, cnt in s["subagent_models"].items():
            bm(f)["subagent_msgs"] += cnt
        for f, ids in s["model_ids"].items():
            bm(f)["ids"].update(ids)
        if s["primary_model"]:
            bm(s["primary_model"])["primary_in_sessions"] += 1
        for f, tk in s["tokens"].items():
            bm(f)["tokens"].update(tk)
        for f, c in s["cost"]["by_model"].items():
            bm(f)["cost"] += c
    A["by_model"] = {}
    for f, d in by_model.items():
        tk = {k: d["tokens"].get(k, 0) for k in ("input", "output", "cache_read", "cache_write")}
        A["by_model"][f] = {"sessions": d["sessions"], "primary_in_sessions": d["primary_in_sessions"],
                            "assistant_msgs": d["assistant_msgs"], "subagent_msgs": d["subagent_msgs"],
                            "model_ids": sorted(d["ids"]), "tokens": tk,
                            "estimated_cost_usd": round(d["cost"], 2) if d["cost"] > 0 else (0.0 if not any(tk.values()) else None)}
    A["sessions_with_model_switch"] = sum(1 for s in sessions if s["model_switches"])
    A["sessions_with_slash_model"] = sum(1 for s in sessions if s["slash_model_commands"])
    sub = Counter()
    for s in sessions:
        sub.update(s["subagent_models"])
    A["subagent_model_msgs"] = dict(sub)
    A["sessions_with_slash_effort"] = sum(1 for s in sessions if s["slash_effort_commands"])

    # effort level per assistant message (main conversation and subagents)
    eff = {}
    for s in sessions:
        for e, n in s["effort"].items():
            eff.setdefault(e, {"main_msgs": 0, "subagent_msgs": 0, "primary_in_sessions": 0})["main_msgs"] += n
        for e, n in s["subagents"]["effort"].items():
            eff.setdefault(e, {"main_msgs": 0, "subagent_msgs": 0, "primary_in_sessions": 0})["subagent_msgs"] += n
        if s["primary_effort"]:
            eff[s["primary_effort"]]["primary_in_sessions"] += 1
    A["by_effort"] = dict(sorted(eff.items(), key=lambda kv: -(kv[1]["main_msgs"] + kv[1]["subagent_msgs"])))

    # estimated cost at list prices (see pricing.py): never the user's real bill
    parts = Counter()
    for s in sessions:
        parts.update(s["cost"]["parts"])
    total = sum(s["cost"]["total_usd"] for s in sessions)
    by_task_cost = defaultdict(lambda: {"sessions": 0, "usd": 0.0})
    for s in sessions:
        d = by_task_cost[s["task_type"]]
        d["sessions"] += 1
        d["usd"] += s["cost"]["total_usd"]
    by_sub = {}
    for s in sessions:
        for typ, d in s["subagents"]["by_type"].items():
            x = by_sub.setdefault(typ, {"runs": 0, "sessions": 0, "usd": 0.0, "models": Counter(), "effort": Counter(),
                                        "tool_errors": 0, "edit_calls": 0})
            x["runs"] += d["runs"]
            x["sessions"] += 1
            x["usd"] += d["cost_usd"]
            x["models"].update(d["models"])
            x["effort"].update(d["effort"])
            x["tool_errors"] += d["tool_errors"]
            x["edit_calls"] += d["edit_calls"]
    cc_sessions = [s for s in sessions if s["cost"]["claude_code_reported_usd"] is not None]
    cc = [s["cost"]["claude_code_reported_usd"] for s in cc_sessions]
    A["cost"] = {
        "total_usd": round(total, 2),
        "main_usd": round(sum(s["cost"]["main_usd"] for s in sessions), 2),
        "subagent_usd": round(sum(s["cost"]["subagent_usd"] for s in sessions), 2),
        "per_session_avg_usd": round(total / n, 2) if n else 0,
        "parts": {k: round(v, 2) for k, v in parts.most_common()},
        "by_task_type": {t: {"sessions": d["sessions"], "usd": round(d["usd"], 2), "per_session_usd": round(d["usd"] / d["sessions"], 2)}
                         for t, d in sorted(by_task_cost.items(), key=lambda kv: -kv[1]["usd"])},
        "by_subagent_type": {t: {"runs": d["runs"], "sessions": d["sessions"], "usd": round(d["usd"], 2),
                                 "per_run_usd": round(d["usd"] / d["runs"], 3) if d["runs"] else 0,
                                 "models": dict(d["models"]), "effort": dict(d["effort"]), "tool_errors": d["tool_errors"],
                                 "edit_calls": d["edit_calls"]}
                             for t, d in sorted(by_sub.items(), key=lambda kv: -kv[1]["usd"])},
        "top_sessions": [{"session_id": s["id"], "title": s.get("title"), "task_type": s["task_type"], "model": s["primary_model"],
                          "effort": s["primary_effort"], "usd": round(s["cost"]["total_usd"], 2),
                          "subagent_usd": round(s["cost"]["subagent_usd"], 2), "user_turns": s["user_turns"],
                          "drivers": cost_drivers(s)}
                         for s in sorted(sessions, key=lambda s: -s["cost"]["total_usd"])[:5] if s["cost"]["total_usd"] > 0],
        "workflows": [{"session_id": s["id"], **w} for s in sessions for w in s["subagents"]["workflows"]][:20],
        "unpriced_msgs": sum(s["cost"]["unpriced_msgs"] for s in sessions),
        # Cross-check only: Claude Code's own running figure (cost-state entries) for the sessions that have one,
        # next to this estimate for the same sessions. It may include background requests the transcript does not show.
        "claude_code_reported_usd": round(sum(cc), 2) if cc else None,
        "estimate_same_sessions_usd": round(sum(s["cost"]["total_usd"] for s in cc_sessions), 2) if cc else None,
        "sessions_with_claude_code_figure": len(cc),
        "custom_prices": bool(prices),
        "source": PRICING_URL, "prices_as_of": PRICES_AS_OF, "disclaimer": DISCLAIMER,
    }

    # permission friction: prompts the user had to answer, tool calls they rejected, calls a rule or classifier blocked
    perm = {"manual_approvals": Counter(), "approval_commands": Counter(), "rejected": Counter(), "denials": Counter(),
            "blocked_by_policy": Counter(), "modes": Counter()}
    for s in sessions:
        perm["manual_approvals"].update(s["manual_approvals"])
        perm["approval_commands"].update(s["manual_approval_commands"])
        perm["rejected"].update(s["rejected_tools"])
        perm["denials"].update(s["tool_denials"])
        perm["blocked_by_policy"].update(s["blocked_by_policy"])
        perm["modes"].update({m: 1 for m in s["permission_modes"]})
    A["permissions"] = {k: dict(v.most_common(15)) for k, v in perm.items()}
    A["permissions"]["sessions_with_manual_approval"] = sum(1 for s in sessions if s["manual_approvals"])
    A["permissions"]["sessions_with_rejection"] = sum(1 for s in sessions if s["rejected_tool_calls"])
    A["permissions"]["note"] = ("modes counts sessions per permission mode. Interactive answers (AskUserQuestion, "
                                "plan approval) are not counted as approvals.")
    A["hooks_activity"] = {"stop_hook_runs": sum(s["hooks"]["runs"] for s in sessions),
                           "hook_errors": sum(s["hooks"]["errors"] for s in sessions),
                           "stops_blocked_by_hook": sum(s["hooks"]["blocked_stop"] for s in sessions),
                           "sessions_with_stop_hooks": sum(1 for s in sessions if s["hooks"]["runs"])}

    # how sessions ended, per task type
    out_t = defaultdict(lambda: {"sessions": 0, "with_edits": 0, "verified_finish": 0, "committed": 0, "pushed": 0,
                                 "with_pr": 0, "checks_run": 0})
    for s in with_turns:
        o, d = s["outcome"], out_t[s["task_type"]]
        d["sessions"] += 1
        d["with_edits"] += o["edited"]
        d["verified_finish"] += bool(o["verified_finish"])
        d["committed"] += o["committed"]
        d["pushed"] += o["pushed"]
        d["with_pr"] += o["prs"] > 0
        d["checks_run"] += o["checks_run"] > 0
    edited = [s for s in with_turns if s["outcome"]["edited"]]
    A["outcomes"] = {
        "by_task_type": dict(sorted(out_t.items(), key=lambda kv: -kv[1]["sessions"])),
        "sessions_with_edits": len(edited),
        "verified_finish_pct": round(100 * sum(1 for s in edited if s["outcome"]["verified_finish"]) / len(edited), 1) if edited else None,
        "unverified_sessions": [s["id"] for s in edited if not s["outcome"]["verified_finish"]][:20],
        "note": ("verified_finish: a test, build, lint or type-check command (main session or subagent) succeeded after the last "
                 "file edit. A heuristic: checks run another way (a hook, CI, by hand) are not seen."),
    }
    A["context"] = {"compactions": sum(s["compactions"] for s in sessions),
                    "sessions_with_compaction": sum(1 for s in sessions if s["compactions"]),
                    "api_errors": sum(s["api_errors"] for s in sessions),
                    "max_peak_context_tokens": max((s["peak_context_tokens"] for s in sessions), default=0)}

    # task types
    by_task = defaultdict(list)
    for s in with_turns:
        by_task[s["task_type"]].append(s)
    A["by_task_type"] = {
        t: {"sessions": len(v), "avg_user_turns": round(sum(x["user_turns"] for x in v) / len(v), 1),
            "avg_friction_per_turn": round(sum(x["friction_per_turn"] for x in v) / len(v), 3),
            "models": dict(Counter(x["primary_model"] or "unknown" for x in v)),
            "efforts": dict(Counter(x["primary_effort"] or "unknown" for x in v))}
        for t, v in sorted(by_task.items(), key=lambda kv: -len(kv[1]))
    }
    matrix = {}
    for t, v in by_task.items():
        cell = defaultdict(list)
        for x in v:
            cell[x["primary_model"] or "unknown"].append(x)
        matrix[t] = {f: {"sessions": len(xs), "avg_user_turns": round(sum(y["user_turns"] for y in xs) / len(xs), 1),
                         "avg_friction_per_turn": round(sum(y["friction_per_turn"] for y in xs) / len(xs), 3),
                         "corrections": sum(len(y["corrections"]) for y in xs),
                         "interruptions": sum(y["interruptions"] for y in xs),
                         "rejected_tool_calls": sum(y["rejected_tool_calls"] for y in xs),
                         "tool_errors": sum(y["tool_errors"] for y in xs),
                         "efforts": dict(Counter(y["primary_effort"] or "unknown" for y in xs)),
                         "avg_est_cost_usd": round(sum(y["cost"]["total_usd"] for y in xs) / len(xs), 2)}
                     for f, xs in cell.items()}
    A["task_model_matrix"] = matrix

    # mismatch candidates
    mism = []
    for s in with_turns:
        tier = TIER.get(s["primary_model"] or "", None)
        if tier is None:
            continue
        writes = s["files_edited"] + s["bash_write_commands"]
        trivial = (s["user_turns"] <= 3 and s["tool_calls"] <= 6 and not s["corrections"]
                   and writes <= 1 and not s["interruptions"] and s["subagents"]["runs"] == 0)
        hard = s["user_turns"] >= 6 and s["friction_per_turn"] >= 0.3
        eff = f", effort {s['primary_effort']}" if s["primary_effort"] else ""
        if tier >= 3 and trivial:
            mism.append({"session_id": s["id"], "task_type": s["task_type"], "model": s["primary_model"],
                         "effort": s["primary_effort"], "kind": "heavy-for-trivial?",
                         "evidence": f"{s['user_turns']} turns, {s['tool_calls']} tool calls, {s['files_edited']} files edited + {s['bash_write_commands']} Bash write commands, no corrections{eff}, est. ${s['cost']['total_usd']}"})
        elif tier == 2 and trivial and s["primary_effort"] in ("xhigh", "max"):
            mism.append({"session_id": s["id"], "task_type": s["task_type"], "model": s["primary_model"],
                         "effort": s["primary_effort"], "kind": "high-effort-for-trivial?",
                         "evidence": f"{s['user_turns']} turns, {s['tool_calls']} tool calls, {writes} writes{eff}"})
        elif tier >= 3 and s["user_turns"] <= 3 and s["tool_calls"] <= 15 and not s["corrections"] and not s["interruptions"]:
            runs = s["subagents"]["runs"]
            mism.append({"session_id": s["id"], "task_type": s["task_type"], "model": s["primary_model"],
                         "effort": s["primary_effort"], "kind": "short-on-heavy?",
                         "evidence": f"{s['user_turns']} turns, {s['tool_calls']} tool calls, {writes} writes{eff}"
                                     + (f", {runs} subagent runs" if runs else "")
                                     + "; read it to judge whether it needed deep reasoning"})
        elif tier == 1 and (hard or s["user_turns"] >= 8):
            mism.append({"session_id": s["id"], "task_type": s["task_type"], "model": s["primary_model"],
                         "effort": s["primary_effort"], "kind": "light-for-hard?",
                         "evidence": f"{s['user_turns']} turns, friction/turn {s['friction_per_turn']}{eff}"})
        elif tier == 2 and s["task_type"] in ("refactor", "bugfix", "infra-ci") and hard:
            mism.append({"session_id": s["id"], "task_type": s["task_type"], "model": s["primary_model"],
                         "effort": s["primary_effort"], "kind": "maybe-too-light-for-hard?",
                         "evidence": f"{s['user_turns']} turns, friction/turn {s['friction_per_turn']}, {s['corrections_strong']} strong corrections{eff}"})
    A["model_mismatch_candidates"] = mism[:25]

    # prompt quality (first prompts)
    pq = [s["prompt_quality"] for s in with_turns if s["prompt_quality"]]
    keys = ["has_goal_why", "has_scope", "has_context_pointer", "has_done_criteria", "asks_plan_first"]
    A["prompt_quality_heuristic"] = {
        "first_prompts_analyzed": len(pq),
        "median_first_prompt_words": sorted(p["words"] for p in pq)[len(pq) // 2] if pq else 0,
        "pct": {k: round(100 * sum(1 for p in pq if p[k]) / len(pq), 1) if pq else 0 for k in keys},
        "note": "Regex heuristics on the FIRST prompt of each session. Treat as a rough signal only.",
    }

    # best / worst
    ranked = sorted([s for s in with_turns if s["user_turns"] >= 3], key=lambda s: (s["friction_per_turn"], -s["user_turns"]))
    pick = lambda s: {"session_id": s["id"], "title": s.get("title"), "task_type": s["task_type"], "model": s["primary_model"],
                      "user_turns": s["user_turns"], "friction_per_turn": s["friction_per_turn"],
                      "first_prompt": s["first_prompt"]}
    by_t = defaultdict(list)
    for s in ranked:
        by_t[s["task_type"]].append(s)
    A["best_worst_by_task"] = {t: {"best": pick(v[0]), "worst": pick(v[-1])} for t, v in by_t.items() if len(v) >= 2}
    A["best_session_candidates"] = [pick(s) for s in ranked[:3]]
    A["worst_session_candidates"] = [pick(s) for s in ranked[::-1][:3]]

    # agent file edits: one event per (session, file, day), tools merged, repeats counted
    merged = {}
    for s_ in sessions:
        for a in s_["agent_file_edits"]:
            date = (a["ts"] or s_["start"] or "")[:10]
            k = (s_["id"], a["path"], date)
            ev = merged.setdefault(k, {"date": date, "project": project_name(s_["_cwd"]) if s_["_cwd"] else "?",
                                       "path": a["path"], "tools": [], "calls": 0, "session_id": s_["id"]})
            if a["tool"] not in ev["tools"]:
                ev["tools"].append(a["tool"])
            ev["calls"] += a["count"]
    events = sorted(merged.values(), key=lambda x: x["date"])
    for ev in events:
        ev["tool"] = "+".join(ev.pop("tools"))
        ev["on_disk"] = Path(os.path.expanduser(ev["path"])).is_file()  # False: renamed or deleted since
    A["agent_file_edit_events"] = events[:200]
    A["agent_file_edit_count"] = sum(e["calls"] for e in events)
    A["agent_files_touched"] = len({e["path"] for e in events})
    A["sessions_with_agent_file_edit"] = sum(1 for s in sessions if s["agent_file_edits"])
    A["sessions_with_corrections_but_no_agent_file_edit"] = sum(
        1 for s in sessions if s["corrections"] and not s["agent_file_edits"])
    A["prompts_asking_to_update_agent_files"] = sum(s["asks_to_update_agent_files"] for s in sessions)
    A["memory_shortcut_prompts"] = sum(s["memory_shortcut_prompts"] for s in sessions)

    # skills
    trig = Counter()
    for s in sessions:
        trig.update(s["skills_triggered"])
    slash_all = Counter()
    for s_ in sessions:
        slash_all.update(s_["slash_commands"])
    norm = {k.split(":")[-1].lower(): v for k, v in trig.items()}
    for k, v in slash_all.items():  # /skill-name typed by the user also triggers the skill
        norm[k.split(":")[-1].lower()] = norm.get(k.split(":")[-1].lower(), 0) + v
    skills_inv = [f for f in inventory if f["kind"] == "skill"]
    A["skills_triggered"] = dict(trig.most_common())
    A["skills_invoked_by_slash"] = {k: v for k, v in slash_all.items() if k not in BUILTIN_CMDS}
    A["automated_turns_excluded"] = dict(sum((Counter(s_["automated_turns"]) for s_ in sessions), Counter()))
    A["skills_never_triggered_in_sample"] = [
        {"name": f["skill_name"], "path": f["path"], "description": f.get("skill_description")}
        for f in skills_inv if f["skill_name"].lower() not in norm and not f.get("managed")
        and not f.get("linked_from_project") and f["skill_name"].lower() != "prompt-insights"]
    A["subagents_used"] = dict(sum((Counter(s["subagents_used"]) for s in sessions), Counter()))

    # repeated corrections across sessions
    pool = []
    for s in sessions:
        for c in s["corrections"]:
            tk = content_tokens(c["excerpt"])
            if len(tk) >= 3:
                pool.append({"sid": s["id"], "project": project_name(s["_cwd"]) if s["_cwd"] else "?",
                             "excerpt": c["excerpt"], "tk": tk})
    clusters = []
    for p in pool:
        for c in clusters:
            if jaccard(p["tk"], c["tk"]) >= 0.5:
                c["items"].append(p)
                c["tk"] |= p["tk"]
                break
        else:
            clusters.append({"tk": set(p["tk"]), "items": [p]})
    rep = []
    for c in clusters:
        sids = sorted({i["sid"] for i in c["items"]})
        if len(sids) < 2:
            continue
        top = {w for w, _ in Counter(w for i in c["items"] for w in i["tk"]).most_common(6)}
        covered = [f["path"] for f in inventory
                   if top and len(top & content_tokens(f["_text"])) / len(top) >= 0.6]
        rep.append({"representative": c["items"][0]["excerpt"], "occurrences": len(c["items"]),
                    "sessions": sids, "projects": sorted({i["project"] for i in c["items"]}),
                    "keywords": sorted(top), "possibly_covered_by": covered[:3]})
    rep.sort(key=lambda r: -r["occurrences"])
    A["repeated_corrections"] = rep[:10]

    # instructions the user repeats in several sessions (standing rules, model assignments, re-pasted briefs)
    sent_pool = []
    for s in sessions:
        for p in s["prompts"]:
            for sent in re.split(r"(?<=[.!?])\s+|\n+", p["text"]):
                tk = content_tokens(sent)
                if 5 <= len(tk) <= 40 and len(sent) >= 30:
                    sent_pool.append({"sid": s["id"], "text": sent.strip()[:200], "tk": tk})
    sent_pool = sent_pool[:2500]
    groups = []
    for it in sent_pool:
        for g in groups:
            if jaccard(it["tk"], g["tk"]) >= 0.6:
                g["items"].append(it)
                break
        else:
            groups.append({"tk": set(it["tk"]), "items": [it]})
    ri = []
    for g in groups:
        sids = sorted({i["sid"] for i in g["items"]})
        if len(sids) >= 2:
            top = {w for w, _ in Counter(w for i in g["items"] for w in i["tk"]).most_common(6)}
            covered = [f["path"] for f in inventory if top and len(top & content_tokens(f["_text"])) / len(top) >= 0.6]
            ri.append({"example": g["items"][0]["text"], "sessions": sids, "occurrences": len(g["items"]),
                       "possibly_covered_by": covered[:3]})
    ri.sort(key=lambda r: (-len(r["sessions"]), -r["occurrences"]))
    A["repeated_instructions"] = ri[:10]
    return A


# ----------------------------------------------------------------------------- modes

def mode_schema(files, extra):
    shapes = defaultdict(Counter)
    block_types = Counter()
    msg_keys = defaultdict(Counter)
    usage_keys = Counter()
    subtypes = Counter()
    for f in files[:3]:
        for e in iter_entries(f):
            if e is None:
                shapes["<unparseable>"]["-"] += 1
                continue
            t = e.get("type")
            shapes[t].update(e.keys())
            if t == "system" and e.get("subtype"):
                subtypes[e["subtype"]] += 1
            m = e.get("message")
            if isinstance(m, dict):
                msg_keys[t].update(m.keys())
                if isinstance(m.get("usage"), dict):
                    usage_keys.update(m["usage"].keys())
                if isinstance(m.get("content"), list):
                    for b in m["content"]:
                        if isinstance(b, dict):
                            block_types[(t, b.get("type"))] += 1
    print(f"Inspected {min(3, len(files))} most recent session file(s). Keys only, no values.\n")
    for t, c in shapes.items():
        print(f"entry type={t!r}: keys={sorted(c)}")
    for t, c in msg_keys.items():
        print(f"  message keys for type={t!r}: {sorted(c)}")
    print(f"\ncontent block types (entry type, block type): {dict(block_types)}")
    print(f"usage keys: {sorted(usage_keys)}")
    needed = {"user entries": "user" in shapes, "assistant entries": "assistant" in shapes,
              "message.model": any(k == "model" for k in msg_keys.get("assistant", {})),
              "message.usage": bool(usage_keys), "timestamp": any("timestamp" in c for c in shapes.values())}
    print("\nExpected fields present:", needed)
    # Used when present; the analysis degrades (and says so) without them.
    optional = {
        "user.promptSource (typed vs automated prompts)": "promptSource" in shapes.get("user", {}),
        "assistant.effort (effort level)": "effort" in shapes.get("assistant", {}),
        "usage.cache_creation (5m/1h cache-write split for pricing)": "cache_creation" in usage_keys,
        "user.permissionDecision (manual approvals)": "permissionDecision" in shapes.get("user", {}),
        "user.toolDenialKind (rejected tool calls)": "toolDenialKind" in shapes.get("user", {}),
        "cost-state entries (Claude Code's own cost figure, cross-check only)": "cost-state" in shapes,
        "ai-title entries (session titles)": "ai-title" in shapes,
        "pr-link entries (pull requests)": "pr-link" in shapes,
        "system turn_duration / compact_boundary": bool(subtypes.get("turn_duration") or subtypes.get("compact_boundary")),
        "<session-id>/subagents/ folders (subagent transcripts)": any(f.with_suffix("").joinpath("subagents").is_dir() for f in files[:20]),
    }
    print("Optional fields seen (in these files):")
    for k, v in optional.items():
        print(f"  {'yes' if v else 'no '}  {k}")
    return 0 if all(needed.values()) else 2


def mode_show(path: Path, extra, max_chars: int, max_lines: int, turns):
    n_turn, lines = -1, 0
    for e in iter_entries(path):
        if not e:
            continue
        t = e.get("type")
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        out = None
        if t == "user" and not e.get("isSidechain") and not e.get("isMeta"):
            kind, text, extra_ = classify_user(e, msg)
            if kind == "empty":
                continue
            if kind == "interrupt":
                out = "[interrupted by user]"
            elif kind == "auto":
                if turns and not (turns[0] <= n_turn <= turns[1]):
                    continue
                out = f"   (automated: {extra_}) {redact(truncate(text, 90), extra)}"
            else:
                if kind == "command":
                    name, args = extra_
                    if name in BUILTIN_CMDS or not args:
                        continue
                    text, via = args, f" /{name}"
                else:
                    via = ""
                text = clean_prompt(text)
                if not text:
                    continue
                n_turn += 1
                if turns and not (turns[0] <= n_turn <= turns[1]):
                    continue
                out = f"[turn {n_turn}]{via} YOU: {redact(truncate(text, max_chars), extra)}"
        elif t == "assistant" and not e.get("isSidechain"):
            if turns and not (turns[0] <= n_turn <= turns[1]):
                continue
            parts = []
            content = msg.get("content") if isinstance(msg.get("content"), list) else []
            txt = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
            if txt.strip():
                parts.append(redact(truncate(txt, max_chars // 2), extra))
            tl = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    arg = inp.get("file_path") or inp.get("command") or inp.get("skill") or inp.get("pattern") or ""
                    tl.append(f"{b.get('name')}({redact(truncate(arg, 70), extra)})")
            if tl:
                parts.append("tools: " + ", ".join(tl))
            if parts:
                out = f"   CLAUDE[{family(msg.get('model'))}]: " + " | ".join(parts)
        if out:
            print(out)
            lines += 1
            if lines >= max_lines:
                print(f"... truncated at {max_lines} lines (use --max-lines or --turns a:b)")
                break
    return 0


MAX_SINCE_DAYS = 7


def days_arg(v):
    n = int(v)
    if not 1 <= n <= MAX_SINCE_DAYS:
        raise argparse.ArgumentTypeError(
            f"must be between 1 and {MAX_SINCE_DAYS}; for a longer period use --limit N (number of sessions, 0 = all)")
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="~/.claude/projects", help="folder with one subfolder per project")
    ap.add_argument("--limit", type=int, default=20, help="most recent sessions to analyze (0 = all)")
    ap.add_argument("--project", help="only projects whose folder name or cwd contains this text")
    ap.add_argument("--since-days", type=days_arg, metavar="N",
                    help=f"only sessions modified in the last N days (1 to {MAX_SINCE_DAYS}); combine with --limit to cap the count")
    ap.add_argument("--out", default=f"{DEFAULT_DIR}/summary.json",
                    help="summary file; the default folder ./prompt-insights/ is created and git-ignored")
    ap.add_argument("--history-dir", metavar="DIR",
                    help=f"where report snapshots are kept for the follow-up between runs; default: ${ENV_VAR} or "
                         "~/.claude/prompt-insights/history (one folder for all projects)")
    ap.add_argument("--labels", help="JSON file {session_id: task_type} to override heuristic task types")
    ap.add_argument("--prices", help="optional JSON {model-substring: {input, output, cache_read, cache_write, cache_write_1h}} "
                                     "in USD per 1M tokens; overrides the built-in list prices (pricing.py) for matching models")
    ap.add_argument("--no-subagents", action="store_true",
                    help="skip <session-id>/subagents/ transcripts (faster; subagent models, tokens and cost are then missing)")
    ap.add_argument("--extra-redact", action="append", default=[], help="extra regex to redact (repeatable)")
    ap.add_argument("--schema", action="store_true", help="print observed JSONL structure and exit")
    ap.add_argument("--show", metavar="SESSION_ID", help="print redacted transcript of a session (id or unique prefix)")
    ap.add_argument("--turns", help="with --show: range a:b of typed-prompt indexes")
    ap.add_argument("--max-chars", type=int, default=400)
    ap.add_argument("--max-lines", type=int, default=400)
    ap.add_argument("--exclude-session", action="append", default=[], metavar="ID",
                    help="skip a session by id or id prefix (repeatable), e.g. earlier look-alike analysis runs")
    ap.add_argument("--include-self", action="store_true", help="keep sessions that ran the prompt-insights skill")
    ap.add_argument("--force", action="store_true", help="write output even if sanity checks fail")
    a = ap.parse_args()

    root = Path(a.root).expanduser()
    if not root.is_dir():
        print(f"ERROR: {root} does not exist or is not a directory.", file=sys.stderr)
        return 1
    extra = compile_extra(a.extra_redact)

    all_files, per_project = [], Counter()
    for proj in sorted(root.iterdir()):
        if not proj.is_dir():
            continue
        for f in proj.glob("*.jsonl"):
            if f.name.startswith("agent-"):
                continue
            all_files.append((f.stat().st_mtime, proj.name, f))
            per_project[proj.name] += 1
    if not all_files:
        print(f"ERROR: no <session>.jsonl files found under {root}/*/", file=sys.stderr)
        return 1
    all_files.sort(reverse=True)

    if a.show:
        hit = [f for _, _, f in all_files if f.stem.startswith(a.show)]
        if len(hit) != 1:
            print(f"ERROR: {len(hit)} sessions match prefix {a.show!r}; be more specific.", file=sys.stderr)
            return 1
        turns = tuple(int(x) for x in a.turns.split(":")) if a.turns else None
        return mode_show(hit[0], extra, a.max_chars, a.max_lines, turns)

    sel = all_files
    if a.project:
        sel = [x for x in sel if a.project.lower() in x[1].lower()]
    if a.since_days:
        cutoff = time.time() - a.since_days * 86400
        sel = [x for x in sel if x[0] >= cutoff]
    sel_total = list(sel)
    if not sel:
        print("ERROR: filters matched no sessions.", file=sys.stderr)
        return 1

    if a.schema:
        return mode_schema([f for _, _, f in sel], extra)

    labels = {k: v for k, v in json.loads(Path(a.labels).read_text()).items() if not k.startswith("_")} if a.labels else {}
    prices = json.loads(Path(a.prices).read_text()) if a.prices else {}

    def is_self_run(s):
        names = list(s["skills_triggered"]) + list(s["slash_commands"])
        early = " ".join(p["text"] for p in s["prompts"][:2]).lower()
        return any("prompt-insights" in k for k in names) or "prompt insights" in early or "prompt-insights" in early

    # Parse newest first and apply --limit AFTER dropping this skill's own runs and --exclude-session
    # ids, so that --limit 15 really gives 15 sessions whenever that many exist.
    sessions, self_runs, skipped = [], [], 0
    for _, _, f in sel:
        if a.limit and len(sessions) >= a.limit:
            break
        if any(f.stem.startswith(x) for x in a.exclude_session):
            skipped += 1
            continue
        s_ = parse_session(f, extra, labels, prices, with_subagents=not a.no_subagents)
        if is_self_run(s_) and not a.include_self:
            self_runs.append(s_)
            continue
        sessions.append(s_)
    if not sessions:
        print("ERROR: no sessions left after exclusions; use --include-self or fewer --exclude-session.", file=sys.stderr)
        return 1

    # sanity checks: fail loudly instead of reporting zeros
    lines = sum(s["_stats"]["lines"] for s in sessions)
    bad = sum(s["_stats"]["bad_lines"] for s in sessions)
    typed = sum(s["user_turns"] for s in sessions)
    asst = sum(s["assistant_msgs"] for s in sessions)
    problems = []
    if lines and bad / lines > 0.2:
        problems.append(f"{bad}/{lines} lines failed to parse as JSON")
    if typed == 0:
        problems.append("no typed user prompts were recognised (format may have changed)")
    if asst == 0:
        problems.append("no assistant messages with a model were recognised (format may have changed)")
    if problems and not a.force:
        print("ERROR: schema sanity check failed:\n  - " + "\n  - ".join(problems) +
              "\nRun with --schema to inspect the structure, adjust the parser, or pass --force.", file=sys.stderr)
        return 2

    used = {k.split(":")[-1].lower() for s in sessions for k in
            list(s["skills_triggered"]) + list(s["subagents_used"]) + list(s["slash_commands"])}
    inventory = build_inventory(sessions, scoped=bool(a.project), used=used)
    roots_info = project_roots(sessions, root)
    agg = aggregate(sessions, inventory, prices)
    cwds = sorted({s["_cwd"] for s in sessions if s["_cwd"]})
    settings = scan_settings(cwds, project_name, extra)

    # compare with the previous report, if one was saved in history/
    out = Path(a.out)
    newest = max((s["_start"] for s in sessions if s["_start"]), default=None)
    history_dir = resolve_history_dir(a.history_dir)
    hist_note = ensure_output_dir(history_dir)
    migrated = migrate_legacy(out.parent, history_dir)
    prev = find_previous(history_dir, newest, a.project)
    fu = None
    if prev:
        hooks_text = "\n".join(h["command"] for st in settings for h in st.get("hooks", []))
        fu = followup(prev, sessions, [(f["path"], f["_text"]) for f in inventory], hooks_text)

    warnings = [f"sanity: {p}" for p in problems]
    if not any(any(t for t in s["tokens"].values()) for s in sessions):
        warnings.append("no token usage found; model comparison relies on friction signals only")
    unpriced = agg["cost"]["unpriced_msgs"]
    if unpriced:
        ids = sorted({i for s in sessions for f, v in s["model_ids"].items() if not s["cost"]["by_model"].get(f) for i in v})
        warnings.append(f"{unpriced} assistant message(s) have no list price (models: {', '.join(ids[:6]) or '?'}); "
                        "their cost is left out of the estimate. Add them with --prices.")
    if a.no_subagents:
        warnings.append("--no-subagents: subagent and workflow transcripts were not read; their models, tokens and cost are missing")
    unknown_types = Counter()
    for s in sessions:
        for k, v in s["_stats"]["types"].items():
            if k not in KNOWN_IGNORED_TYPES:
                unknown_types[k] += v
    if unknown_types:
        warnings.append(f"unrecognised entry types (ignored): {dict(unknown_types)}")
    if self_runs:
        warnings.append(f"{len(self_runs)} session(s) that ran prompt-insights itself were excluded (use --include-self to keep them)")
    if skipped:
        warnings.append(f"{skipped} session(s) skipped by --exclude-session")
    heuristic_labels = [s["id"] for s in sessions if s["task_type_source"] == "heuristic"]
    if heuristic_labels:
        warnings.append(f"task types are heuristic for {len(heuristic_labels)} of {len(sessions)} sessions: review labels.todo.json, "
                        "write labels.json and re-run with --labels so the model/task matrix is trustworthy")

    if fu and fu["sessions_since"] == 0:
        warnings.append("follow-up: no session in this sample started after the previous report; the 'after' column is empty")

    starts = [s["start"] for s in sessions if s["start"]]
    for s in sessions:
        s["project"] = project_name(s["_cwd"]) if s["_cwd"] else "?"
        for k in ("_cwd", "_start", "_stats"):
            s.pop(k, None)
    for f in inventory:
        f.pop("_text", None)
    ctx_rows = [s["context"] for s in sessions if s.get("context")]
    agg["context"]["flags"] = context_flags(sessions)
    agg["context"]["sessions_measured"] = len(ctx_rows)
    agg["context"]["median_peak_tokens"] = sorted(c["peak_tokens"] for c in ctx_rows)[len(ctx_rows) // 2] if ctx_rows else None
    agg["context"]["cold_restarts_total"] = sum(c["cold_restart_count"] for c in ctx_rows)
    agg["context"]["note"] = ("Context sizes are MEASURED from each request's usage fields (input + cache read + cache write). Thresholds are "
                              "this skill's rules of thumb, not Anthropic limits. Cache lifetime is read from the cache-write type in the "
                              "transcript and assumed to be 1 hour (subscription) when absent; on an API key or cloud provider it is "
                              "5 minutes by default, so cold-cache gaps would be more frequent than shown here.")

    summary = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "root": tilde(str(root)),
            "sessions_available_total": len(all_files),
            "sessions_available_per_project": dict(per_project.most_common(15)),
            "sessions_analyzed": len(sessions),
            "date_range": [min(starts)[:10], max(starts)[:10]] if starts else None,
            "filters": {"project": a.project, "since_days": a.since_days, "limit": a.limit},
            "sessions_in_filter": len(sel_total),
            "sessions_self_excluded": len(self_runs),
            "max_since_days": MAX_SINCE_DAYS,
            "history_dir": tilde(str(history_dir)),
            "task_labels": {"manual": sum(1 for s in sessions if s["task_type_source"] == "manual"),
                            "heuristic": sum(1 for s in sessions if s["task_type_source"] == "heuristic")},
            "claude_code_versions": dict(Counter(s["claude_code_version"] for s in sessions if s["claude_code_version"])),
            "warnings": warnings,
            "measured": ["session/turn counts", "timestamps and active time", "models per assistant message",
                         "token usage (deduplicated by message id, main session and subagents)", "effort level per message",
                         "subagent and workflow-agent runs, models and tokens", "tool calls and errors", "agent-file edits via tool calls",
                         "skill and subagent invocations", "permission approvals and rejected tool calls", "context compactions",
                         "hooks and permission rules in settings files", "file mtimes and sizes"],
            "estimated": [f"cost: measured tokens x Claude API list prices from {PRICING_URL} (as of {PRICES_AS_OF})"
                          + ("; --prices overrides applied" if prices else "") + ". Not the user's actual cost."],
            "heuristic": ["task_type", "corrections (regex)", "repeat_prompt_pairs", "prompt_quality flags",
                          "model mismatch candidates", "dead-reference candidates", "repeated-correction clusters",
                          "verified finish (check command after the last edit)", "cost drivers"],
            "not_covered": ("Plugin-provided skills and hooks, managed (organisation) settings, and non-typed context are not "
                            "analyzed. Subagent transcripts are read" + (" (skipped this run)." if a.no_subagents else ".")),
        },
        "aggregates": agg,
        "followup": fu,
        "project_roots": roots_info,
        "agent_files": inventory,
        "settings": settings,
        "sessions": sessions,
    }
    guard = ensure_output_dir(out.parent)
    out.write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")

    todo = {"_instructions": "Fix each value to the real task type, save as labels.json, then re-run with --labels labels.json. "
                             "Judge from the first prompt, not from the heuristic.",
            "_allowed": TASK_TYPES}
    for s in sessions:
        todo[s["id"]] = s["task_type"]
    (out.parent / "labels.todo.json").write_text(json.dumps(todo, indent=1), encoding="utf-8")

    t = agg["totals"]
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB) | {guard}")
    pool = f"{len(sel_total)} in the filtered set" if (a.project or a.since_days) else f"{len(all_files)} available"
    print(f"Sessions analyzed: {t['sessions']} of {pool} | avg user turns: {t['avg_user_turns']} | "
          f"with corrections/interrupts: {t['pct_sessions_with_correction_or_interrupt']}%")
    print("Models (sessions): " + ", ".join(f"{k}={v['sessions']}" for k, v in agg["by_model"].items() if v["sessions"]))
    print(f"Subagent runs: {t['subagent_runs']} ({t['workflow_agent_runs']} in workflows) in {t['sessions_with_subagents']} sessions")
    c = agg["cost"]
    print(f"Estimated cost at API list prices: ${c['total_usd']} (subagents ${c['subagent_usd']}). "
          "An estimate from the public price list, not your actual cost.")
    print(f"Agent-file edit events: {agg['agent_file_edit_count']} | agent files found: {len(inventory)} | settings files: {len(settings)}")
    print(f"History folder: {tilde(str(history_dir))} ({hist_note})"
          + (f"; copied {migrated} snapshot(s) from {out.parent / 'history'}" if migrated else ""))
    if fu:
        print(f"Follow-up: previous report {fu['previous_report']['generated_at']}, {fu['sessions_since']} session(s) since")
    for w in warnings:
        print("WARNING:", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
