# insights.json schema

The model writes this file after reading `summary.json`. `build_report.py` renders it next to the
measured data in a tabbed page. Every key is optional: a missing section is shown as "Not provided",
and the builder warns when `quick_win`, `techniques`, `templates` or `action_plan` are missing.

All strings are redacted again at build time, but still never paste secrets, tokens, hostnames or
customer names. Keep quotes short.

```json
{
  "quick_win": {
    "title": "One action, doable in minutes",
    "why": "One or two sentences, tied to a number or session from the data",
    "do_this": "The exact text to paste: a prompt, a CLAUDE.md line, or a command",
    "minutes": 5,
    "evidence": "session ids / numbers",
    "metric": "optional: the follow-up metric that measures it (see below), e.g. has_done_criteria"
  },
  "followup_note": "only when summary.followup is set: what changed since the last report, in a few sentences",
  "headline_insights": ["5 short, concrete findings, each with a number or example"],
  "top_change": "The single highest-impact change, one or two sentences (bigger than the quick win)",

  "prompt_quality": {
    "scores": [
      {"criterion": "Goal and why", "score": 3.0, "note": "evidence in one line"},
      {"criterion": "Scope and constraints", "score": 2.0, "note": ""},
      {"criterion": "Context pointers", "score": 4.0, "note": ""},
      {"criterion": "Done criteria", "score": 1.5, "note": ""},
      {"criterion": "Plan first", "score": 2.0, "note": ""},
      {"criterion": "Task size", "score": 3.5, "note": ""}
    ]
  },

  "weaknesses": [
    {
      "title": "Short name of the pattern",
      "before": "VERBATIM excerpt of a real prompt, copied from --show output",
      "before_kind": "quote",
      "after": "rewritten better prompt",
      "why": "why the rewrite works, in one or two sentences",
      "evidence_sessions": ["session-id-prefix"]
    }
  ],
  "strengths": [{"title": "", "evidence": "concrete example"}],

  "best_vs_worst": {
    "comparable": true,
    "comparability_note": "required when comparable is false: why the two sessions are not like for like",
    "best":  {"session_id": "", "first_prompt": "", "what_happened": "", "prompt_traits": ["..."]},
    "worst": {"session_id": "", "first_prompt": "", "what_happened": "", "prompt_traits": ["..."]},
    "key_difference": "what the prompts did differently"
  },

  "techniques": [
    {
      "id": "rpi",
      "name": "RPI: Research, Plan, Implement",
      "when": "one line: the situation it fits",
      "why_for_you": "evidence from the user's sessions",
      "steps": ["3 to 5 short steps"],
      "example_prompt": "written in the user's domain",
      "phases": [{"id": "research|plan|implement", "short": "optional, RPI only: the one-liner in the user's domain", "prompt": "optional, RPI only: the full prompt in the user's domain"}],
      "evidence_sessions": ["..."]
    }
  ],

  "official_prompts": [
    {
      "id": "id from assets/prompt-library.json, for example plan-a-multi-file",
      "why_for_you": "evidence from the user's sessions (session id or number)",
      "prompt": "the library prompt with its {slots} filled in with the user's own terms",
      "evidence_sessions": ["..."]
    }
  ],

  "agent_files": {
    "update_pattern": "how often, when and why agent files get updated, with counts",
    "findings": [
      {"path": "exact path from summary.agent_files", "status": "healthy|stale|bloated|thin|at-risk",
       "evidence": "what shows it", "action": "what to do"}
    ],
    "repeated_corrections": [
      {"theme": "", "occurrences": 3, "target_file": "CLAUDE.md", "proposed_line": "exact line to add",
       "enforcement": "claude-md|rule|skill|hook",
       "hook": {"event": "PostToolUse", "matcher": "Edit|Write", "command": "the command to run", "why": "one line"}}
    ],
    "rewrites": [
      {"path": "", "action": "rewrite|merge|remove", "issue": "", "proposed_text": ""}
    ],
    "routine": ["checklist items for keeping agent files fresh"]
  },

  "model_routing": {
    "mismatches": [
      {"session_id": "", "task_type": "", "model": "", "issue": "heavy for trivial | light for hard | ...",
       "suggestion": "what to use instead and why"}
    ],
    "guide": [
      {"task_type": "", "recommended": "model tier or alias", "effort": "low|medium|high|xhigh|max",
       "why": "", "evidence": "sessions / numbers, or 'no data'"}
    ],
    "rules_of_thumb": ["practical rules, e.g. when to use /model, /effort or plan mode"]
  },

  "spend": {
    "headline": "one or two sentences on what drives the estimated cost, with numbers from aggregates.cost",
    "savings": [{"action": "a change the user can make", "why": "the driver it reduces", "evidence": "session ids / numbers"}]
  },

  "context_window": {
    "headline": "one or two sentences: how the user uses the context window, with numbers from aggregates.context",
    "findings": [
      {"flag": "key from aggregates.context.flags, or 'kitchen_sink' for your own judgment",
       "title": "", "evidence": "session ids and numbers from sessions[].context",
       "advice": "what to do differently, in the user's terms",
       "copy": "optional text to paste, e.g. a '# Compact instructions' block for CLAUDE.md or a prompt"}
    ],
    "habits": ["short, specific habits that fit this user's data; each from references/context-window.md"]
  },

  "permissions": {
    "findings": ["short findings about approvals, rejections, hooks and rules, with numbers"],
    "allow_rules": [{"rule": "Bash(npm run test *)", "why": "approved by hand N times", "target": ".claude/settings.json"}]
  },

  "templates": [
    {
      "task_type": "", "title": "", "recommended_model": "", "recommended_effort": "optional",
      "technique": "optional technique id",
      "goal": "what and why, with <placeholders>",
      "context": "files, docs, examples to read first",
      "constraints": "what must not change, limits",
      "approach": "how to work: plan first, stages, which agents",
      "done_when": "the check that proves it: command, visible result"
    }
  ],

  "action_plan": {
    "now": ["plain string, or {\"text\": \"...\", \"sources\": [\"claude-md\", \"memory\"]}"],
    "this_month": [""],
    "ongoing": [""]
  },

  "stats": {"repeated_corrections_not_captured": 0},
  "limits": ["sample size, estimated vs measured, what a bigger sample might change"]
}
```

