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
import base64
import html
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the installed skill folder free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
from history import ENV_VAR, resolve_history_dir, snapshot, stamp_of  # noqa: E402
from outdir import DEFAULT_DIR, ensure_output_dir  # noqa: E402
from pricing import DISCLAIMER, PRICES_AS_OF, PRICING_URL  # noqa: E402
from redact import compile_extra, redact  # noqa: E402

# Official Claude Code prompt library, shipped with the skill (assets/prompt-library.json).
_LIB_DATA = json.loads((Path(__file__).resolve().parent.parent / "assets" / "prompt-library.json").read_text(encoding="utf-8"))
LIB_META, LIB_SOURCES, LIBRARY = _LIB_DATA["library"], _LIB_DATA["sources"], _LIB_DATA["prompts"]
LIB = {p["id"]: p for p in LIBRARY}
# Logo shipped with the skill (assets/logo.png), embedded as a data URI so the report stays one offline file.
_LOGO = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
LOGO_HTML = ('<img src="data:image/png;base64,' + base64.b64encode(_LOGO.read_bytes()).decode("ascii")
             + '" alt="Claude Code prompt insights" width="280" height="95">') if _LOGO.is_file() else "Claude Code prompt insights"

# Multi-step playbooks (RPI) with a dedicated prompt per step, shipped with the skill.
PLAYBOOKS = {k: v for k, v in json.loads((Path(__file__).resolve().parent.parent / "assets" / "technique-playbooks.json")
                                          .read_text(encoding="utf-8")).items() if not k.startswith("_")}


def link(label, url) -> str:
    if not url:
        return esc(label)
    return f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">{esc(label)}</a>'


def prompt_origin(p) -> str:
    """Where a library prompt comes from: the library page, and the Anthropic page the entry is tagged with."""
    s = LIB_SOURCES.get(p.get("source"), {})
    out = link(LIB_META["name"], LIB_META["url"])
    if s:
        out += " &middot; from " + link(s["label"], s.get("url"))
    return out


# Colour roles: blue = actions and links only; red and green = removed and added text (and bad/good status);
# amber = warnings only. One neutral ladder (bg, card, code) with clear steps in both themes.
LIGHT = ("--bg:#f7f8f9;--fg:#14171a;--muted:#5b636b;--card:#fff;--line:#dfe3e7;--code:#eef0f2;"
         "--accent:#1d4ed8;--accent-rgb:29 78 216;--accent-bg:#eaf0ff;"
         "--good:#166534;--ins-bg:#e3f4e8;--bad:#b42318;--del-bg:#fde8e6;--warn:#92400e;--warn-bg:#fdf1d8")
DARK = ("--bg:#0e1012;--fg:#e8eaed;--muted:#98a1aa;--card:#16191c;--line:#272c31;--code:#1e2227;"
        "--accent:#7aa7ff;--accent-rgb:122 167 255;--accent-bg:#172036;"
        "--good:#6ee7a0;--ins-bg:#12301f;--bad:#ff8f86;--del-bg:#3a1816;--warn:#fbbf24;--warn-bg:#2e2410")

