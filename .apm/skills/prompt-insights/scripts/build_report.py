#!/usr/bin/env python3
"""Render summary.json (measured data) + insights.json (model judgment) into one
self-contained, tabbed HTML report. Standard library only, no network, no external assets.

Usage:
  python3 build_report.py --summary out/summary.json --insights out/insights.json \
      --out out/claude-prompt-insights.html

All text is HTML-escaped and re-redacted before it is written. The build fails if the
resulting page would load anything from the network. Without JavaScript every tab is shown
one after the other, so the file still reads correctly in a viewer that blocks scripts.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import textwrap
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the installed skill folder free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
from outdir import DEFAULT_DIR, ensure_output_dir  # noqa: E402
from redact import compile_extra, redact  # noqa: E402

LIGHT = ("--bg:#fafaf9;--fg:#1c1917;--muted:#6b6560;--card:#fff;--line:#e7e5e4;--accent:#2563eb;--accent-bg:#eff4ff;--good:#15803d;"
         "--bad-rgb:220 70 60;--bad:#b91c1c;--warn:#b45309;--code:#f5f5f4;--win:#fff8e6;--win-line:#e9b949")
DARK = ("--bg:#141413;--fg:#ecebe8;--muted:#9a958e;--card:#1e1d1b;--line:#33312e;--accent:#6ea0ff;--accent-bg:#1b2436;"
        "--good:#4ade80;--bad-rgb:220 70 60;--bad:#f87171;--warn:#fbbf24;--code:#262522;--win:#2a2415;--win-line:#a07d1c")

# Theme: follows the system by default; the toggle in the header forces light or dark and is remembered.
CSS = (":root{" + LIGHT + "}\n"
       "@media (prefers-color-scheme:dark){:root:not([data-theme=\"light\"]){" + DARK + "}}\n"
       ":root[data-theme=\"dark\"]{" + DARK + "}\n"
       ":root[data-theme=\"light\"]{" + LIGHT + "}\n") + """
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header.top{max-width:1000px;margin:0 auto;padding:20px 16px 6px}
header.top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
header.top h1{font-size:24px;margin:0 0 2px}
.themebtn{appearance:none;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:6px 12px;font:inherit;font-size:13px;cursor:pointer;white-space:nowrap}
.themebtn:hover{background:var(--code)}.themebtn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
a{color:var(--accent)}
.tabs{position:sticky;top:0;z-index:10;background:var(--card);border-bottom:1px solid var(--line);display:flex;gap:2px;overflow-x:auto;padding:6px 12px}
.tabs button{appearance:none;border:0;background:none;color:var(--muted);padding:8px 12px;border-radius:8px;white-space:nowrap;font:inherit;font-size:14px;cursor:pointer}
.tabs button:hover{background:var(--code);color:var(--fg)}
.tabs button[aria-selected=true]{background:var(--accent-bg);color:var(--accent);font-weight:600}
.tabs button:focus-visible,a:focus-visible,button.copy:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
main{max-width:1000px;margin:0 auto;padding:8px 16px 64px}
.js .panel{display:none}.js .panel.active{display:block}
h2{font-size:20px;margin:24px 0 10px}h3{font-size:16px;margin:24px 0 8px}h4{margin:0 0 6px}
.sub{color:var(--muted);margin:0 0 12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.stat b{display:block;font-size:24px;line-height:1.2}.stat span{color:var(--muted);font-size:13px}
.callout{border-left:4px solid var(--accent);background:var(--card);padding:12px 16px;border-radius:0 10px 10px 0;margin:12px 0}
.callout.warn{border-left-color:var(--warn)}
.quickwin{background:var(--win);border:1px solid var(--win-line);border-radius:12px;padding:16px 18px;margin:14px 0}
.quickwin .label{font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--warn)}
.quickwin h2{margin:4px 0 6px;font-size:21px}
.tag{display:inline-block;font-size:12px;padding:1px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted);margin-right:4px}
.tag.good{color:var(--good);border-color:var(--good)}.tag.bad{color:var(--bad);border-color:var(--bad)}.tag.warn{color:var(--warn);border-color:var(--warn)}
.ba{display:grid;gap:10px;grid-template-columns:1fr 1fr}@media(max-width:700px){.ba{grid-template-columns:1fr}}
.ba>div{border:1px solid var(--line);border-radius:8px;padding:10px;background:var(--code)}
.ba h4{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
pre,code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px}
pre{background:var(--code);padding:10px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;margin:6px 0}
.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600;font-size:13px}
.bar{display:grid;grid-template-columns:150px 1fr 90px;gap:8px;align-items:center;margin:5px 0;font-size:14px}
.bar i{display:block;height:14px;border-radius:4px;background:var(--accent)}.bar span.v{color:var(--muted);text-align:right;font-size:13px}
.heat{background:rgb(var(--bad-rgb)/calc(var(--h,0)*.6))}
.muted{color:var(--muted)}.na{color:var(--muted);font-style:italic}
button.copy{float:right;font-size:12px;padding:3px 10px;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:6px;cursor:pointer}
ul.check{list-style:none;padding:0}ul.check li{padding:4px 0}ul.check li:before{content:"\\2610  ";color:var(--muted)}
.cols{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
details{margin:8px 0}summary{cursor:pointer;color:var(--accent)}
.next{margin-top:28px}.next a{color:var(--accent);cursor:pointer;text-decoration:none}
svg text{fill:var(--fg);font-size:12px}svg .gl{stroke:var(--line);fill:none}svg .poly{fill:var(--accent);fill-opacity:.25;stroke:var(--accent);stroke-width:2}
.srcs{margin:8px 0 0;font-size:13px;color:var(--muted)}.srcs a{margin-right:10px}
.doctor{border-left:4px solid var(--good);background:var(--card);padding:12px 16px;border-radius:0 10px 10px 0;margin:12px 0}
@media print{:root,:root[data-theme]{""" + LIGHT + """}.tabs,.themebtn,button.copy,.next{display:none}.js .panel{display:block!important}.card,.ba>div{break-inside:avoid}}
"""

THEME_INIT = """(function(){try{var t=localStorage.getItem('pi-theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t)}catch(e){}})();"""

JS = """
(function(){
var btn=document.getElementById('theme');
function cur(){var t=document.documentElement.getAttribute('data-theme');return t==='light'||t==='dark'?t:'auto'}
function label(){if(btn)btn.textContent='Theme: '+cur().replace('auto','system')}
if(btn){label();btn.addEventListener('click',function(){
  var n={auto:'light',light:'dark',dark:'auto'}[cur()];
  if(n==='auto')document.documentElement.removeAttribute('data-theme');else document.documentElement.setAttribute('data-theme',n);
  try{if(n==='auto')localStorage.removeItem('pi-theme');else localStorage.setItem('pi-theme',n)}catch(e){}
  label()})}

var d=document,root=d.documentElement;root.classList.add('js');
var tabs=[].slice.call(d.querySelectorAll('.tabs [role=tab]'));
function show(id,push){
  var ok=tabs.some(function(t){return t.dataset.tab===id});if(!ok)id=tabs[0].dataset.tab;
  tabs.forEach(function(t){var on=t.dataset.tab===id;t.setAttribute('aria-selected',on);t.tabIndex=on?0:-1});
  [].forEach.call(d.querySelectorAll('.panel'),function(p){p.classList.toggle('active',p.id==='p-'+id)});
  if(push){try{history.replaceState(null,'','#'+id)}catch(e){}}
  window.scrollTo(0,0);
}
tabs.forEach(function(t,i){
  t.addEventListener('click',function(){show(t.dataset.tab,true)});
  t.addEventListener('keydown',function(e){
    var n=e.key==='ArrowRight'?i+1:e.key==='ArrowLeft'?i-1:null;if(n===null)return;
    n=(n+tabs.length)%tabs.length;tabs[n].focus();show(tabs[n].dataset.tab,true);e.preventDefault()});
});
[].forEach.call(d.querySelectorAll('[data-goto]'),function(a){a.addEventListener('click',function(){show(a.dataset.goto,true)})});
show((location.hash||'').slice(1)||tabs[0].dataset.tab,false);
[].forEach.call(d.querySelectorAll('button.copy'),function(b){b.addEventListener('click',function(){
  var el=d.getElementById(b.dataset.target);var t=el?el.textContent:'';
  function done(){var o=b.textContent;b.textContent='Copied';setTimeout(function(){b.textContent=o},1200)}
  function fallback(){var ta=d.createElement('textarea');ta.value=t;d.body.appendChild(ta);ta.select();
    try{d.execCommand('copy');done()}catch(e){}d.body.removeChild(ta)}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(done,fallback)}else{fallback()}})});
})();
"""

# Short catalog so the Techniques tab is useful even when insights.json recommends nothing.
# Longer guidance lives in references/prompting-techniques.md.
TECHNIQUES = [
    ("rpi", "RPI: Research, Plan, Implement",
     "Three separate steps. Research writes findings to a file and changes no code. Plan turns them into numbered steps you review. "
     "Implement follows the plan in a fresh context.",
     "Unfamiliar code, changes that touch several files, or anything you would not finish in one sitting."),
    ("plan-mode", "Plan mode / plan before editing",
     "Ask for a plan and say 'do not edit yet' (or press Shift+Tab to plan mode). Approve or correct the plan, then let it run.",
     "You can already picture two ways to do it and want to choose before code exists."),
    ("interview", "Interview me first",
     "Say 'ask me questions until you can write the spec' before any building starts. Answers become the spec.",
     "The prompt is a one-liner for a feature with many open choices."),
    ("staged", "Staged delivery with checkpoints",
     "Split a big backlog into stages and ask to stop and report after each. You choose which stage continues.",
     "A prompt that asks for a whole backlog; you have had to cut scope after the first run."),
    ("verify-loop", "Give it a way to check itself",
     "End with 'Done when' and name the command or visible result: tests, build, screenshot, a number on screen.",
     "Features that were correct in code but missing something you could see or measure."),
    ("builder-critic", "Builder plus critic",
     "A second agent reviews the first one's work against a written bar and sends it back. Add your recurring checks to the critic's rubric.",
     "Quality problems found after delivery; you already run loops or workflows."),
    ("repro-first", "Reproduce first, then fix",
     "For bugs: 'write a failing test or exact repro steps first, then fix, then show the test passing'.",
     "Bug reports that bounced back because the fix did not match the symptom."),
    ("subagent-research", "Delegate exploration to subagents",
     "Send reading and searching to subagents so the main conversation keeps room for decisions.",
     "Long sessions where the main context fills with file dumps."),
    ("context-hygiene", "Context hygiene: clear, handoff, restart",
     "Use /clear between unrelated tasks. At a natural break write a short handoff note and start a fresh session from it.",
     "Sessions with many turns, repeated instructions or the agent forgetting earlier decisions."),
    ("standing-rules", "Put standing rules in files, not chat",
     "Anything you say twice goes into CLAUDE.md, a rule file or a skill so every session and subagent sees it.",
     "The same correction or preference appears in more than one session."),
    ("pattern-reference", "Point at an example",
     "'Follow the pattern in <file>' or paste one good example of the output you want.",
     "Output style or structure keeps missing; you can show a good case."),
    ("deep-thinking", "Ask for deeper reasoning where it counts",
     "For design choices and hard bugs, ask it to think through options and trade-offs before choosing; keep routine edits on a fast path.",
     "Architecture decisions and bugs that survived a first fix."),
]


# Trusted sources only. Every link points at Anthropic's own documentation or engineering blog;
# insights.json refers to them by id, so no free-form URL ever reaches the page.
CC = "https://code.claude.com/docs/en/"
SOURCES = {
    "best-practices": ("Best practices for Claude Code", CC + "best-practices"),
    "verify": ("Give Claude a way to verify its work", CC + "best-practices#give-claude-a-way-to-verify-its-work"),
    "plan": ("Explore first, then plan, then code", CC + "best-practices#explore-first-then-plan-then-code"),
    "interview": ("Let Claude interview you", CC + "best-practices#let-claude-interview-you"),
    "context": ("Manage context aggressively", CC + "best-practices#manage-context-aggressively"),
    "investigate": ("Use subagents for investigation", CC + "best-practices#use-subagents-for-investigation"),
    "claude-md": ("Write an effective CLAUDE.md", CC + "best-practices#write-an-effective-claudemd"),
    "memory": ("How Claude remembers your project (CLAUDE.md, auto memory)", CC + "memory"),
    "prompt-audit": ("Audit your instruction files (/doctor prompt-audit)", CC + "memory#audit-your-instruction-files"),
    "skills": ("Extend Claude with skills", CC + "skills"),
    "sub-agents": ("Create custom subagents", CC + "sub-agents"),
    "hooks": ("Hooks guide", CC + "hooks-guide"),
    "model-config": ("Model configuration (/model, opusplan)", CC + "model-config"),
    "modes": ("Permission modes and plan mode", CC + "permission-modes"),
    "workflows": ("Common workflows", CC + "common-workflows"),
    "how-it-works": ("How Claude Code works", CC + "how-claude-code-works"),
    "features": ("Extend Claude Code: skills, hooks, MCP, subagents", CC + "features-overview"),
    "prompting": ("Prompting best practices (Claude Platform docs)",
                  "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices"),
    "context-eng": ("Effective context engineering for AI agents (Anthropic engineering)",
                    "https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents"),
}
# Source ids that go with each technique in the catalogue.
TECH_SOURCES = {
    "rpi": ["plan", "modes", "workflows"], "plan-mode": ["plan", "modes"], "interview": ["interview"],
    "staged": ["plan", "best-practices"], "verify-loop": ["verify"], "builder-critic": ["sub-agents", "best-practices"],
    "repro-first": ["verify", "workflows"], "subagent-research": ["investigate", "sub-agents"],
    "context-hygiene": ["context", "context-eng"], "standing-rules": ["claude-md", "memory"],
    "pattern-reference": ["prompting"], "deep-thinking": ["prompting", "model-config"],
}
# Used when an action item names no sources: match the topic from its wording.
KEYWORD_SOURCES = [
    (r"claude\.md|agents\.md|standing rule|memory", ["claude-md", "memory"]),
    (r"prompt-audit|/doctor|stale|outdated|dead ref", ["prompt-audit"]),
    (r"\bskill", ["skills"]), (r"subagent|sub-agent|critic|builder", ["sub-agents"]),
    (r"\bmodel\b|/model|opus|sonnet|haiku|tier", ["model-config"]),
    (r"done when|verify|check|screenshot|test", ["verify"]),
    (r"\bplan\b|plan mode|research|rpi", ["plan"]), (r"stage|backlog|scope|split", ["plan"]),
    (r"/clear|context|handoff|long session", ["context"]), (r"\bhook", ["hooks"]),
    (r"interview|spec", ["interview"]),
]


def source_anchor(i) -> str:
    t, u = SOURCES[i]
    return f'<a href="{html.escape(u)}" target="_blank" rel="noopener noreferrer">{html.escape(t)}</a>'


def source_links(ids) -> str:
    out = [source_anchor(i) for i in dict.fromkeys(ids) if i in SOURCES]
    return f'<div class="srcs">Sources: {" · ".join(out)}</div>' if out else ""


def infer_sources(text: str):
    ids = []
    for rx, found in KEYWORD_SOURCES:
        if re.search(rx, text or "", re.I):
            ids += found
    return list(dict.fromkeys(ids))[:3]


def version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except Exception:
        return (0,)


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return esc(n)


def na(msg="Not provided in insights.json") -> str:
    return f'<p class="na">{esc(msg)}</p>'


def bars(items, unit="") -> str:
    """items: list of (label, value, display)"""
    if not items:
        return na("No data")
    mx = max((v for _, v, _ in items), default=0) or 1
    rows = []
    for label, v, disp in items:
        w = max(2, round(100 * v / mx))
        rows.append(f'<div class="bar"><span>{esc(label)}</span><i style="width:{w}%"></i><span class="v">{esc(disp)}{esc(unit)}</span></div>')
    return "".join(rows)


def table(headers, rows, raw_cols=()) -> str:
    if not rows:
        return na("No data")
    h = "".join(f"<th>{esc(x)}</th>" for x in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{c if i in raw_cols else esc(c)}</td>" for i, c in enumerate(r)) + "</tr>"
    return f'<div class="tablewrap"><table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table></div>'


def lst(items, cls="") -> str:
    if not items:
        return na()
    return f'<ul class="{cls}">' + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def copybox(id_, text, label="Copy") -> str:
    return f'<button class="copy" data-target="{id_}">{esc(label)}</button><pre id="{id_}">{esc(text)}</pre>'


def radar(scores) -> str:
    """scores: list of (label, value 0..5). Labels wrap onto several lines and the canvas is wide
    enough that none is cut off at the edge."""
    n = len(scores)
    if n < 3:
        return na("Need at least 3 criteria for a radar chart")
    W, H, cx, cy, R = 700, 360, 350, 180, 105
    pts, axes, labels = [], [], []
    for i, (lab, val) in enumerate(scores):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        v = max(0.0, min(5.0, float(val))) / 5
        pts.append(f"{cx + R * v * math.cos(ang):.1f},{cy + R * v * math.sin(ang):.1f}")
        axes.append(f'<line class="gl" x1="{cx}" y1="{cy}" x2="{cx + R * math.cos(ang):.1f}" y2="{cy + R * math.sin(ang):.1f}"/>')
        lx, ly = cx + (R + 16) * math.cos(ang), cy + (R + 16) * math.sin(ang)
        anchor = "middle" if abs(math.cos(ang)) < 0.3 else ("start" if math.cos(ang) > 0 else "end")
        lines = textwrap.wrap(str(lab), 24) or [""]
        n_l = len(lines) + 1  # label lines plus the score line
        sin = math.sin(ang)
        y0 = ly - (n_l - 1) * 14 if sin < -0.9 else (ly + 10 if sin > 0.9 else ly + 4 - (n_l - 1) * 7)
        tspans = "".join(f'<tspan x="{lx:.1f}" y="{y0 + k * 14:.1f}">{esc(t)}</tspan>' for k, t in enumerate(lines))
        tspans += f'<tspan x="{lx:.1f}" y="{y0 + len(lines) * 14:.1f}" font-weight="700">{float(val):.1f} / 5</tspan>'
        labels.append(f'<text text-anchor="{anchor}">{tspans}</text>')
    rings = ""
    for lvl in range(1, 6):
        ring = " ".join(f"{cx + R * lvl / 5 * math.cos(-math.pi / 2 + 2 * math.pi * i / n):.1f},"
                        f"{cy + R * lvl / 5 * math.sin(-math.pi / 2 + 2 * math.pi * i / n):.1f}" for i in range(n))
        rings += f'<polygon class="gl" points="{ring}"/>'
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:760px;overflow:visible" role="img" aria-label="Prompt quality radar chart">'
            f'{rings}{"".join(axes)}<polygon class="poly" points="{" ".join(pts)}"/>{"".join(labels)}</svg>')


def redact_tree(x, extra):
    if isinstance(x, str):
        return redact(x, extra)
    if isinstance(x, list):
        return [redact_tree(i, extra) for i in x]
    if isinstance(x, dict):
        return {k: redact_tree(v, extra) for k, v in x.items()}
    return x


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\"'`“”‘’]", "", s or "")).strip().lower()


def verify_quote(before: str, sids, S) -> tuple:
    """Check that a 'before' excerpt really occurs in the stored prompts of the cited sessions.

    Returns (state, found, total) with state in verified | partial | missing | unchecked.
    """
    text = re.sub(r"\((?:[^()]*\b[0-9a-f]{8}\b[^()]*)\)\s*$", "", before or "").strip()  # drop "(c518ffd8, turn 3)"
    frags = [norm(f).rstrip("…") for f in re.split(r"\.\.\.|…", text)]
    frags = [f for f in frags if len(f) >= 12]
    if not frags:
        return "unchecked", 0, 0
    hay = ""
    for s in S.get("sessions", []):
        if any(s["id"].startswith(x) for x in (sids or [])) or not sids:
            hay += " " + " ".join(norm(p["text"]).rstrip("…") for p in s.get("prompts", []))
            hay += " " + norm(s.get("first_prompt") or "")
    found = sum(1 for f in frags if f in hay)
    state = "verified" if found == len(frags) else ("partial" if found else "missing")
    return state, found, len(frags)


# ----------------------------------------------------------------------------- panels

def p_overview(S, I):
    A, T, M = S["aggregates"], S["aggregates"]["totals"], S["meta"]
    body = ""
    sessions = S.get("sessions", [])
    heur = sum(1 for s in sessions if s.get("task_type_source") == "heuristic")
    flt = (M.get("filters") or {}).get("project")
    chips = [f'{M["sessions_analyzed"]} of {M["sessions_available_total"]} sessions']
    if M.get("date_range"):
        chips.append(f'{M["date_range"][0]} to {M["date_range"][1]}')
    if flt:
        chips.append(f"project: {flt}")
    chips.append("task labels reviewed" if sessions and heur == 0 else f"task labels: {heur} of {len(sessions)} heuristic")
    body += '<p class="sub">' + " · ".join(esc(c) for c in chips) + "</p>"

    qw = I.get("quick_win")
    if qw:
        mins = f' · about {esc(qw.get("minutes"))} min' if qw.get("minutes") else ""
        body += ('<div class="quickwin"><div class="label">Quick win' + mins + '</div>'
                 f'<h2>{esc(qw.get("title"))}</h2>')
        if qw.get("why"):
            body += f'<p>{esc(qw["why"])}</p>'
        if qw.get("do_this"):
            body += copybox("qw", qw["do_this"])
        if qw.get("evidence"):
            body += f'<p class="muted">Evidence: {esc(qw["evidence"])}</p>'
        body += "</div>"
    else:
        body += '<div class="callout warn"><b>No quick win provided.</b> insights.json should contain a <code>quick_win</code> object.</div>'

    if I.get("top_change"):
        body += f'<div class="callout"><b>Highest-impact change:</b> {esc(I["top_change"])}</div>'
    heads = I.get("headline_insights") or []
    body += "<h3>What the sessions show</h3>" + (f'<div class="card">{lst(heads)}</div>' if heads else na("headline_insights missing"))

    auto = sum((A.get("automated_turns_excluded") or {}).values())
    uncaptured = (I.get("stats") or {}).get("repeated_corrections_not_captured")
    if uncaptured is None:
        uncaptured = sum(1 for r in A["repeated_corrections"] if not r["possibly_covered_by"])
    cards = [
        (T["avg_user_turns"], "typed prompts per session"),
        (f'{T.get("short_prompt_share_pct", 0)}%', "typed prompts of 3 words or fewer"),
        (auto, "automated turns excluded"),
        (f"{T['pct_sessions_with_correction_or_interrupt']}%", "sessions with corrections or interrupts"),
        (A.get("agent_files_touched", 0), f"agent files touched ({A['agent_file_edit_count']} edit calls)"),
        (uncaptured, "repeated corrections not in a file"),
        (len(A["by_model"]), "model families used"),
        (f"{T['active_hours']} h", "active time"),
        (T["total_tool_errors"], "tool errors"),
    ]
    body += "<h3>Numbers</h3><div class=\"grid\">" + "".join(
        f'<div class="card stat"><b>{esc(v)}</b><span>{esc(l)}</span></div>' for v, l in cards) + "</div>"
    if M["sessions_analyzed"] < 10:
        body += (f'<div class="callout warn">Small sample ({M["sessions_analyzed"]} sessions). Treat findings as leads, not statistics. '
                 'Re-run after more sessions.</div>')
    techs = I.get("techniques") or []
    if techs:
        t = techs[0]
        body += ('<h3>Technique to try</h3><div class="card">'
                 f'<b>{esc(t.get("name"))}</b> <span class="tag">{esc(t.get("when", ""))[:90]}</span>'
                 f'<p>{esc(t.get("why_for_you", ""))}</p>'
                 '<p class="next"><a data-goto="techniques">See all recommended techniques →</a></p></div>')
    return "Overview", body


def p_prompts(S, I):
    pq = I.get("prompt_quality", {})
    scores = [(x.get("criterion", "?"), x.get("score", 0)) for x in pq.get("scores", [])]
    body = ""
    if scores:
        body += f'<div class="card">{radar(scores)}</div>'
        body += table(["Criterion", "Score (0-5)", "Note"], [[x.get("criterion"), x.get("score"), x.get("note", "")] for x in pq["scores"]])
    else:
        h = S["aggregates"]["prompt_quality_heuristic"]
        names = {"has_goal_why": "Goal and why", "has_scope": "Scope / constraints", "has_context_pointer": "Context pointers",
                 "has_done_criteria": "Done criteria", "asks_plan_first": "Plan first"}
        body += '<p class="sub">Regex heuristic on first prompts (insights.json had no scores).</p>'
        body += bars([(names[k], v, f"{v}") for k, v in h["pct"].items()], "%")
    body += "<h3>Top recurring weaknesses</h3>"
    for i, w in enumerate(I.get("weaknesses", []), 1):
        sids = w.get("evidence_sessions", [])
        if w.get("before_kind") == "behavior":
            tag = '<span class="tag">behaviour, no prompt to quote</span>'
        else:
            st, f, n = verify_quote(w.get("before", ""), sids, S)
            tag = {"verified": '<span class="tag good">verbatim quote checked</span>',
                   "partial": f'<span class="tag warn">partly found in transcript ({f}/{n})</span>',
                   "missing": '<span class="tag bad">not found in transcript: may be reconstructed</span>',
                   "unchecked": '<span class="tag">quote not checked</span>'}[st]
        body += (f'<div class="card"><b>{i}. {esc(w.get("title"))}</b> {tag}'
                 f'<div class="ba"><div><h4>Before</h4><pre>{esc(w.get("before"))}</pre></div>'
                 f'<div><h4>After</h4><pre>{esc(w.get("after"))}</pre></div></div>'
                 f'<p>{esc(w.get("why"))}</p>'
                 f'{"<p class=muted>Evidence: " + esc(", ".join(sids)) + "</p>" if sids else ""}</div>')
    if not I.get("weaknesses"):
        body += na()
    body += "<h3>Top strengths</h3>"
    body += "".join(f'<div class="card"><span class="tag good">strength</span><b>{esc(s.get("title"))}</b><p>{esc(s.get("evidence"))}</p></div>'
                    for s in I.get("strengths", [])) or na()

    body += "<h3>Best vs worst session</h3>"
    bw = I.get("best_vs_worst")
    if bw:
        comparable = bw.get("comparable", True)
        if not comparable:
            body += (f'<div class="callout warn"><b>Not a like-for-like comparison.</b> {esc(bw.get("comparability_note", ""))}</div>')

        def side(k, label, cls):
            d = bw.get(k, {})
            return (f'<div><h4><span class="tag {cls}">{label}</span> {esc(d.get("session_id", ""))}</h4>'
                    f'<p><b>First prompt:</b></p><pre>{esc(d.get("first_prompt", ""))}</pre>'
                    f'<p>{esc(d.get("what_happened", ""))}</p>{lst(d.get("prompt_traits", []))}</div>')
        lb = ("best", "worst") if comparable else ("smoother", "rougher")
        body += f'<div class="ba">{side("best", lb[0], "good")}{side("worst", lb[1], "bad")}</div>'
        if bw.get("key_difference"):
            body += f'<div class="callout"><b>Key difference:</b> {esc(bw["key_difference"])}</div>'
    else:
        A = S["aggregates"]
        pairs = A.get("best_worst_by_task") or {}
        cands = [x for v in pairs.values() for x in (v["best"], v["worst"])] or A["best_session_candidates"] + A["worst_session_candidates"]
        rows = [[x["session_id"][:8], x["task_type"], x["model"], x["user_turns"], x["friction_per_turn"], x["first_prompt"]] for x in cands]
        body += ('<p class="sub">Candidates by friction score (insights.json had no comparison).</p>'
                 + table(["Session", "Task", "Model", "Turns", "Friction/turn", "First prompt"], rows))
    return "Prompts", body


def p_techniques(S, I):
    recs = I.get("techniques") or []
    body = '<p class="sub">Ways of working with the agent that fit the patterns in your sessions. The first one is the most useful to try.</p>'
    if not recs:
        body += '<div class="callout warn"><b>No techniques recommended.</b> insights.json should contain a <code>techniques</code> list (RPI, plan mode, staged delivery, and so on).</div>'
    cat = {t[0]: t for t in TECHNIQUES}
    for i, t in enumerate(recs):
        base = cat.get(t.get("id"), None)
        name = t.get("name") or (base[1] if base else "Technique")
        body += f'<div class="card"><b>{i + 1}. {esc(name)}</b>'
        if t.get("when") or base:
            body += f' <span class="tag">{esc(t.get("when") or base[3])}</span>'
        if t.get("why_for_you"):
            body += f'<p><b>Why it fits you:</b> {esc(t["why_for_you"])}</p>'
        if t.get("steps"):
            body += "<ol>" + "".join(f"<li>{esc(x)}</li>" for x in t["steps"]) + "</ol>"
        elif base:
            body += f"<p>{esc(base[2])}</p>"
        if t.get("example_prompt"):
            body += f'<p><b>Example prompt</b></p>{copybox(f"tq{i}", t["example_prompt"])}'
        if t.get("evidence_sessions"):
            body += f'<p class="muted">Evidence: {esc(", ".join(t["evidence_sessions"]))}</p>'
        body += "</div>"
    used = {t.get("id") for t in recs}
    body += (f'<details><summary>Technique catalog ({len(TECHNIQUES)})</summary>'
             + table(["Technique", "What it is", "Use it when"], [[t[1], t[2], t[3]] for t in TECHNIQUES]) + "</details>")
    return "Techniques", body


def p_agent_files(S, I):
    AF = I.get("agent_files", {})
    find = {f.get("path"): f for f in AF.get("findings", [])}
    body = f'<p>{esc(AF.get("update_pattern", ""))}</p>' if AF.get("update_pattern") else ""
    flagged = [f for f in S["agent_files"] if f["hints"] or f["possibly_dead_references"]]
    flagged += [f for f in S["agent_files"] if find.get(f["path"], {}).get("status") in ("stale", "bloated", "thin", "at-risk") and f not in flagged]
    vers = list(S["meta"].get("claude_code_versions") or {})
    too_old = bool(vers) and max(version_tuple(v) for v in vers) < (2, 1, 283)
    if flagged or AF.get("repeated_corrections") or AF.get("rewrites"):
        first = flagged[0]["path"] if flagged else ""
        body += ('<div class="doctor"><b>Run <code>/doctor prompt-audit</code> in Claude Code.</b> It checks CLAUDE.md, AGENTS.md, rules, skills, commands '
                 'and subagents for instructions written for older models, references to files or commands that no longer exist, and files that contradict '
                 'each other. It reports proposed edits and changes nothing until you approve.'
                 + (f' To check one file: <code>/doctor prompt-audit {esc(first)}</code>.' if first else "")
                 + (' Needs Claude Code v2.1.283 or later; your sessions ran an older version, so update first.' if too_old else " Needs Claude Code v2.1.283 or later.")
                 + source_links(["prompt-audit", "memory"]) + "</div>")
    roots = S.get("project_roots") or []
    if roots:
        yn = lambda b: "yes" if b else "no"
        body += "<h3>Checked on disk</h3>" + table(
            ["Project", "Exists", "CLAUDE.md", "AGENTS.md", "Rules", "Subagents", "Skills", "Memory notes", "Sessions"],
            [[r["project"], yn(r["exists"]), yn(r["claude_md"] or r["claude_local_md"]), yn(r["agents_md"]), r["rules"],
              r["agents"], r["skills"], f'{r["memory_files"]}' + (f' ({", ".join(r.get("memory_note_names", [])[:4])})' if r.get("memory_note_names") else ""),
              r["sessions"]] for r in roots])
    rows = []
    for f in S["agent_files"]:
        fi = find.get(f["path"], {})
        status = fi.get("status") or (", ".join(f["hints"]) or "no flags")
        rows.append([f["path"], f["kind"], f["scope"], f["last_modified"][:10], f"{f['lines']} lines / {f['size_bytes']} B",
                     f["sessions_after_last_edit"], status, fi.get("evidence") or ", ".join(f["possibly_dead_references"][:3])])
        if fi.get("action"):
            rows[-1][-1] = f'{rows[-1][-1]} → {fi["action"]}'
    body += "<h3>File health</h3>" + table(
        ["File", "Kind", "Scope", "Last modified", "Size", "Sessions since", "Status", "Evidence → action"], rows)
    ev = S["aggregates"]["agent_file_edit_events"]
    body += "<h3>Update timeline</h3>" + table(["Date", "Project", "File", "Via", "Calls"],
                                              [[e["date"], e["project"], e["path"] + ("" if e.get("on_disk", True) else "  (no longer on disk)"), e["tool"], e.get("calls", 1)] for e in ev])
    body += "<h3>Repeated corrections to capture</h3>"
    rc = AF.get("repeated_corrections", [])
    for i, r in enumerate(rc):
        body += (f'<div class="card"><b>{esc(r.get("theme"))}</b> '
                 f'<span class="tag">{esc(r.get("occurrences", ""))}x</span><span class="tag">add to {esc(r.get("target_file", "CLAUDE.md"))}</span>'
                 f'{copybox(f"rc{i}", r.get("proposed_line"))}</div>')
    if not rc:
        auto = S["aggregates"]["repeated_corrections"]
        body += table(["Occurrences", "Sample", "Possibly covered by"],
                      [[r["occurrences"], r["representative"], ", ".join(r["possibly_covered_by"]) or "-"] for r in auto]) if auto \
            else '<p class="na">No correction repeated across sessions in this sample.</p>'
    ri = S["aggregates"].get("repeated_instructions") or []
    if ri:
        body += "<h3>Instructions you repeat across sessions</h3><p class=\"sub\">Sentences that appear in two or more sessions: candidates for CLAUDE.md, a rule or a skill.</p>" + table(
            ["Sessions", "Example", "Already in"], [[len(r["sessions"]), r["example"], ", ".join(r["possibly_covered_by"]) or "no agent file"] for r in ri])
    body += "<h3>Rules and skills to rewrite, merge or remove</h3>"
    for i, r in enumerate(AF.get("rewrites", [])):
        body += (f'<div class="card"><b>{esc(r.get("path"))}</b> <span class="tag warn">{esc(r.get("action", "rewrite"))}</span>'
                 f'<p>{esc(r.get("issue"))}</p>{copybox(f"rw{i}", r.get("proposed_text"))}</div>')
    if not AF.get("rewrites"):
        body += na()
    A = S["aggregates"]
    nt = A["skills_never_triggered_in_sample"]
    inv = A.get("skills_invoked_by_slash") or {}
    if inv:
        body += "<h3>Skills you invoked by slash command</h3>" + table(["Command", "Times"], [["/" + k, v] for k, v in inv.items()])
    if nt:
        body += "<h3>Skills never triggered in this sample</h3>" + table(["Skill", "Description"], [[x["name"], x["description"]] for x in nt])
    body += "<h3>Maintenance routine</h3>" + lst(AF.get("routine", []), "check")
    return "Agent files", body


def p_models(S, I):
    A, MR = S["aggregates"], I.get("model_routing", {})
    bm = A["by_model"]
    body = ""
    heur = [s for s in S.get("sessions", []) if s.get("task_type_source") == "heuristic"]
    if heur:
        body += (f'<div class="callout warn"><b>Task types are still heuristic for {len(heur)} of {len(S["sessions"])} sessions.</b> '
                 'The task x model matrix below compares only as well as those labels are right. Review labels.todo.json, save it as '
                 'labels.json and re-run the analyzer with --labels.</div>')
    body += "<h3>Assistant messages by model</h3>" + bars(
        [(f, d["assistant_msgs"], fmt_int(d["assistant_msgs"])) for f, d in sorted(bm.items(), key=lambda kv: -kv[1]["assistant_msgs"])])
    body += "<h3>Sessions by task type</h3>" + bars([(t, d["sessions"], str(d["sessions"])) for t, d in A["by_task_type"].items()])
    body += "<h3>Tokens (measured)</h3>" + table(
        ["Model", "Sessions", "Input", "Output", "Cache read", "Cache write", "Est. cost USD"],
        [[f, d["sessions"], fmt_int(d["tokens"]["input"]), fmt_int(d["tokens"]["output"]), fmt_int(d["tokens"]["cache_read"]),
          fmt_int(d["tokens"]["cache_write"]), d["estimated_cost_usd"] if d["estimated_cost_usd"] is not None else "n/a"] for f, d in bm.items()])
    if all(d["estimated_cost_usd"] is None for d in bm.values()):
        body += '<p class="muted">No price file was given, so cost is not estimated. Cache reads are the largest token count by far; they are billed at a lower rate than fresh input.</p>'
    fams = sorted(bm)
    mx = max((c["avg_friction_per_turn"] for r in A["task_model_matrix"].values() for c in r.values()), default=0) or 1
    rows = ""
    for t, r in A["task_model_matrix"].items():
        rows += f"<tr><td>{esc(t)}</td>"
        for f in fams:
            c = r.get(f)
            if c:
                rows += (f'<td class="heat" style="--h:{c["avg_friction_per_turn"] / mx:.2f}">n={c["sessions"]}<br>'
                         f'<span class="muted">{c["avg_user_turns"]} turns, f/t {c["avg_friction_per_turn"]}</span></td>')
            else:
                rows += '<td class="muted">-</td>'
        rows += "</tr>"
    body += ("<h3>Task type x model: friction matrix</h3><p class=\"sub\">Darker = more friction per typed prompt (f/t). "
             "Cells with n&lt;3 are anecdotes, not evidence.</p>"
             f'<div class="tablewrap"><table><thead><tr><th>Task type</th>{"".join(f"<th>{esc(f)}</th>" for f in fams)}</tr></thead><tbody>{rows}</tbody></table></div>')
    mism = MR.get("mismatches") or [{"session_id": m["session_id"], "task_type": m["task_type"], "model": m["model"],
                                     "issue": m["kind"], "suggestion": m["evidence"]} for m in A["model_mismatch_candidates"]]
    body += "<h3>Mismatches</h3>" + table(["Session", "Task", "Model", "Issue", "Suggestion / evidence"],
                                          [[str(m.get("session_id", ""))[:8], m.get("task_type"), m.get("model"), m.get("issue"), m.get("suggestion")] for m in mism])
    guide = MR.get("guide", [])
    body += "<h3>Model routing guide</h3>" + (table(["Task type", "Recommended model", "Why", "Evidence"],
                                                    [[g.get("task_type"), g.get("recommended"), g.get("why"), g.get("evidence")] for g in guide]) if guide else na())
    body += "<h3>Rules of thumb</h3>" + lst(MR.get("rules_of_thumb", []))
    body += '<p class="muted">Available models change. Re-check this guide against the current model list (/model) before adopting it.</p>'
    return "Models", body


def compose_template(t) -> str:
    """Build the copyable prompt from structured fields; fall back to a free-form body."""
    parts = []
    for key, label in (("goal", "Goal"), ("context", "Context"), ("constraints", "Constraints"),
                       ("approach", "Approach"), ("done_when", "Done when")):
        if t.get(key):
            parts.append(f"{label}: {t[key]}")
    return "\n".join(parts) if parts else (t.get("body") or "")


def p_templates(S, I):
    body = '<p class="sub">Copy a template, replace the &lt;placeholders&gt;, and send it. Each one names goal, context, constraints, approach and what done looks like.</p>'
    for i, t in enumerate(I.get("templates", [])):
        tech = f'<span class="tag">technique: {esc(t["technique"])}</span>' if t.get("technique") else ""
        body += (f'<div class="card"><b>{esc(t.get("title"))}</b> '
                 f'<span class="tag">{esc(t.get("task_type", ""))}</span><span class="tag good">model: {esc(t.get("recommended_model", "-"))}</span>{tech}'
                 f'{copybox(f"tpl{i}", compose_template(t))}</div>')
    if not I.get("templates"):
        body += na()
    return "Templates", body


def action_items(items) -> str:
    """Each item is a string or {"text": ..., "sources": [ids]}; links come from the trusted catalogue."""
    if not items:
        return na()
    rows = ""
    for it in items:
        text = it.get("text", "") if isinstance(it, dict) else str(it)
        ids = (it.get("sources") if isinstance(it, dict) else None) or infer_sources(text)
        rows += f"<li>{esc(text)}{source_links(ids)}</li>"
    return f'<ul class="check">{rows}</ul>'


def p_plan(S, I):
    ap = I.get("action_plan", {})
    cols = "".join(f'<div class="card"><b>{t}</b>{action_items(ap.get(k, []))}</div>'
                   for k, t in (("now", "Do now"), ("this_month", "This month"), ("ongoing", "Ongoing")))
    reading = ["best-practices", "claude-md", "prompting"]
    for t in I.get("techniques") or []:
        reading += TECH_SOURCES.get(t.get("id"), [])
    items = "".join(f"<li>{source_anchor(i)}</li>" for i in dict.fromkeys(reading) if i in SOURCES)
    body = f'<div class="cols">{cols}</div>'
    body += ('<h3>Further reading</h3><div class="card"><p class="sub">Anthropic documentation for the techniques and settings above. '
             f'These links need an internet connection.</p><ul>{items}</ul></div>')
    return "Action plan", body


def p_method(S, I):
    M = S["meta"]
    body = f'<div class="card"><p><b>Sample:</b> {M["sessions_analyzed"]} of {M["sessions_available_total"]} sessions. Generated {esc(M["generated_at"])}.</p>'
    body += "<p><b>Measured:</b> " + esc("; ".join(M["measured"])) + ".</p>"
    body += "<p><b>Heuristic (candidates, confirmed by reading context):</b> " + esc("; ".join(M["heuristic"])) + ".</p>"
    body += f'<p><b>Not covered:</b> {esc(M["not_covered"])}</p>'
    body += ("<p><b>Typed prompts:</b> only entries marked as human input count. Task notifications, messages from other sessions and injected "
             "reminders are excluded. Arguments of skill slash commands count as typed prompts.</p>")
    body += "<p><b>Redaction:</b> secrets, tokens, emails, IPs and long blobs are redacted in code before analysis; the report is redacted again at build time.</p></div>"
    if M["warnings"]:
        body += "<h3>Warnings</h3>" + lst(M["warnings"])
    body += "<h3>Limits noted by the analysis</h3>" + lst(I.get("limits", []))
    return "Method", body


PANELS = [("overview", p_overview), ("prompts", p_prompts), ("techniques", p_techniques), ("agentfiles", p_agent_files),
          ("models", p_models), ("templates", p_templates), ("plan", p_plan), ("method", p_method)]


def build(S, I) -> str:
    tabs, panels = "", ""
    for n, (id_, fn) in enumerate(PANELS):
        title, body = fn(S, I)
        sel = "true" if n == 0 else "false"
        tabs += (f'<button role="tab" id="t-{id_}" data-tab="{id_}" aria-controls="p-{id_}" aria-selected="{sel}" '
                 f'tabindex="{0 if n == 0 else -1}">{esc(title)}</button>')
        panels += (f'<section class="panel{" active" if n == 0 else ""}" id="p-{id_}" role="tabpanel" aria-labelledby="t-{id_}">'
                   f'<h2>{esc(title)}</h2>{body}</section>')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Claude Code prompt insights</title>'
            f'<script>{THEME_INIT}</script><style>{CSS}</style></head><body>'
            '<header class="top"><div><h1>Claude Code prompt insights</h1>'
            '<p class="sub">Generated from your local session transcripts. Contains redacted quotes; review before sharing.</p></div>'
            '<button id="theme" class="themebtn" type="button" aria-label="Switch between system, light and dark theme">Theme: system</button></header>'
            f'<nav class="tabs" role="tablist" aria-label="Report sections">{tabs}</nav><main>{panels}</main>'
            f'<script>{JS}</script></body></html>')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--insights", required=True)
    ap.add_argument("--out", default=f"{DEFAULT_DIR}/claude-prompt-insights.html")
    ap.add_argument("--extra-redact", action="append", default=[])
    a = ap.parse_args()
    try:
        S = json.loads(Path(a.summary).read_text())
        I = json.loads(Path(a.insights).read_text())
    except Exception as e:
        print(f"ERROR: cannot read inputs: {e}", file=sys.stderr)
        return 1
    extra = compile_extra(a.extra_redact)
    I = redact_tree(I, extra)
    S = redact_tree(S, extra)
    page = build(S, I)
    # Links the reader clicks (<a href>) are fine; anything the page would fetch on its own is not.
    if re.search(r"""<(?:script|img|iframe|source|video|audio|embed|object|link)\b[^>]*\b(?:src|href|data)\s*=\s*["']?\s*(?:https?:)?//|url\(\s*["']?(?:https?:)?//|@import""", page, re.I):
        print("ERROR: generated page would load external resources; refusing to write.", file=sys.stderr)
        return 2
    n_ver = len(re.findall(r"verbatim quote checked", page))
    n_bad = len(re.findall(r"not found in transcript|partly found", page))
    n_wk = len(I.get("weaknesses") or [])
    print(f"Quotes: {n_ver} verified, {n_bad} flagged, {n_wk - n_ver - n_bad} unchecked or behaviour-only, of {n_wk} weaknesses.")
    missing = [k for k in ("quick_win", "techniques", "templates", "action_plan") if not I.get(k)]
    out = Path(a.out)
    guard = ensure_output_dir(out.parent)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB), offline-safe, {len(PANELS)} tabs | {guard}")
    if missing:
        print("WARNING: insights.json is missing: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