## Writing rules

- **Evidence first.** Each weakness, mismatch and stale-file claim must point to a session id, a
  file path or a number in `summary.json`. If the evidence is thin, say so in the text instead of
  dropping the claim silently. Do not compare against numbers that are not in `summary.json`
  (for example "versus your average across all projects" when only one project was analysed).
- **Quick win.** One action that takes about five minutes and pays off in the next session:
  a line to paste into CLAUDE.md or a skill, or a sentence to add to the next prompt. It must be
  concrete (`do_this` is paste-ready) and smaller than `top_change`. Do not make it generic advice.
- **`before_kind`** is `"quote"` (the default) when `before` is copied from a prompt, and
  `"behavior"` when there is no prompt to quote (a rule the user keeps stating in chat, a habit).
- **Real quotes only.** `before` is copied from `analyze_sessions.py --show` output (or
  `sessions[].prompts` in summary.json), shortened with `...` where needed. The report checks it
  against the transcript and flags a quote it cannot find. When the problem is behaviour with no
  prompt to quote (a rule the user keeps saying in chat), set `before_kind: "behavior"` and describe
  it in `before`; do not invent a prompt.
- **Scores** are 0 to 5 and your judgment after reading the flagged turns. The regex flags in
  `aggregates.prompt_quality_heuristic` are a starting point only. The first prompt can be a pasted
  brief (`first_prompt_pasted`): judge it as a spec, not as typing.
- **Best vs worst.** Pick two sessions of the same task type when you can. If the only candidates
  differ in kind (a 1-turn chore against a long build), set `comparable: false` and explain; the
  report then labels them "smoother" and "rougher" instead.
- **Tiny samples** (fewer than 5 sessions): still score, but say "low confidence" in each note, and
  prefer concrete findings (a file missing, a session that took 4 turns to name its subject) over
  statistics. A standing rule stated in one session may be listed in `repeated_corrections` with
  `occurrences: 1`, labelled "stated once" in `theme`; never inflate the count.