# Theme: follows the system by default; the toggle in the header forces light or dark and is remembered.
CSS = (":root{" + LIGHT + "}\n"
       "@media (prefers-color-scheme:dark){:root:not([data-theme=\"light\"]){" + DARK + "}}\n"
       ":root[data-theme=\"dark\"]{" + DARK + "}\n"
       ":root[data-theme=\"light\"]{" + LIGHT + "}\n") + """
:root{--serif:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 var(--sans)}
header.top{max-width:980px;margin:0 auto;padding:22px 16px 8px;display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
header.top h1{font:600 26px/1.2 var(--serif);margin:0 0 4px;letter-spacing:-.01em}
header.top h1 img{display:block;max-width:100%;height:auto;background:#fff;border:1px solid var(--line);border-radius:10px}
.themebtn{appearance:none;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:6px 12px;font:inherit;font-size:13px;cursor:pointer;white-space:nowrap}
.themebtn:hover{background:var(--code)}
a{color:var(--accent)}
.tabs{position:sticky;top:0;z-index:10;background:var(--card);border-bottom:1px solid var(--line);display:flex;gap:2px;overflow-x:auto;padding:6px 12px}
.tabs button{appearance:none;border:0;background:none;color:var(--muted);padding:8px 12px;border-radius:8px;white-space:nowrap;font:inherit;font-size:14px;cursor:pointer}
.tabs button:hover{background:var(--code);color:var(--fg)}
.tabs button[aria-selected=true]{background:var(--accent-bg);color:var(--accent);font-weight:600}
.tabs .badge{display:inline-block;min-width:18px;margin-left:6px;padding:0 6px;border-radius:99px;background:var(--code);color:var(--muted);font-size:12px;font-weight:600;text-align:center}
.tabs button[aria-selected=true] .badge{background:var(--card);color:var(--accent)}
@media(max-width:760px){.tabs{-webkit-mask-image:linear-gradient(to right,#000 calc(100% - 28px),transparent);mask-image:linear-gradient(to right,#000 calc(100% - 28px),transparent)}}
.tabs button:focus-visible,a:focus-visible,button.copy:focus-visible,.themebtn:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
main{max-width:980px;margin:0 auto;padding:8px 16px 72px}
.js .panel{display:none}.js .panel.active{display:block}
.ph{font:600 22px/1.2 var(--serif);margin:24px 0 10px}
.js .panel>.ph{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
h3{font:600 20px/1.25 var(--serif);margin:32px 0 10px;letter-spacing:-.005em}h4{margin:0 0 6px;font-size:13px;font-weight:600;color:var(--muted)}
.sub{color:var(--muted);margin:0 0 12px}
.card p,.card li,.callout,.prose li,.prose p,.quickwin p,.doctor{max-width:70ch}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:10px 0}
.prose{margin:8px 0;padding-left:20px}.prose li{margin:6px 0}
.meta{display:flex;flex-wrap:wrap;gap:4px 28px;margin:4px 0 16px}.meta div{display:flex;gap:6px}.meta dt{color:var(--muted)}.meta dd{margin:0;font-weight:600}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px 24px;margin:8px 0}.facts div{border-top:2px solid var(--line);padding-top:8px}
.facts dt{color:var(--muted);font-size:13px;order:2}.facts dd{margin:0;font:600 30px/1.1 var(--serif)}.facts div{display:flex;flex-direction:column}
.callout{border-left:4px solid var(--accent);background:var(--card);padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0}
.callout.warn{border-left-color:var(--warn);background:var(--warn-bg)}
.doctor{border-left:4px solid var(--accent);background:var(--card);padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0}
.quickwin{background:var(--accent-bg);border:2px solid var(--accent);border-radius:14px;padding:22px 26px;margin:16px 0 28px}
.quickwin .label{font-size:13px;font-weight:600;color:var(--accent)}
.quickwin h2{font:600 30px/1.15 var(--serif);margin:6px 0 10px;letter-spacing:-.01em}
.quickwin p{font-size:17px;margin:0 0 6px}
.quickwin .codebox{background:var(--card)}
.codebox{border:1px solid var(--line);border-radius:8px;background:var(--code);margin:10px 0;overflow:hidden}
.codebar{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:4px 6px 4px 12px;border-bottom:1px solid var(--line);font-size:12px;color:var(--muted)}
.codebox pre{margin:0;border-radius:0;background:none;padding:12px 14px;font-size:14px}
button.copy{font:inherit;font-size:12px;padding:3px 10px;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:6px;cursor:pointer}
button.copy:hover{background:var(--code)}
.tag{display:inline-block;font-size:12px;padding:1px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted);margin-right:4px}
.chgs{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:12px 0 6px}
.chg{border:1px solid var(--line);border-top-width:4px;border-radius:8px;padding:10px 12px;background:var(--card)}
.chg.good{border-top-color:var(--good)}.chg.bad{border-top-color:var(--bad)}.chg.flat{border-top-color:var(--line)}
.chg-l{font-size:13px;color:var(--muted);min-height:2.6em}.chg-v{font:600 28px/1.2 var(--serif);margin:4px 0}.chg-d{font-size:13px;color:var(--muted)}
.chg.good .chg-a,.chg.good .chg-d{color:var(--good)}.chg.bad .chg-a,.chg.bad .chg-d{color:var(--bad)}
.dl{font-size:12px;font-weight:600;margin-left:4px;white-space:nowrap}.dl.good{color:var(--good)}.dl.bad{color:var(--bad)}
.tag.good{color:var(--good);border-color:var(--good)}.tag.bad{color:var(--bad);border-color:var(--bad)}.tag.warn{color:var(--warn);border-color:var(--warn)}
.ba{display:grid;gap:12px;grid-template-columns:1fr 1fr;margin:10px 0}@media(max-width:700px){.ba{grid-template-columns:1fr}}
.ba>div{border-radius:6px;padding:10px 12px}
.ba .before{background:var(--del-bg);border-left:3px solid var(--bad)}.ba .after{background:var(--ins-bg);border-left:3px solid var(--good)}
.ba pre{background:none;padding:0;margin:4px 0 0}
del{text-decoration:line-through;text-decoration-color:var(--bad);text-decoration-thickness:1.5px}
ins{text-decoration:none;font-weight:700;border-bottom:2px solid var(--good)}
pre,code{font-family:var(--mono);font-size:13px}
pre{background:var(--code);padding:10px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;margin:6px 0}
.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600;font-size:13px}
td small{display:block;color:var(--muted);font-size:12px;margin-top:2px}
.scores{margin:8px 0 4px}.srow{margin:14px 0}.shead{display:flex;justify-content:space-between;gap:12px;font-weight:600}
.shead .sval{font-variant-numeric:tabular-nums;color:var(--muted);font-weight:600}
.strack{height:10px;border-radius:5px;background:var(--code);margin:6px 0 4px;position:relative;overflow:hidden}
.strack i{display:block;height:100%;border-radius:5px;background:var(--accent)}
.strack:after{content:"";position:absolute;inset:0;background:repeating-linear-gradient(to right,transparent 0,transparent calc(20% - 2px),var(--card) calc(20% - 2px),var(--card) 20%)}
.snote{margin:0;color:var(--muted);font-size:14px;max-width:70ch}
.bar{display:grid;grid-template-columns:150px 1fr 90px;gap:8px;align-items:center;margin:5px 0;font-size:14px}
.bar i{display:block;height:12px;border-radius:4px;background:var(--accent)}.bar span.v{color:var(--muted);text-align:right;font-size:13px}
.heat{background:rgb(var(--accent-rgb)/calc(var(--h,0)*.35))}
.muted{color:var(--muted)}.na{color:var(--muted);font-style:italic}
ul.check{list-style:none;padding:0}ul.check li{padding:4px 0}ul.check li:before{content:"\\2610  ";color:var(--muted)}
.cols{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
details{margin:8px 0}summary{cursor:pointer;color:var(--accent)}
.next{margin-top:24px}.next a{color:var(--accent);cursor:pointer}
.srcs{display:flex;flex-wrap:wrap;gap:2px 14px;margin:8px 0 0;font-size:13px;color:var(--muted)}
@media print{:root,:root[data-theme]{""" + LIGHT + """}.tabs,.themebtn,button.copy,.next{display:none}.js .panel{display:block!important}
.js .panel>.ph{position:static;width:auto;height:auto;clip:auto}.card,.ba>div{break-inside:avoid}}
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
     "Three separate sessions, each ending in a file. Research documents what exists (no opinions, no edits). Plan turns it into phased steps "
     "with success criteria that you review. Implement follows the plan mechanically, ticking checkboxes. A dedicated prompt for each step is below.",
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
    ("hooks", "Enforce mechanical rules with hooks",
     "A hook in settings.json runs a command at a fixed point (after an edit, before a tool call, when Claude stops), every time. "
     "CLAUDE.md lines are advice the model can miss; a hook cannot be skipped.",
     "A rule you can check with a command (format, run tests, never touch a path) is still broken after it went into CLAUDE.md."),
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
    "permissions": ("Configure permissions: allow, ask and deny rules", CC + "permissions"),
    "settings": ("Claude Code settings files", CC + "settings"),
    "pricing": ("Claude API pricing (the list prices behind the cost estimate)", PRICING_URL),
    "prompt-library": ("Prompt library (official Claude Code prompts)", CC + "prompt-library"),
    "prompting": ("Prompting best practices (Claude Platform docs)",
                  "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices"),
    "costs": ("Manage costs effectively (reduce token usage)", CC + "costs#reduce-token-usage"),
    "prompt-caching": ("How Claude Code uses prompt caching", CC + "prompt-caching"),
    "context-window": ("Explore the context window", CC + "context-window"),
    "autocompact": ("Set the auto-compact window", CC + "model-config#set-the-auto-compact-window"),
    "context-eng": ("Effective context engineering for AI agents (Anthropic engineering)",
                    "https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents"),
}
# Source ids that go with each technique in the catalogue.
TECH_SOURCES = {
    "rpi": ["plan", "modes", "workflows"], "plan-mode": ["plan", "modes"], "interview": ["interview"],
    "staged": ["plan", "best-practices"], "verify-loop": ["verify"], "builder-critic": ["sub-agents", "best-practices"],
    "repro-first": ["verify", "workflows"], "subagent-research": ["investigate", "sub-agents"],
    "context-hygiene": ["context", "context-eng"], "standing-rules": ["claude-md", "memory"],
    "pattern-reference": ["prompting"], "deep-thinking": ["prompting", "model-config"], "hooks": ["hooks", "settings"],
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
    (r"permission|allow rule|allowlist|auto mode|approval", ["permissions"]),
    (r"\bcost|\bprice|spend|\$\d|token budget", ["pricing"]), (r"\beffort\b", ["model-config"]),
]


def source_anchor(i) -> str:
    t, u = SOURCES[i]
    return f'<a href="{html.escape(u)}" target="_blank" rel="noopener noreferrer">{html.escape(t)}</a>'


def source_links(ids) -> str:
    out = [source_anchor(i) for i in dict.fromkeys(ids) if i in SOURCES]
    return f'<div class="srcs"><span>Sources</span>{"".join(out)}</div>' if out else ""


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


def usd(x) -> str:
    """Cost figures always carry a tilde: they are estimates, never a bill."""
    if x is None:
        return "n/a"
    try:
        v = float(x)
    except Exception:
        return esc(x)
    return f"~${v:,.2f}" if v >= 0.01 or v == 0 else "~<$0.01"


def cost_meta(S) -> dict:
    c = S["aggregates"].get("cost") or {}
    return {"source": c.get("source") or PRICING_URL, "as_of": c.get("prices_as_of") or PRICES_AS_OF,
            "disclaimer": c.get("disclaimer") or DISCLAIMER, "custom": c.get("custom_prices")}


def cost_note(S, short=False) -> str:
    """The estimate disclaimer, with a link to the pricing page the numbers come from."""
    m = cost_meta(S)
    link = f'<a href="{esc(m["source"])}" target="_blank" rel="noopener noreferrer">Claude API pricing page</a>'
    custom = " Prices from your --prices file replaced the list price for some models." if m["custom"] else ""
    if short:
        return (f'<p class="muted" style="font-size:13px">Estimate at list prices from the {link} (as of {esc(m["as_of"])}). '
                f"Not your actual cost.{custom}</p>")
    return (f'<div class="callout warn"><b>Cost is an estimate, not your bill.</b> Token counts from your transcripts are '
            f'multiplied by the Claude API list prices on the {link} (copied {esc(m["as_of"])}). What you really pay depends on '
            f"your plan: a Claude subscription, discounts, credits or a cloud provider's price list all change it.{custom}</div>")


def sid(s_id, title=None) -> str:
    """Session cell: short id plus the session title Claude Code generated (raw HTML)."""
    t = f"<small>{esc(title)}</small>" if title else ""
    return f"{esc(str(s_id or '')[:8])}{t}"


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


def copybox(id_, text, label="") -> str:
    """A code block with a copy toolbar inside it (no floating button)."""
    return (f'<div class="codebox"><div class="codebar"><span>{esc(label)}</span>'
            f'<button class="copy" data-target="{id_}">Copy</button></div><pre id="{id_}">{esc(text)}</pre></div>')


def copy_cell(id_, text) -> str:
    """Text in a table cell with an inline Copy button (for suggestions that sit in a table)."""
    return f'<span id="{id_}">{esc(text)}</span> <button class="copy" data-target="{id_}">Copy</button>'


def hook_box(id_, hook: dict) -> str:
    """A proposed hook as the settings.json block to paste (shape from the Claude Code hooks guide)."""
    block = {"hooks": {hook.get("event") or "PostToolUse": [
        {"matcher": hook.get("matcher", ""), "hooks": [{"type": "command", "command": hook.get("command", "")}]}]}}
    why = f'<p class="muted" style="font-size:14px">{esc(hook["why"])}</p>' if hook.get("why") else ""
    return why + copybox(id_, json.dumps(block, indent=2), "Merge into .claude/settings.json (project) or ~/.claude/settings.json")


def redline(before: str, after: str) -> tuple:
    """Word-level markup: removed words struck through in the before text, added words marked in the after text.
    Skipped when the two texts share too little for a word diff to say anything."""
    import difflib
    a, b = (before or "").split(), (after or "").split()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if not a or not b or sm.ratio() < 0.25:
        return esc(before), esc(after)
    ob, oa = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            ob.append(esc(" ".join(a[i1:i2])))
            oa.append(esc(" ".join(b[j1:j2])))
        else:
            if i2 > i1:
                ob.append("<del>" + esc(" ".join(a[i1:i2])) + "</del>")
            if j2 > j1:
                oa.append("<ins>" + esc(" ".join(b[j1:j2])) + "</ins>")
    return " ".join(ob), " ".join(oa)


def score_bars(scores) -> str:
    """scores: list of (label, value 0..5, note). Sorted weakest first so the priority is the first row."""
    if not scores:
        return na("No scores")
    rows = ""
    for lab, val, note in sorted(scores, key=lambda x: float(x[1])):
        v = max(0.0, min(5.0, float(val)))
        rows += (f'<div class="srow"><div class="shead"><span>{esc(lab)}</span><span class="sval">{v:.1f} / 5</span></div>'
                 f'<div class="strack" role="img" aria-label="{esc(lab)} {v:.1f} out of 5"><i style="width:{v / 5 * 100:.0f}%"></i></div>'
                 + (f'<p class="snote">{esc(note)}</p>' if note else "") + "</div>")
    return f'<div class="scores">{rows}</div><p class="sub">Scale 0 to 5, weakest first. Your judgment calls after reading the flagged turns, not a measurement.</p>'


def status_chip(status) -> str:
    cls = {"healthy": "good", "stale": "warn", "bloated": "warn", "thin": "warn", "at-risk": "warn"}.get(str(status).lower(), "")
    return f'<span class="tag {cls}">{esc(status)}</span>'


FILE_STATUSES = ("healthy", "stale", "bloated", "thin", "at-risk")


def effective_status(f, find) -> str:
    """Model finding wins; otherwise derive from the script's own flags so every file lands in one status."""
    st = str((find.get(f["path"]) or {}).get("status") or "").lower()
    if st in FILE_STATUSES:
        return st
    h = f["hints"]
    if f["possibly_dead_references"]:
        return "at-risk"
    for hint, status in (("bloated?", "bloated"), ("thin?", "thin"), ("untouched-90d+", "stale")):
        if hint in h:
            return status
    return "healthy"