- **Techniques**: 1 to 3, chosen with `references/prompting-techniques.md`; at least one when any
  weakness is about scope, task size, missing checks or unfamiliar code.
- **Official prompts**: 0 to 3, chosen with `references/prompt-library.md`. The `id` must exist in
  `assets/prompt-library.json`; the builder skips unknown ids with a warning. Each needs `why_for_you`
  with evidence. Optional: leave the list out when nothing in the sessions fits.
- **Templates**: 3 to 5, one per most common task type in `aggregates.by_task_type` (use the
  corrected labels). Fill all five fields; `<placeholders>` only for what you cannot know.
- **Repeated corrections**: an occurrence is a separate session where the user states the same
  rule, whether or not a correction phrase was detected (`repeated_instructions` lists candidates).
   write the exact line the user can paste into the agent file. Prefer a
  positive instruction ("Use the existing Logger") over a prohibition. If the user states a
  standing rule in chat (for example "commit and push after the gauntlet"), list it here with the
  file it belongs in, even when it appears in only one session.
- **Model names**: refer to tiers or the aliases the user actually used. Do not hard-code model
  versions or prices from memory.
- **Cost** is an estimate: measured tokens priced at the Claude API list prices in
  `scripts/pricing.py` (from https://platform.claude.com/docs/en/about-claude/pricing). Every cost
  you write says so ("about $12 at API list prices"); never call it the user's spend or bill. Only
  quote figures from `aggregates.cost` or `sessions[].cost`. `claude_code_reported_usd` is a
  cross-check, not a second answer.
- **Context window**: read `references/context-window.md` first. Confirm each automatic flag against the
  session (`--show`) before keeping it, drop false ones, and add `kitchen_sink` yourself when one session
  mixes unrelated goals. Sizes are measured; thresholds are rules of thumb, so say "flagged because ...".
  Never claim a quality loss: say the context was large, not that answers got worse.
- **Hooks**: use `enforcement: "hook"` only for rules a command can check or carry out (formatting,
  tests, blocking edits to a path). Write `hook.command` so it works as a `"type": "command"` hook;
  the report renders the settings.json block. Judgment calls stay in CLAUDE.md or a skill.
- **Allow rules**: propose them only for commands the data shows were approved by hand, and never
  for destructive commands (rm, git push --force, deploys).
- **`quick_win.metric`** is one of: `typed_prompts`, `corrections_pct`, `friction_per_turn`,
  `has_done_criteria`, `has_goal_why`, `has_scope`, `has_context_pointer`, `asks_plan_first`,
  `plan_mode`, `verified_finish`, `rejected_tool_calls`, `compactions`, `cost_per_session`. The next
  run highlights it in the follow-up table.

## Action plan sources and `/doctor prompt-audit`

Action items link to Anthropic's own documentation. Name sources by id; the report turns them into
links and adds a "Further reading" list. An item that names none is linked by topic automatically.
Free-form URLs are never rendered.

| id | Points to |
|---|---|
| `best-practices` | Best practices for Claude Code |
| `verify` | Give Claude a way to verify its work |
| `plan` | Explore first, then plan, then code |
| `interview` | Let Claude interview you |
| `context` | Manage context aggressively |
| `investigate` | Use subagents for investigation |
| `claude-md` | Write an effective CLAUDE.md |
| `memory` | How Claude remembers your project |
| `prompt-audit` | Audit your instruction files (`/doctor prompt-audit`) |
| `skills`, `sub-agents`, `hooks` | Skills, subagents, hooks guide |
| `permissions`, `settings` | Permission rules (allow, ask, deny); settings files |
| `pricing` | Claude API pricing page (the list prices behind the cost estimate) |
| `model-config` | Model configuration (`/model`, `opusplan`) |
| `modes`, `workflows`, `how-it-works`, `features` | Permission modes, common workflows, how Claude Code works, extension overview |
| `prompting`, `context-eng` | Claude prompting best practices; Anthropic's context-engineering article |

When agent files look stale, bloated, contradictory or written for older models, add an action item
such as `{"text": "Run /doctor prompt-audit on <path> and apply the edits you agree with", "sources": ["prompt-audit"]}`.
It needs Claude Code v2.1.283 or later and changes nothing until the user approves.