def folder_label(f) -> str:
    """~/.claude/ (global files) is one working folder; plugin files are grouped; the rest by project."""
    scope = f["scope"]
    return "~/.claude/" if scope == "global" else ("Plugins (managed)" if scope == "plugin" else scope)


def delta(now, before, up_is_good=True) -> str:
    """'+2' / '-1' next to a number: green when it moved the better way, red when worse; nothing if unchanged or unknown.
    up_is_good=None: neutral grey."""
    if before is None or now == before:
        return ""
    d = now - before
    cls = "" if up_is_good is None else ("good" if (d > 0) == up_is_good else "bad")
    return f' <span class="dl {cls}" title="was {before} at the last scan">{d:+d}</span>'


def file_health_by_folder(S, find) -> str:
    folders = {}
    for f in S["agent_files"]:
        counts = folders.setdefault(folder_label(f), dict.fromkeys(FILE_STATUSES, 0))
        counts[effective_status(f, find)] += 1
    if not folders:
        return na("No agent files found")
    prev = None
    pf = (S.get("followup") or {}).get("previous_files")
    if pf is not None:
        prev = {}
        for f in pf:
            counts = prev.setdefault(folder_label(f), dict.fromkeys(FILE_STATUSES, 0))
            counts[effective_status(f, {f.get("path"): {"status": f.get("status")}})] += 1
    order = sorted(folders, key=lambda k: (k != "~/.claude/", k))
    rows = []
    for k in order:
        c = folders[k]
        p = prev.get(k, dict.fromkeys(FILE_STATUSES, 0)) if prev is not None else None
        rows.append([esc(k), f"{sum(c.values())}" + (delta(sum(c.values()), sum(p.values()), None) if p else "")]
                    + [f"{c[st]}" + (delta(c[st], p[st], st == "healthy") if p else "") for st in FILE_STATUSES])
    return table(["Working folder", "Files"] + [st.capitalize() for st in FILE_STATUSES], rows, raw_cols=range(2 + len(FILE_STATUSES)))


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

def flagged_files(S, I):
    find = {f.get("path"): f for f in (I.get("agent_files") or {}).get("findings", [])}
    out = [f for f in S["agent_files"] if f["hints"] or f["possibly_dead_references"]]
    out += [f for f in S["agent_files"] if find.get(f["path"], {}).get("status") in ("stale", "bloated", "thin", "at-risk") and f not in out]
    return out


def fmt_metric(key, v) -> str:
    if v is None:
        return "-"
    return usd(v) if key == "cost_per_session" else f"{v:g}"


def change_tiles(metrics, lo=4, hi=6) -> str:
    """4 to 6 tiles for the biggest changes: arrow = direction of the number, colour = better (green) or worse (red)."""
    cand = []
    for m in metrics:
        b, a = m.get("before"), m.get("after")
        if b is None or a is None:
            continue
        rel = abs(a - b) / max(abs(a), abs(b), 1e-9)
        cand.append((rel if rel >= 0.05 else 0, bool(m.get("quick_win")), rel, m))
    # biggest relative change first; metrics with a known good direction win ties; flat ones only fill up to `lo`
    cand.sort(key=lambda c: (c[0] > 0, c[0], c[3].get("better") is not None, c[1]), reverse=True)
    picked = [c for c in cand if c[0] > 0][:hi]
    picked += [c for c in cand if c[0] == 0][:max(0, lo - len(picked))]
    if not picked:
        return ""
    tiles = ""
    for _, qw, _, m in picked:
        b, a, key = m["before"], m["after"], m.get("key")
        d = a - b
        if abs(d) < 1e-9 or (abs(d) / max(abs(a), abs(b), 1e-9)) < 0.05:
            cls, arrow, word = "flat", "&rarr;", "about the same"
        else:
            arrow = "&uarr;" if d > 0 else "&darr;"
            if m.get("better") is None:
                cls, word = "flat", "changed"
            else:
                good = (d > 0) == (m["better"] == "higher")
                cls, word = ("good", "better") if good else ("bad", "worse")
        pct = (m.get("label") or "").rstrip().endswith("(%)")
        amount = (f"{d:+.1f} pts" if pct else (f"{'+' if d > 0 else '-'}${abs(d):.2f}" if key == "cost_per_session" else f"{d:+.2g}")) if cls != "flat" or d else ""
        label = re.sub(r"\s*\(%\)", "", m.get("label") or "")
        tiles += (f'<div class="chg {cls}"><div class="chg-l">{esc(label)}</div>'
                  f'<div class="chg-v"><span class="chg-a" aria-hidden="true">{arrow}</span> {esc(fmt_metric(key, a))}{"%" if pct else ""}</div>'
                  f'<div class="chg-d">{esc(word)}{(" · " + esc(amount)) if amount else ""}<br>was {esc(fmt_metric(key, b))}{"%" if pct else ""}'
                  f'{" · quick win" if qw else ""}</div></div>')
    return ('<div class="chgs">' + tiles + "</div>"
            '<p class="muted" style="font-size:13px">Arrow: which way the number moved. Green: better. Red: worse. Grey: no clear direction or no real change.</p>')


def followup_html(S, I) -> str:
    fu = S.get("followup")
    if not fu:
        return ""
    pr = fu.get("previous_report") or {}
    when = str(pr.get("generated_at") or "?")[:10]
    body = (f'<h3>Since your last report</h3><p class="sub">Previous report from {esc(when)}, built from '
            f'{esc(pr.get("sessions_analyzed", "?"))} sessions. {esc(fu.get("sessions_since", 0))} session(s) in this run started after it.</p>')
    if I.get("followup_note"):
        body += f'<div class="callout"><b>What changed.</b> {esc(I["followup_note"])}</div>'
    rows = []
    for m in fu.get("metrics") or []:
        b, a = m.get("before"), m.get("after")
        if b is None or a is None:
            tag = '<span class="tag">no comparison</span>'
        elif abs(a - b) < 1e-9:
            tag = '<span class="tag">same</span>'
        elif m.get("better") is None:
            tag = '<span class="tag">changed</span>'
        else:
            good = (a > b) == (m["better"] == "higher")
            tag = f'<span class="tag {"good" if good else "bad"}">{"better" if good else "worse"}</span>'
        label = esc(m.get("label")) + (' <span class="tag good">quick win</span>' if m.get("quick_win") else "")
        rows.append([label, esc(fmt_metric(m.get("key"), b)), esc(fmt_metric(m.get("key"), a)), tag])
    body += change_tiles(fu.get("metrics") or [])
    if rows:
        body += ("<details><summary>All measures compared</summary>"
                 + table(["Measure", "Before (last report's sample)", "Since then", ""], rows, raw_cols=(0, 1, 2, 3)) + "</details>")
    adv = fu.get("advice") or []
    if adv:
        cls = {"landed": "good", "partly": "warn", "not found": "bad", "target missing": "warn"}
        body += "<h4 style=\"margin-top:16px\">Did last report's advice land in your files?</h4>" + table(
            ["Advice", "Kind", "Target", "Status"],
            [[esc(x.get("item")), esc(x.get("kind")), esc(x.get("target")),
              f'<span class="tag {cls.get(x.get("status"), "")}">{esc(x.get("status"))}</span>'
              + (f'<small>{esc(x["where"])}</small>' if x.get("where") else "")] for x in adv], raw_cols=(0, 1, 2, 3))
    body += f'<p class="muted" style="font-size:13px">{esc(fu.get("note", ""))}</p>'
    return body


def sample_html(S) -> str:
    """How many sessions the report covers and how to change that."""
    M = S["meta"]
    F = M.get("filters") or {}
    n = M["sessions_analyzed"]
    avail = M.get("sessions_in_filter") or M["sessions_available_total"]
    what = f"{n} session{'s' if n != 1 else ''}"
    if M.get("date_range"):
        what += f' from {M["date_range"][0]} to {M["date_range"][1]}'
    chosen = []
    if F.get("limit"):
        chosen.append(f'the {F["limit"]} most recent sessions')
    else:
        chosen.append("all sessions")
    if F.get("since_days"):
        chosen.append(f'from the last {F["since_days"]} day{"s" if F["since_days"] != 1 else ""}')
    if F.get("project"):
        chosen.append(f'of projects matching "{F["project"]}"')
    more = ""
    left = avail - n - (M.get("sessions_self_excluded") or 0)
    if left > 0:
        more = f" {left} more {'matching ' if (F.get('project') or F.get('since_days')) else ''}session{'s' if left != 1 else ''} exist and are not included."
    out = ('<div class="card"><p><b>Included in this report:</b> ' + esc(what) + ". Selection: " + esc(" ".join(chosen)) + "." + esc(more) + "</p>"
           "<p><b>Change the sample.</b> Ask Claude Code in plain language, or pass a flag to <code>analyze_sessions.py</code> and build the report again.</p>"
           + '<ul class="prose">' + "".join(f"<li>{x}</li>" for x in [
                  "More or fewer sessions: <code>--limit N</code> (<code>--limit 0</code> = every session). Ask for example: \u201cRun prompt insights on my last 40 sessions.\u201d",
                  "A time window: <code>--since-days N</code> (default 7 days; any N works). Ask for example: \u201cRun prompt insights on the last 30 days.\u201d",
                  "One project only: <code>--project TEXT</code>. The follow-up then compares with earlier reports of the same project."]) + "</ul>"
           + copybox("smp1", "Run prompt insights on my last 40 sessions", "Ask Claude Code")
           + copybox("smp2", "Run prompt insights on the last 30 days", "Ask Claude Code") + "</div>")
    return out


def p_overview(S, I):
    A, T, M = S["aggregates"], S["aggregates"]["totals"], S["meta"]
    body = ""
    sessions = S.get("sessions", [])
    heur = sum(1 for s in sessions if s.get("task_type_source") == "heuristic")
    flt = (M.get("filters") or {}).get("project")
    pool = (f'{M["sessions_analyzed"]} in this project' if flt
            else f'{M["sessions_analyzed"]} of {M["sessions_available_total"]} sessions')
    meta = [("Sample", pool)]
    if M.get("date_range"):
        meta.append(("Period", f'{M["date_range"][0]} to {M["date_range"][1]}'))
    if flt:
        meta.append(("Project", flt))
    meta.append(("Task labels", "reviewed" if sessions and heur == 0 else f"{heur} of {len(sessions)} still guessed"))
    body += '<dl class="meta">' + "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in meta) + "</dl>"
    if M["sessions_analyzed"] < 10:
        body += (f'<div class="callout warn"><b>Small sample ({M["sessions_analyzed"]} sessions).</b> Read these findings as leads, not statistics, '
                 "and re-run after more sessions.</div>")

    qw = I.get("quick_win")
    if qw:
        mins = f', about {esc(qw.get("minutes"))} minutes' if qw.get("minutes") else ""
        body += f'<div class="quickwin"><div class="label">Quick win{mins}</div><h2>{esc(qw.get("title"))}</h2>'
        if qw.get("why"):
            body += f'<p>{esc(qw["why"])}</p>'
        if qw.get("do_this"):
            body += copybox("qw", qw["do_this"], "Paste into Claude Code or your CLAUDE.md")
        if qw.get("evidence"):
            body += f'<p class="muted" style="font-size:14px">Evidence: {esc(qw["evidence"])}</p>'
        body += "</div>"
    else:
        body += '<div class="callout warn"><b>No quick win provided.</b> insights.json should contain a <code>quick_win</code> object.</div>'

    body += followup_html(S, I)
    if I.get("top_change"):
        body += f'<div class="callout"><b>Highest-impact change.</b> {esc(I["top_change"])}</div>'
    heads = I.get("headline_insights") or []
    body += "<h3>What the sessions show</h3>" + (
        '<ul class="prose">' + "".join(f"<li>{esc(h)}</li>" for h in heads) + "</ul>" if heads else na("headline_insights missing"))

    n_rep = len(A.get("repeated_instructions") or [])
    facts = [
        (T["avg_user_turns"], "typed prompts per session"),
        (f"{T['pct_sessions_with_correction_or_interrupt']}%", "sessions with a correction or interrupt"),
        (len(flagged_files(S, I)), "agent files flagged"),
        (n_rep, "instructions repeated across sessions"),
    ]
    vf = (A.get("outcomes") or {}).get("verified_finish_pct")
    if vf is not None:
        facts.append((f"{vf}%", "sessions with edits that ended on a passing check"))
    c = A.get("cost")
    if c:
        facts.append((usd(c.get("total_usd")), "estimated cost at API list prices (not your bill)"))
    body += "<h3>Numbers that matter</h3><dl class=\"facts\">" + "".join(
        f"<div><dt>{esc(l)}</dt><dd>{esc(v)}</dd></div>" for v, l in facts) + "</dl>"
    if c:
        body += cost_note(S, short=True)
    body += '<p class="sub">Everything else measured is on the Method tab.</p>'
    techs = I.get("techniques") or []
    if techs:
        t = techs[0]
        body += ('<h3>Technique to try</h3><div class="card">'
                 f'<b>{esc(t.get("name"))}</b>'
                 f'<p>{esc(t.get("why_for_you", ""))}</p>'
                 '<p class="next" style="margin:8px 0 0"><a data-goto="techniques" href="#techniques">See the recommended techniques</a></p></div>')
    return "Overview", body


def p_prompts(S, I):
    pq = I.get("prompt_quality", {})
    body = ""
    if pq.get("scores"):
        body += score_bars([(x.get("criterion", "?"), x.get("score", 0), x.get("note", "")) for x in pq["scores"]])
    else:
        h = S["aggregates"]["prompt_quality_heuristic"]
        names = {"has_goal_why": "Goal and why", "has_scope": "Scope and constraints", "has_context_pointer": "Context pointers",
                 "has_done_criteria": "Done criteria", "asks_plan_first": "Plan first"}
        body += '<p class="sub">Regex heuristic on first prompts (insights.json had no scores).</p>'
        body += bars([(names[k], v, f"{v}") for k, v in h["pct"].items()], "%")
    body += "<h3>Top recurring weaknesses</h3>"
    for i, w in enumerate(I.get("weaknesses", []), 1):
        sids = w.get("evidence_sessions", [])
        if w.get("before_kind") == "behavior":
            tag = '<span class="tag">behaviour, no prompt to quote</span>'
            bhtml, ahtml = esc(w.get("before")), esc(w.get("after"))
        else:
            st, f, n = verify_quote(w.get("before", ""), sids, S)
            tag = {"verified": '<span class="tag good">verbatim quote checked</span>',
                   "partial": f'<span class="tag warn">partly found in transcript ({f}/{n})</span>',
                   "missing": '<span class="tag bad">not found in transcript: may be reconstructed</span>',
                   "unchecked": '<span class="tag">quote not checked</span>'}[st]
            bhtml, ahtml = redline(w.get("before", ""), w.get("after", ""))
        body += (f'<div class="card"><b>{i}. {esc(w.get("title"))}</b> {tag}'
                 f'<div class="ba"><div class="before"><h4>Your prompt</h4><pre>{bhtml}</pre></div>'
                 f'<div class="after"><h4>Rewritten <button class="copy" data-target="wk{i}">Copy</button></h4><pre id="wk{i}">{ahtml}</pre></div></div>'
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

        titles = {s["id"]: s.get("title") for s in S.get("sessions", [])}

        def side(k, label, cls):
            d = bw.get(k, {})
            t = next((v for i, v in titles.items() if d.get("session_id") and i.startswith(str(d["session_id"]))), None)
            return (f'<div><h4><span class="tag {cls}">{label}</span> {esc(d.get("session_id", ""))}'
                    f'{" · " + esc(t) if t else ""}</h4>'
                    f'<p><b>First prompt</b></p><pre>{esc(d.get("first_prompt", ""))}</pre>'
                    f'<p>{esc(d.get("what_happened", ""))}</p>{lst(d.get("prompt_traits", []))}</div>')
        lb = ("best", "worst") if comparable else ("smoother", "rougher")
        body += f'<div class="ba">{side("best", lb[0], "good")}{side("worst", lb[1], "bad")}</div>'
        if bw.get("key_difference"):
            body += f'<div class="callout"><b>Key difference.</b> {esc(bw["key_difference"])}</div>'
    else:
        A = S["aggregates"]
        pairs = A.get("best_worst_by_task") or {}
        cands = [x for v in pairs.values() for x in (v["best"], v["worst"])] or A["best_session_candidates"] + A["worst_session_candidates"]
        rows = [[sid(x["session_id"], x.get("title")), esc(x["task_type"]), esc(x["model"]), esc(x["user_turns"]),
                 esc(x["friction_per_turn"]), esc(x["first_prompt"])] for x in cands]
        body += ('<p class="sub">Candidates by friction score (insights.json had no comparison).</p>'
                 + table(["Session", "Task", "Model", "Turns", "Friction/turn", "First prompt"], rows, raw_cols=range(6)))

    oc = S["aggregates"].get("outcomes")
    if oc and oc.get("by_task_type"):
        body += ("<h3>How sessions ended</h3><p class=\"sub\">Per task type: sessions that edited files, and how many of those ended "
                 "with a test, build, lint or type check that passed after the last edit (in the session or a subagent).</p>")
        body += table(["Task type", "Sessions", "With edits", "Ended on a passing check", "Committed", "Pushed", "Pull request"],
                      [[t, d["sessions"], d["with_edits"], f'{d["verified_finish"]} of {d["with_edits"]}' if d["with_edits"] else "-",
                        d["committed"], d["pushed"], d["with_pr"]] for t, d in oc["by_task_type"].items()])
        body += f'<p class="muted" style="font-size:13px">{esc(oc.get("note", ""))}</p>'
    return "Prompts", body


def playbook_html(key, pid, overrides=None) -> str:
    """Steps of a multi-step technique, each with its own copyable prompt. overrides: [{id, prompt}] from insights.json."""
    pb = PLAYBOOKS.get(key)
    if not pb:
        return ""
    ov = {o.get("id"): o.get("prompt") for o in overrides or [] if isinstance(o, dict) and o.get("prompt")}
    ovs = {o.get("id"): o.get("short") for o in overrides or [] if isinstance(o, dict) and o.get("short")}
    out = f'<div class="playbook"><p>{esc(pb["intro"])}</p>'
    out += '<p class="flow"><b>' + " &rarr; ".join(esc(x) for x in pb["flow"]) + "</b></p>"
    def prompts(ph, label):
        pid_ = f"{pid}-{ph['id']}"
        tailored = ph["id"] in ov or ph["id"] in ovs
        return (f'<p><b>One-liner</b> <span class="muted">(paste as is)</span></p>'
                + copybox(pid_ + "-s", ovs.get(ph["id"]) or ph["short"], f'{label} one-liner')
                + f'<details><summary>Full prompt{" (tailored to you)" if tailored else ""}, for a skill</summary>'
                + f'<p class="sub">Save it as a skill, for example <code>.claude/skills/{esc(ph["skill_name"])}/SKILL.md</code>, and run it as <code>/{esc(ph["skill_name"])}</code>.</p>'
                + copybox(pid_, ov.get(ph["id"]) or ph["prompt"], f'{label} full prompt') + "</details>")

    for n, ph in enumerate(pb["phases"]):
        out += (f'<div class="card"><b>{esc(ph["number"])} · {esc(ph["name"])}</b> <span class="tag">{esc(ph["goal"])}</span>'
                '<ul class="prose">'
                f'<li><b>Rule:</b> {esc(ph["rule"])}</li><li><b>Produces:</b> {esc(ph["output"])}</li>'
                f'<li><b>You check:</b> {esc(ph["you_check"])}</li><li><b>In Claude Code:</b> {esc(ph["tips"])}</li></ul>'
                + prompts(ph, ph["name"]) + "</div>")
    for ex in pb.get("extras") or []:
        out += (f'<div class="card"><b>{esc(ex["name"])}</b> <span class="tag">{esc(ex["when"])}</span>'
                + prompts(ex, "Iterate") + "</div>")
    if pb.get("skill_hint"):
        out += f'<div class="callout"><b>Make it a skill.</b> {esc(pb["skill_hint"])}</div>'
    out += (f'<p><b>Use it when:</b> {esc(pb["use_when"])}</p><p><b>Skip it when:</b> {esc(pb["skip_when"])}</p>'
            "<p><b>Common mistakes</b></p><ul class=\"prose\">" + "".join(f"<li>{esc(m)}</li>" for m in pb["mistakes"]) + "</ul>"
            f'<p class="muted" style="font-size:13px">{esc(pb["credit"])}</p></div>')
    return out


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
        if t.get("id") in PLAYBOOKS:
            body += playbook_html(t["id"], f"tq{i}", t.get("phases"))
        elif t.get("example_prompt"):
            body += f'<p><b>Example prompt</b></p>{copybox(f"tq{i}", t["example_prompt"])}'
        if t.get("evidence_sessions"):
            body += f'<p class="muted">Evidence: {esc(", ".join(t["evidence_sessions"]))}</p>'
        body += "</div>"
    body += official_prompts_html(I)
    shown = {r.get("id") for r in recs}
    for key, pb in PLAYBOOKS.items():
        if key not in shown:  # not recommended this time: keep the prompts one click away
            title = next((x[1] for x in TECHNIQUES if x[0] == key), key)
            body += f'<details><summary>{esc(title)}: a prompt for each step</summary>{playbook_html(key, "pbk-" + key)}</details>'
    body += (f'<details><summary>Technique catalog ({len(TECHNIQUES)})</summary>'
             + table(["Technique", "What it is", "Use it when"], [[t[1], t[2], t[3]] for t in TECHNIQUES]) + "</details>")
    body += (f'<details><summary>Official prompt library ({len(LIBRARY)})</summary>'
             f'<p class="sub">Every prompt from the Claude Code prompt library, copied into the skill (fetched {esc(LIB_META["fetched"])}). Replace the {{braces}} with your own terms.</p>'
             + table(["Phase", "Task", "Prompt", "Origin"], [[p["phase"], p["category"], p["prompt"], prompt_origin(p)] for p in LIBRARY], raw_cols=(3,)) + "</details>")
    return "Techniques", body


def official_prompts_html(I) -> str:
    """Prompts from the official library that fit this user. insights.json names them by id and supplies
    the filled-in text; the library text itself comes from assets/prompt-library.json, never from insights.json."""
    recs = [r for r in I.get("official_prompts") or [] if r.get("id") in LIB]
    if not recs:
        return ""
    body = ('<h3>Official prompts to try</h3><p class="sub">Taken from the '
            f'{source_anchor("prompt-library")} (bundled with this skill), filled in with your own project terms.</p>')
    for i, r in enumerate(recs):
        lp = LIB[r["id"]]
        body += (f'<div class="card"><span class="tag">{esc(lp["phase"])}</span><span class="tag">{esc(lp["category"])}</span>')
        if r.get("why_for_you"):
            body += f'<p><b>Why it fits you:</b> {esc(r["why_for_you"])}</p>'
        body += copybox(f"op{i}", r.get("prompt") or lp["prompt"], "Prompt library")
        body += f'<p class="muted">Origin: {prompt_origin(lp)}</p>'
        if r.get("evidence_sessions"):
            body += f'<p class="muted">Evidence: {esc(", ".join(r["evidence_sessions"]))}</p>'
        body += "</div>"
    return body


def p_agent_files(S, I):
    AF = I.get("agent_files", {})
    find = {f.get("path"): f for f in AF.get("findings", [])}
    body = f'<p>{esc(AF.get("update_pattern", ""))}</p>' if AF.get("update_pattern") else ""
    flagged = flagged_files(S, I)
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
        prev_roots = {r["project"]: r for r in (S.get("followup") or {}).get("previous_roots") or []}

        def yn(r, key, keys=None):
            now = any(r[k] for k in (keys or [key]))
            p = prev_roots.get(r["project"])
            was = any(p.get(k) for k in (keys or [key])) if p else None
            tag = "" if was is None or was == now else (' <span class="dl good">new</span>' if now else ' <span class="dl bad">gone</span>')
            return ("yes" if now else "no") + tag

        def num(r, key):
            p = prev_roots.get(r["project"])
            return f'{r[key]}' + (delta(r[key], p.get(key, 0)) if p else "")

        def mem(r):
            names = f' ({esc(", ".join(r.get("memory_note_names", [])[:4]))})' if r.get("memory_note_names") else ""
            return num(r, "memory_files") + names

        body += "<h3>Checked on disk</h3>" + table(
            ["Project", "Exists", "CLAUDE.md", "AGENTS.md", "Rules", "Subagents", "Skills", "Memory notes", "Sessions"],
            [[esc(r["project"]), yn(r, "exists"), yn(r, None, ["claude_md", "claude_local_md"]), yn(r, "agents_md"), num(r, "rules"),
              num(r, "agents"), num(r, "skills"), mem(r), f'{r["sessions"]}'] for r in roots], raw_cols=range(9))
        if prev_roots:
            body += '<p class="muted" style="font-size:13px">+/- compares with the last report\'s scan. Green: more files or notes. Red: fewer.</p>'
        elif S.get("followup") is None:
            body += '<p class="muted" style="font-size:13px">Changes since the last scan show here once a previous report exists.</p>'
    body += "<h3>File health</h3>" + file_health_by_folder(S, find)
    rows = []
    for f in S["agent_files"]:
        status = effective_status(f, find)
        if status == "healthy":
            continue
        fi = find.get(f["path"], {})
        meta = f'{folder_label(f)}, {f["kind"]}, modified {f["last_modified"][:10]}, {f["lines"]} lines, {f["sessions_after_last_edit"]} sessions since'
        evidence = fi.get("evidence") or ", ".join(f["possibly_dead_references"][:3]) or ", ".join(f["hints"])
        if fi.get("action"):
            evidence = f'{evidence}  Next: {fi["action"]}' if evidence else f'Next: {fi["action"]}'
        rows.append([f'{esc(f["path"])}<small>{esc(meta)}</small>', status_chip(status), esc(evidence)])
    if rows:
        body += "<h3>Files needing attention</h3>" + table(["File", "Status", "Evidence and next step"], rows, raw_cols=(0, 1, 2))
    ev = S["aggregates"]["agent_file_edit_events"]
    body += "<h3>Update timeline</h3>" + table(["Date", "Project", "File", "Via", "Calls"],
                                              [[e["date"], e["project"], e["path"] + ("" if e.get("on_disk", True) else "  (no longer on disk)"), e["tool"], e.get("calls", 1)] for e in ev])
    body += "<h3>Repeated corrections to capture</h3>"
    rc = AF.get("repeated_corrections", [])
    for i, r in enumerate(rc):
        hook = r.get("hook") if isinstance(r.get("hook"), dict) else None
        where = "enforce with a hook" if hook or r.get("enforcement") == "hook" else f'add to {r.get("target_file", "CLAUDE.md")}'
        body += (f'<div class="card"><b>{esc(r.get("theme"))}</b> '
                 f'<span class="tag">{esc(r.get("occurrences", ""))}x</span><span class="tag">{esc(where)}</span>')
        if r.get("proposed_line"):
            body += copybox(f"rc{i}", r.get("proposed_line"))
        if hook:
            body += hook_box(f"rch{i}", hook)
        body += "</div>"
    if not rc:
        auto = S["aggregates"]["repeated_corrections"]
        body += table(["Occurrences", "Sample", "Possibly covered by"],
                      [[r["occurrences"], copy_cell(f"arc{i}", r["representative"]), ", ".join(r["possibly_covered_by"]) or "-"] for i, r in enumerate(auto)], raw_cols=(1,)) if auto \
            else '<p class="na">No correction repeated across sessions in this sample.</p>'
    ri = S["aggregates"].get("repeated_instructions") or []
    if ri:
        body += "<h3>Instructions you repeat across sessions</h3><p class=\"sub\">Sentences that appear in two or more sessions: candidates for CLAUDE.md, a rule or a skill.</p>" + table(
            ["Sessions", "Example", "Already in"], [[len(r["sessions"]), copy_cell(f"ri{i}", r["example"]), ", ".join(r["possibly_covered_by"]) or "no agent file"] for i, r in enumerate(ri)], raw_cols=(1,))
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
    body += "<h3>Assistant messages by model</h3><p class=\"sub\">Main conversation + subagents.</p>" + bars(
        [(f, d["assistant_msgs"] + d.get("subagent_msgs", 0), f'{fmt_int(d["assistant_msgs"])} + {fmt_int(d.get("subagent_msgs", 0))}')
         for f, d in sorted(bm.items(), key=lambda kv: -(kv[1]["assistant_msgs"] + kv[1].get("subagent_msgs", 0)))])
    be = A.get("by_effort") or {}
    if be:
        body += ("<h3>Effort level</h3><p class=\"sub\">Assistant messages per effort level, main conversation + subagents. "
                 "Effort is set with /effort or per agent; higher effort thinks longer and costs more output tokens.</p>") + bars(
            [(e, d["main_msgs"] + d["subagent_msgs"], f'{fmt_int(d["main_msgs"])} + {fmt_int(d["subagent_msgs"])}') for e, d in be.items()])
    body += "<h3>Sessions by task type</h3>" + bars([(t, d["sessions"], str(d["sessions"])) for t, d in A["by_task_type"].items()])

    body += spend_html(S, I)
    body += context_html(S, I)

    body += "<h3>Tokens (measured)</h3><p class=\"sub\">Including subagents. The cost column is the list-price estimate above.</p>" + table(
        ["Model", "Sessions", "Input", "Output", "Cache read", "Cache write", "Est. cost"],
        [[f, d["sessions"], fmt_int(d["tokens"]["input"]), fmt_int(d["tokens"]["output"]), fmt_int(d["tokens"]["cache_read"]),
          fmt_int(d["tokens"]["cache_write"]), usd(d["estimated_cost_usd"])] for f, d in bm.items()])
    body += subagents_html(S)

    fams = sorted(f for f, d in bm.items() if d["sessions"])
    mx = max((c["avg_friction_per_turn"] for r in A["task_model_matrix"].values() for c in r.values()), default=0) or 1
    rows = ""
    for t, r in A["task_model_matrix"].items():
        rows += f"<tr><td>{esc(t)}</td>"
        for f in fams:
            c = r.get(f)
            if c:
                eff = ", ".join(f"{k} {v}" for k, v in (c.get("efforts") or {}).items() if k != "unknown")
                cost = f', {usd(c["avg_est_cost_usd"])}/session' if c.get("avg_est_cost_usd") is not None else ""
                rows += (f'<td class="heat" style="--h:{c["avg_friction_per_turn"] / mx:.2f}">n={c["sessions"]}<br>'
                         f'<span class="muted">{c["avg_user_turns"]} turns, f/t {c["avg_friction_per_turn"]}{esc(cost)}'
                         f'{"<br>effort: " + esc(eff) if eff else ""}</span></td>')
            else:
                rows += '<td class="muted">-</td>'
        rows += "</tr>"
    body += ("<h3>Task type x model: friction matrix</h3><p class=\"sub\">Darker = more friction per typed prompt (f/t). "
             "Cells with n&lt;3 are anecdotes, not evidence.</p>"
             f'<div class="tablewrap"><table><thead><tr><th>Task type</th>{"".join(f"<th>{esc(f)}</th>" for f in fams)}</tr></thead><tbody>{rows}</tbody></table></div>')
    titles = {s["id"]: s.get("title") for s in S.get("sessions", [])}

    def title_of(x):
        return next((v for i, v in titles.items() if x and i.startswith(str(x))), None)
    mism = MR.get("mismatches") or [{"session_id": m["session_id"], "task_type": m["task_type"], "model": m["model"],
                                     "effort": m.get("effort"), "issue": m["kind"], "suggestion": m["evidence"]}
                                    for m in A["model_mismatch_candidates"]]
    body += "<h3>Mismatches</h3>" + table(["Session", "Task", "Model", "Effort", "Issue", "Suggestion / evidence"],
                                          [[sid(m.get("session_id"), title_of(m.get("session_id"))), esc(m.get("task_type")), esc(m.get("model")),
                                            esc(m.get("effort") or "-"), esc(m.get("issue")), esc(m.get("suggestion"))] for m in mism],
                                          raw_cols=range(6))
    guide = MR.get("guide", [])
    body += "<h3>Model routing guide</h3>" + (table(["Task type", "Recommended model", "Effort", "Why", "Evidence"],
                                                    [[g.get("task_type"), g.get("recommended"), g.get("effort") or "-", g.get("why"), g.get("evidence")]
                                                     for g in guide]) if guide else na())
    body += "<h3>Rules of thumb</h3>" + lst(MR.get("rules_of_thumb", []))
    body += '<p class="muted">Available models change. Re-check this guide against the current model list (/model) before adopting it.</p>'
    return "Models & cost", body


PART_LABELS = {"cache_write": "Cache writes", "cache_read": "Cache reads", "output": "Output", "input": "Uncached input",
               "web_search": "Web searches"}


def spend_html(S, I) -> str:
    c = S["aggregates"].get("cost")
    if not c:
        return ""
    sp = I.get("spend") or {}
    body = "<h3>Estimated cost</h3>" + cost_note(S)
    if sp.get("headline"):
        body += f'<div class="callout"><b>Where the money goes.</b> {esc(sp["headline"])}</div>'
    facts = [(usd(c["total_usd"]), "total, estimated"), (usd(c["main_usd"]), "main conversations"),
             (usd(c["subagent_usd"]), "subagents and workflows"), (usd(c["per_session_avg_usd"]), "per session, average")]
    body += '<dl class="facts">' + "".join(f"<div><dt>{esc(l)}</dt><dd>{esc(v)}</dd></div>" for v, l in facts) + "</dl>"
    parts = c.get("parts") or {}
    if parts:
        body += "<h4 style=\"margin-top:16px\">By token type</h4>" + bars(
            [(PART_LABELS.get(k, k), v, usd(v)) for k, v in sorted(parts.items(), key=lambda kv: -kv[1]) if v > 0])
    bt = c.get("by_task_type") or {}
    if bt:
        body += "<h4 style=\"margin-top:16px\">By task type</h4>" + table(
            ["Task type", "Sessions", "Est. cost", "Per session"], [[t, d["sessions"], usd(d["usd"]), usd(d["per_session_usd"])] for t, d in bt.items()])
    top = c.get("top_sessions") or []
    if top:
        body += "<h4 style=\"margin-top:16px\">Most expensive sessions</h4>" + table(
            ["Session", "Task", "Model / effort", "Est. cost", "Of which subagents", "What drove it"],
            [[sid(t["session_id"], t.get("title")), esc(t["task_type"]), esc(f'{t["model"]} / {t.get("effort") or "-"}'), esc(usd(t["usd"])),
              esc(usd(t["subagent_usd"])), esc("; ".join(t.get("drivers") or []) or "-")] for t in top], raw_cols=range(6))
    for i, x in enumerate(sp.get("savings") or []):
        body += (f'<div class="card"><b>{esc(x.get("action"))}</b>'
                 + (f'<p>{esc(x["why"])}</p>' if x.get("why") else "")
                 + (f'<p class="muted">Evidence: {esc(x["evidence"])}</p>' if x.get("evidence") else "") + "</div>")
    return body


CONTEXT_ADVICE = {
    "high_baseline": ("Trim what loads at the start of every session: shorten CLAUDE.md (aim under 200 lines), move workflow-specific "
                      "instructions into skills, disable unused MCP servers with /mcp and plugins with /plugin. Run /context to see the biggest items.",
                      ["costs", "claude-md"]),
    "long_lived_big": ("Split long work into stages: finish a task, then /clear (or /compact with instructions at a natural break) before the next. "
                       "Let a subagent do the reading-heavy research.", ["context", "investigate"]),
    "very_large": ("A context this large is slow, costly on every request and prone to context rot. Compact or clear earlier; consider "
                   "/autocompact to compact sooner than the model limit.", ["autocompact", "context-window"]),
    "no_hygiene": ("Use /clear between unrelated tasks, /compact with a focus at a natural break, or /rewind to drop a failed path.",
                   ["context", "costs"]),
    "correction_spiral": ("After two failed corrections, /clear and restart with a better first prompt that includes what you learned.",
                          ["best-practices", "context"]),
    "cache_cold": ("Coming back after the cache lifetime means the whole context is processed again. After a long break, /clear or start a "
                   "new session rather than resuming a huge one, or /compact before you leave.", ["prompt-caching"]),
    "switch_big": ("Each model has its own cache, so switching model or effort in a big context makes the next request re-read everything "
                   "uncached. Choose model and effort at the start of the session.", ["prompt-caching"]),
    "heavy_reads": ("Delegate big reads (logs, test output, many files, docs) to a subagent so only a summary enters your context, or filter "
                    "the output with a hook.", ["investigate", "costs"]),
}


def fmt_window(n) -> str:
    return f"{n // 1_000_000}M" if n >= 1_000_000 else f"{n // 1000}K"


def context_html(S, I) -> str:
    A = S["aggregates"].get("context") or {}
    ses = [s for s in S.get("sessions", []) if s.get("context")]
    if not ses:
        return ""
    CW = I.get("context_window") or {}
    body = "<h3>Context window</h3>"
    body += ('<div class="callout"><b>How to read this.</b> Sizes are measured from each request\'s usage fields (input + cache read + cache write). '
             'The flag thresholds are this tool\'s rules of thumb, not Anthropic limits. The report assumes a Claude subscription, where the prompt '
             'cache of the main conversation lasts about 1 hour; on an API key or cloud provider it is 5 minutes by default, so idle gaps '
             'cost more there and the cache numbers below understate your case. Sessions that were resumed start with their old history, so '
             'startup size is judged by the lowest per project.' + source_links(["context-window", "prompt-caching"]) + '</div>')
    if CW.get("headline"):
        body += f'<div class="callout"><b>Summary.</b> {esc(CW["headline"])}</div>'
    peaks = sorted((s["context"]["peak_tokens"] for s in ses))
    base = sorted(s["context"]["baseline_tokens"] for s in ses)
    facts = [(f'{peaks[len(peaks) // 2] // 1000}K', "median peak context"), (f'{peaks[-1] // 1000}K', "largest peak"),
             (f'{base[0] // 1000}K', "lowest startup context"),
             (str(sum(1 for s in ses if s["context"]["requests_above_200k"])), "sessions above 200K"),
             (str(A.get("cold_restarts_total", 0)), "cache restarts after idle")]
    body += '<dl class="facts">' + "".join(f"<div><dt>{esc(l)}</dt><dd>{esc(v)}</dd></div>" for v, l in facts) + "</dl>"
    top = sorted(ses, key=lambda s: -s["context"]["peak_tokens"])[:10]
    body += "<h4 style=\"margin-top:16px\">Peak context per session</h4><p class=\"sub\">Largest request in each session, in thousands of tokens, with the share of the model window. Top 10.</p>" + bars(
        [(f'{s["id"][:8]} {s.get("project", "")}', s["context"]["peak_tokens"],
          f'{s["context"]["peak_tokens"] // 1000}K' + (f' ({s["context"]["peak_pct_of_window"]:g}% of {fmt_window(s["context"]["window_tokens"])})'
                                                    if s["context"].get("window_tokens") else "")) for s in top])
    body += "<h4 style=\"margin-top:16px\">Per session</h4>" + table(
        ["Session", "Peak", "Startup", "Requests above 200K", "Cache restarts", "/clear /compact /rewind", "Biggest tool result"],
        [[sid(s["id"], s.get("title")), f'{s["context"]["peak_tokens"] // 1000}K', f'{s["context"]["baseline_tokens"] // 1000}K',
          f'{s["context"]["requests_above_200k"]} of {s["context"]["requests"]}', s["context"]["cold_restart_count"],
          " / ".join(str(s["context"]["hygiene_commands"][k]) for k in ("clear", "compact", "rewind")),
          (f'{s["context"]["tool_result_tokens_top"][0]["tool"]} ~{s["context"]["tool_result_tokens_top"][0]["tokens"] // 1000}K'
           if s["context"]["tool_result_tokens_top"] and s["context"]["tool_result_tokens_top"][0]["tokens"] >= 1000 else "-")]
         for s in top], raw_cols=(0,))
    body += "<h4 style=\"margin-top:16px\">What to change</h4>"
    findings = CW.get("findings") or []
    for i, f in enumerate(findings):
        flag = next((x for x in A.get("flags", []) if x["key"] == f.get("flag")), None)
        body += (f'<div class="card"><b>{esc(f.get("title") or (flag or {}).get("title") or f.get("flag"))}</b>'
                 + (f' <span class="tag warn">{esc(flag["rule"])}</span>' if flag else "")
                 + (f'<p class="muted">Evidence: {esc(f["evidence"])}</p>' if f.get("evidence") else "")
                 + f'<p>{esc(f.get("advice"))}</p>' + (copybox(f"cwf{i}", f["copy"], "Paste into CLAUDE.md or your prompt") if f.get("copy") else "")
                 + source_links(CONTEXT_ADVICE.get(f.get("flag"), ("", []))[1]) + "</div>")
    covered = {f.get("flag") for f in findings}
    for x in A.get("flags", []):
        if x["key"] in covered:
            continue
        adv, srcs = CONTEXT_ADVICE.get(x["key"], ("", []))
        ev = ", ".join(f"{str(k)[:8] if re.fullmatch(r'[0-9a-f-]{36}', str(k)) else k}: {v}" for k, v in list(x["evidence"].items())[:5]) if isinstance(x["evidence"], dict) else ""
        body += (f'<div class="card"><b>{esc(x["title"])}</b> <span class="tag warn">flagged because: {esc(x["rule"])}</span>'
                 f'<p class="muted">{len(x["sessions"])} session(s). {esc(ev)}</p><p>{esc(adv)}</p>{source_links(srcs)}</div>')
    if not findings and not A.get("flags"):
        body += '<p class="na">No context-window flags in this sample.</p>'
    if CW.get("habits"):
        body += "<h4 style=\"margin-top:16px\">Habits for you</h4>" + lst(CW["habits"], "check")
    return body


def subagents_html(S) -> str:
    c = S["aggregates"].get("cost") or {}
    T = S["aggregates"]["totals"]
    bst = c.get("by_subagent_type") or {}
    if not bst:
        return ""
    body = (f'<h3>Subagents and workflow agents</h3><p class="sub">{fmt_int(T.get("subagent_runs", 0))} runs in '
            f'{T.get("sessions_with_subagents", 0)} sessions ({fmt_int(T.get("workflow_agent_runs", 0))} inside workflows), '
            "measured from their own transcripts.</p>")
    fmt = lambda d: ", ".join(f"{k} {fmt_int(v)}" for k, v in sorted(d.items(), key=lambda kv: -kv[1])) or "-"
    body += table(["Agent type", "Runs", "Sessions", "Model (messages)", "Effort (messages)", "Est. cost", "Per run", "Tool errors"],
                  [[t, fmt_int(d["runs"]), d["sessions"], fmt(d["models"]), fmt(d["effort"]), usd(d["usd"]), usd(d["per_run_usd"]),
                    d["tool_errors"]] for t, d in bst.items()])
    wfs = c.get("workflows") or []
    if wfs:
        titles = {s["id"]: s.get("title") for s in S.get("sessions", [])}
        body += "<h4 style=\"margin-top:16px\">Workflows</h4>" + table(
            ["Session", "Workflow", "Agents", "Phases (agents)", "Agent types", "Est. cost"],
            [[sid(w["session_id"], titles.get(w["session_id"])), esc(w["id"]), esc(w["runs"]), esc(fmt(w["phases"])), esc(fmt(w["types"])),
              esc(usd(w["cost_usd"]))] for w in wfs], raw_cols=range(6))
    return body


def p_settings(S, I):
    A = S["aggregates"]
    P, H = A.get("permissions") or {}, A.get("hooks_activity") or {}
    files = S.get("settings") or []
    IP = I.get("permissions") or {}
    body = ('<p class="sub">Where a rule lives decides how reliably it is followed. Move a rule down this list when it keeps '
            "being broken.</p>")
    body += table(["Where the rule lives", "Good for", "How it is followed"], [
        ["Your prompt", "one-off requests", "this session only"],
        ["CLAUDE.md, rules, memory", "conventions and context", "read every session, but advice the model can miss"],
        ["Skill", "repeatable procedures", "loaded when the task matches, or by /name"],
        ["Hook (settings.json)", "anything a command can check or do", "runs every time, cannot be skipped"],
        ["Permission rule (settings.json)", "which tool calls run without asking", "enforced by Claude Code"],
    ])
    if IP.get("findings"):
        body += "<h3>Findings</h3>" + lst(IP["findings"])

    body += "<h3>Settings files on disk</h3>"
    if files:
        rows = []
        for x in files:
            pm = x.get("permissions") or {}
            ev = {}
            for h in x.get("hooks") or []:
                ev[h["event"]] = ev.get(h["event"], 0) + 1
            rows.append([f'{esc(x["path"])}<small>{esc(x.get("scope"))}</small>',
                         esc(", ".join(f"{k} {v}" for k, v in ev.items()) or ("error: " + x["error"] if x.get("error") else "none")),
                         esc(f'{pm.get("allow", 0)} / {pm.get("ask", 0)} / {pm.get("deny", 0)}'), esc(pm.get("default_mode") or "-")])
        body += table(["File", "Hooks", "Allow / ask / deny rules", "Default mode"], rows, raw_cols=(0, 1, 2, 3))
        hooks = [(x["path"], h) for x in files for h in x.get("hooks") or []]
        if hooks:
            body += "<h4 style=\"margin-top:16px\">Hooks defined</h4>" + table(
                ["File", "Event", "Matcher", "Runs"], [[p, h["event"], h["matcher"] or "(all)", h["command"]] for p, h in hooks])
    else:
        body += na("No settings files found for these projects.")
    if H.get("stop_hook_runs"):
        defined = any(x.get("hook_count") for x in files)
        body += (f'<p>Stop hooks ran {fmt_int(H["stop_hook_runs"])} times in {H.get("sessions_with_stop_hooks", 0)} sessions '
                 f'({H.get("hook_errors", 0)} errors, {H.get("stops_blocked_by_hook", 0)} times a hook kept Claude working).'
                 + ("" if defined else " None are defined in the settings files above, so they come from plugins, which this "
                                        "report does not inventory.") + "</p>")

    body += "<h3>Permission prompts and rejected tool calls</h3>"
    appr, rej = P.get("manual_approvals") or {}, P.get("rejected") or {}
    facts = [(sum(appr.values()), "tool calls you approved by hand"), (P.get("sessions_with_manual_approval", 0), "sessions with a manual approval"),
             (sum(rej.values()), "tool calls you rejected"), (sum((P.get("blocked_by_policy") or {}).values()), "blocked by a rule or the auto-mode classifier")]
    body += '<dl class="facts">' + "".join(f"<div><dt>{esc(l)}</dt><dd>{esc(v)}</dd></div>" for v, l in facts) + "</dl>"
    if appr:
        body += "<h4 style=\"margin-top:16px\">Approved by hand, per tool</h4>" + table(["Tool", "Approvals"], list(appr.items()))
    cmds = P.get("approval_commands") or {}
    if cmds:
        body += "<h4 style=\"margin-top:16px\">Bash commands approved by hand (first two words)</h4>" + table(["Command", "Times"], list(cmds.items()))
    if rej:
        body += ("<h4 style=\"margin-top:16px\">Rejected, per tool</h4><p class=\"sub\">A rejection is a correction without words: "
                 "the agent chose an action you did not want. They count towards friction.</p>") + table(["Tool", "Rejections"], list(rej.items()))
    if P.get("modes"):
        body += "<h4 style=\"margin-top:16px\">Permission modes (sessions)</h4>" + table(["Mode", "Sessions"], list(P["modes"].items()))
    rules = IP.get("allow_rules") or []
    if rules:
        block = {"permissions": {"allow": [r.get("rule", "") for r in rules if r.get("rule")]}}
        body += ("<h4 style=\"margin-top:16px\">Allow rules to consider</h4>"
                 + lst([f'{r.get("rule")}: {r.get("why", "")}' for r in rules])
                 + copybox("allowrules", json.dumps(block, indent=2), "Merge into .claude/settings.json; keep deny rules for anything destructive"))
    if appr or rej:
        body += ('<div class="callout">Approving the same safe command again and again? Add an allow rule such as '
                 '<code>Bash(npm run *)</code>, or run <code>/fewer-permission-prompts</code> if your Claude Code has it: it scans '
                 "your transcripts and proposes an allowlist. Auto mode lets a classifier approve routine actions instead of you."
                 + source_links(["permissions", "modes", "hooks"]) + "</div>")
    return "Hooks & permissions", body


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
        tech += f'<span class="tag good">effort: {esc(t["recommended_effort"])}</span>' if t.get("recommended_effort") else ""
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
    if I.get("official_prompts"):
        reading.append("prompt-library")
    items = "".join(f"<li>{source_anchor(i)}</li>" for i in dict.fromkeys(reading) if i in SOURCES)
    body = f'<div class="cols">{cols}</div>'
    body += ('<h3>Further reading</h3><div class="card"><p class="sub">Anthropic documentation for the techniques and settings above. '
             f'These links need an internet connection.</p><ul>{items}</ul></div>')
    return "Action plan", body


def sessions_html(S) -> str:
    """Every analysed session: when it started, where it ran, what it was."""
    rows = []
    for s in sorted(S.get("sessions") or [], key=lambda x: x.get("start") or "", reverse=True):
        start = (s.get("start") or "")[:16].replace("T", " ")
        wd = s.get("cwd") or "?"
        if str(s.get("cwd_source", "")).startswith("folder"):
            wd += " (from folder name)"
        rows.append([f'<span style="white-space:nowrap">{esc(start or "?")}</span>', f'<code>{esc(wd)}</code>', esc(s.get("title") or s.get("first_prompt", "")[:60] or "-"),
                     esc(s.get("task_type") or "-"), esc(s.get("primary_model") or "-"), esc(s.get("user_turns", 0)),
                     f'<code>{esc(str(s.get("id", ""))[:8])}</code>'])
    n = len(rows)
    return (f'<h3>Sessions analysed ({n})</h3><p class="sub">Newest first. Time is when the session started, in UTC. '
            'The work directory is read from the transcript (or, when it records none, from the project folder name).</p>'
            f'<details{" open" if n <= 25 else ""}><summary>{n} session{"s" if n != 1 else ""}</summary>'
            + table(["Started (UTC)", "Work directory", "Title", "Task", "Model", "Typed prompts", "Id"], rows, raw_cols=range(7)) + "</details>")


def p_method(S, I):
    M, A, T = S["meta"], S["aggregates"], S["aggregates"]["totals"]
    auto = sum((A.get("automated_turns_excluded") or {}).values())
    nums = [["Sessions analysed", f'{M["sessions_analyzed"]} of {M["sessions_available_total"]}'],
            ["Typed prompts per session", T["avg_user_turns"]], ["Automated turns excluded", auto],
            ["Prompts of 3 words or fewer", f'{T.get("short_prompt_share_pct", 0)}%'],
            ["Sessions with a correction or interrupt", f'{T["pct_sessions_with_correction_or_interrupt"]}%'],
            ["Agent files touched", f'{A.get("agent_files_touched", 0)} ({A["agent_file_edit_count"]} edit calls)'],
            ["Model families used", len(A["by_model"])], ["Active time", f'{T["active_hours"]} h'], ["Tool errors", T["total_tool_errors"]],
            ["Rejected tool calls", T.get("total_rejected_tool_calls", 0)],
            ["Subagent runs (in workflows)", f'{T.get("subagent_runs", 0)} ({T.get("workflow_agent_runs", 0)})'],
            ["Context compactions", (A.get("context") or {}).get("compactions", 0)]]
    c = A.get("cost") or {}
    if c:
        nums.append(["Estimated cost at API list prices", usd(c.get("total_usd"))])
        if c.get("claude_code_reported_usd") is not None:
            nums.append([f'Cross-check: Claude Code\'s own running figure for the {c["sessions_with_claude_code_figure"]} sessions that record one',
                         f'{usd(c["claude_code_reported_usd"])} (this estimate for the same sessions: {usd(c.get("estimate_same_sessions_usd"))})'])
    pre = "<h3>Sample</h3>" + sample_html(S) + sessions_html(S) + "<h3>All numbers</h3>" + table(["Measure", "Value"], nums)
    body = pre + f'<div class="card" style="margin-top:20px"><p><b>Sample:</b> {M["sessions_analyzed"]} of {M["sessions_available_total"]} sessions. Generated {esc(M["generated_at"])}. Snapshot kept in {esc(M.get("history_dir") or "the history folder")}.</p>'
    body += "<p><b>Measured:</b> " + esc("; ".join(M["measured"])) + ".</p>"
    if M.get("estimated"):
        body += "<p><b>Estimated:</b> " + esc("; ".join(M["estimated"])) + "</p>"
    body += "<p><b>Heuristic (candidates, confirmed by reading context):</b> " + esc("; ".join(M["heuristic"])) + ".</p>"
    if c:
        body += ("<p><b>Cost:</b> the estimate prices each request at Claude API list rates (input, 5-minute and 1-hour cache "
                 "writes, cache reads, output, web searches, fast mode and long-prompt rates where they apply). Requests Claude Code makes "
                 "in the background and does not write to the transcript are not included, which is one reason the cross-check figure "
                 "can be higher. Neither number is what you pay.</p>" + cost_note(S, short=True))
    body += f'<p><b>Not covered:</b> {esc(M["not_covered"])}</p>'
    body += ("<p><b>Typed prompts:</b> only entries marked as human input count. Task notifications, messages from other sessions and injected "
             "reminders are excluded. Arguments of skill slash commands count as typed prompts.</p>")
    body += "<p><b>Redaction:</b> secrets, tokens, emails, IPs and long blobs are redacted in code before analysis; the report is redacted again at build time.</p></div>"
    if M["warnings"]:
        body += "<h3>Warnings</h3>" + lst(M["warnings"])
    body += "<h3>Limits noted by the analysis</h3>" + lst(I.get("limits", []))
    return "Method", body


PANELS = [("overview", p_overview), ("prompts", p_prompts), ("techniques", p_techniques), ("agentfiles", p_agent_files),
          ("settings", p_settings), ("models", p_models), ("templates", p_templates), ("plan", p_plan), ("method", p_method)]


def build(S, I) -> str:
    badges = {"prompts": len(I.get("weaknesses") or []), "techniques": len(I.get("techniques") or []),
              "agentfiles": len(flagged_files(S, I)), "templates": len(I.get("templates") or [])}
    tabs, panels = "", ""
    for n, (id_, fn) in enumerate(PANELS):
        title, body = fn(S, I)
        sel = "true" if n == 0 else "false"
        badge = f'<span class="badge">{badges[id_]}</span>' if badges.get(id_) else ""
        tabs += (f'<button role="tab" id="t-{id_}" data-tab="{id_}" aria-controls="p-{id_}" aria-selected="{sel}" '
                 f'tabindex="{0 if n == 0 else -1}">{esc(title)}{badge}</button>')
        panels += (f'<section class="panel{" active" if n == 0 else ""}" id="p-{id_}" role="tabpanel" aria-labelledby="t-{id_}">'
                   f'<h2 class="ph">{esc(title)}</h2>{body}</section>')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Claude Code prompt insights</title>'
            f'<script>{THEME_INIT}</script><style>{CSS}</style></head><body>'
            f'<header class="top"><div><h1>{LOGO_HTML}</h1>'
            '<p class="sub">Built from your local session transcripts. Quotes are redacted; review them before sharing.</p></div>'
            '<button id="theme" class="themebtn" type="button" aria-label="Switch between system, light and dark theme">Theme: system</button></header>'
            f'<nav class="tabs" role="tablist" aria-label="Report sections">{tabs}</nav><main>{panels}</main>'
            f'<script>{JS}</script></body></html>')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--insights", required=True)
    ap.add_argument("--out", help=f"report file; default {DEFAULT_DIR}/claude-prompt-insights-<UTC timestamp>.html")
    ap.add_argument("--history-dir", metavar="DIR",
                    help=f"where the snapshot for the next follow-up is kept; default: ${ENV_VAR} or "
                         "~/.claude/prompt-insights/history")
    ap.add_argument("--extra-redact", action="append", default=[])
    ap.add_argument("--no-snapshot", action="store_true",
                    help="do not save a snapshot to the history folder (the next run compares against that copy)")
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
    out = Path(a.out) if a.out else Path(DEFAULT_DIR) / f"claude-prompt-insights-{stamp_of(S['meta'].get('generated_at'))}.html"
    guard = ensure_output_dir(out.parent)
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB), offline-safe, {len(PANELS)} tabs | {guard}")
    if not a.no_snapshot:
        history_dir = resolve_history_dir(a.history_dir)
        ensure_output_dir(history_dir)
        d = snapshot(history_dir, Path(a.summary), Path(a.insights), out)
        print(f"Saved a copy (data and report) for the next run's follow-up in {d}")
    if missing:
        print("WARNING: insights.json is missing: " + ", ".join(missing))
    unknown = [r.get("id") for r in I.get("official_prompts") or [] if r.get("id") not in LIB]
    if unknown:
        print("WARNING: official_prompts ids not in the prompt library, skipped: " + ", ".join(map(str, unknown)))
    elif not I.get("official_prompts"):
        print("NOTE: insights.json has no official_prompts; the Techniques tab shows only the library catalogue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
