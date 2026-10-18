---
name: prompt-insights
description: Use when the user wants to analyze their past Claude Code sessions in ~/.claude/projects: how to write better prompts, which prompting techniques (RPI research-plan-implement, plan mode, staged delivery) would help, whether agent files (CLAUDE.md, AGENTS.md, rules, skills, commands, subagents) are stale, whether the right model and effort level is used for each task type (subagents and workflows included), what the sessions cost (estimated at API list prices), where hooks or permission rules would help, and what changed since the last report. Produces a self-contained offline HTML report with tabs, light and dark mode and a quick win at the top. Trigger on requests to review their Claude Code history, improve their prompting, give prompt engineering feedback, check for stale CLAUDE.md, rules or skills, find repeated corrections, choose between Opus, Sonnet and Haiku, see what their sessions or subagents cost, or "prompt insights", even if no HTML report is requested.
---

# Prompt insights

Turn the user's Claude Code session history into an actionable, tabbed HTML report about prompt
quality, prompting techniques that fit their habits, agent file maintenance, hooks and permission
friction, and model and effort choice per task type with an estimated cost. The first tab opens with
a **quick win** the user can apply in five minutes, and from the second run on, with what changed
since the last report.

Scripts do the mechanical work (parsing, counting, redaction, HTML). You do the judgment
(is this a real correction, is this rule stale, what would a better prompt look like, which
technique fits). Never read raw `.jsonl` files directly: they are large and may contain secrets.
Work from `summary.json` and `--show`.

## Where files go

Everything the skill writes lands in **`prompt-insights/`** inside the directory the agent runs from
(the user's project folder). The scripts create it, put a `.gitignore` inside it, and add
`prompt-insights/` to the enclosing git repository's `.gitignore`, because reports contain redacted
quotes from the user's sessions and must never be committed. Do not pass `--out` unless the user
asks for another location.

`SKILL_DIR` below is the folder holding this SKILL.md (for example `.claude/skills/prompt-insights`
or `~/.claude/skills/prompt-insights`). Run the commands from the user's project folder with the
full path to the scripts, so that `./prompt-insights/` is created in the right place.

Report snapshots (used for the follow-up between runs) are kept outside the project, in one folder
for all projects: **`~/.claude/prompt-insights/history/<timestamp>/`**. Override it with
`--history-dir DIR` on both scripts or with the `PROMPT_INSIGHTS_HISTORY` environment variable (the
option wins). Each snapshot records its `--project` filter, and a run is only compared with the
newest earlier snapshot of the same project filter. Snapshots found in an older
`./prompt-insights/history/` are copied over automatically.

## Safety rules

- Read-only on `~/.claude/projects` and on all repos. The only files you create are in
  `./prompt-insights/`, in the history folder above, and the one-line `.gitignore` entries described above.
- Redaction happens in the scripts. Still never quote secrets, tokens, internal hostnames or
  customer names. If the user names internal terms to hide, pass them with `--extra-redact REGEX`.
- Python 3.9+ standard library only; nothing to install.

## Workflow

1. **Check the format.** Session files are not a stable public contract.
   ```
   python3 SKILL_DIR/scripts/analyze_sessions.py --schema
   ```
   If it reports missing expected fields, stop and tell the user what changed instead of
   continuing with zeros. Pass the same `--project` / `--since-days` filters you will use in step 2;
   without them it inspects the newest sessions of any project.

2. **Build the summary.** Defaults to the 20 most recent sessions.
   ```
   python3 SKILL_DIR/scripts/analyze_sessions.py --limit 20
   ```
   This writes `prompt-insights/summary.json` and `prompt-insights/labels.todo.json`. It also reads
   each session's subagent and workflow-agent transcripts (`<session-id>/subagents/`), the hooks and
   permission rules in settings files (only those two keys), and, when an earlier report was saved in
   the history folder, compares this run with it (`followup`).
   Flags: `--project TEXT` (one project; also narrows the agent-file inventory to that project),
   `--since-days N` (1 to 7 only; for a longer period use `--limit`), `--limit N` (the N most recent
   sessions; `--limit 0` = all; `--limit` counts sessions kept after exclusions),
   `--exclude-session ID` (repeatable: use it for earlier look-alike analysis runs that did not
   invoke this skill and would add noise), `--prices prices.json` (overrides the built-in list prices
   for matching models), `--no-subagents` (faster, but subagent models and cost go missing),
   `--extra-redact REGEX` (repeatable), `--labels labels.json`. Print the console digest to the
   user and tell them to skim `summary.json` for leaked secrets before sharing.

   What the parser counts as a typed prompt: only human input. Task notifications, messages from
   other sessions and injected reminders are excluded (`aggregates.automated_turns_excluded`),
   sessions that ran this skill are left out (so a re-run does not analyse itself; `--include-self`
   keeps them), and the arguments of a skill slash command such as `/my-skill <text>` count, because
   that text is what the user typed. So turn counts and friction are about the user, not the machinery.

3. **Fix the task labels (do not skip).** Task types are guessed from keywords and are often wrong
   (a feature build tagged "review", a chore tagged "feature"), which poisons the model/task matrix.
   Read each session's `first_prompt` in `summary.json`, correct the values in
   `prompt-insights/labels.todo.json`, save it as `prompt-insights/labels.json`, and re-run step 2
   with `--labels prompt-insights/labels.json`. The warning about heuristic labels disappears and the
   Overview tab says "task labels reviewed".

   Label by what the user wanted, not by how it was built: a feature delivered by a multi-agent
   workflow is "feature". Label by what the session turned out to be: `first_prompt` is the
   starting hint, but if the session drifted (a README request that became feature work), use
   the later `prompts` and the label that describes most of the work. If nothing in the allowed
   list fits, use "chore" (small mechanical work) or "other".

4. **Read the summary in pieces**: `meta` and `aggregates` first (including `cost`, `by_effort`,
   `permissions`, `outcomes`), then `followup` if it is not null, then `project_roots`, `agent_files`
   and `settings`, then individual `sessions`. Use `python3 -c` or `jq` to slice it.

5. **Verify before concluding.** All flags are heuristics. For every correction, mismatch or
   stale-file claim, read the surrounding turns:
   ```
   python3 SKILL_DIR/scripts/analyze_sessions.py --show <session-id-prefix> --turns 2:6
   ```
   `--show` uses the same turn numbers as the summary and prints automated entries as
   `(automated: ...)` lines; it stops at 400 lines, so use `--turns a:b` for long sessions.
   Drop false positives. Then check the repo on disk:
   - `project_roots` says whether CLAUDE.md, AGENTS.md, rules and memory notes exist. Memory notes
     are the user's own saved preferences and often hold the standing rules that are missing from
     CLAUDE.md: read the ones named in `memory_note_names` (read-only) when judging what is missing.
   - Open each agent file you plan to criticise before calling it stale, thin or dead. Run `grep` on
     every `possibly_dead_references` entry first; they are candidates only.
   - Events in `agent_file_edit_events` with `on_disk: false` were renamed or deleted since the
     session: report them as such rather than as live files.

6. **Analyze these areas.**
   - *Prompts:* score the criteria in `references/insights-schema.md`, find the top 5 recurring
     weaknesses with before/after rewrites, 3 strengths, and a best/worst comparison.
   - *Techniques:* read `references/prompting-techniques.md`, match the user's weaknesses to
     1 to 3 techniques (RPI, plan mode, staged delivery, verify loop, ...), and give each an
     example prompt in the user's own domain. `rpi` ships with a dedicated prompt per phase
     (Research, Plan, Implement, plus iterate); give it `phases` only to tailor them, see the
     RPI section of that file.
   - *Official prompts:* read `references/prompt-library.md`. Where a weakness or technique has a
     matching prompt in the official Claude Code prompt library, add 0 to 3 `official_prompts` with
     the library `id`, the evidence, and the prompt filled in with the user's own terms.
   - *Agent files:* use `agent_files`, `project_roots`, `agent_file_edit_events`,
     `repeated_corrections`, `repeated_instructions` and `skills_never_triggered_in_sample`. A skill
     the user invokes by slash command is in `skills_invoked_by_slash`, so it is in use even if the
     Skill tool never ran. A rule that keeps being corrected but never edited is the strongest
     staleness signal; `repeated_instructions` finds rules restated across sessions even without
     correction wording. A subagent defined mid-session does not load until restart and workflows
     may call subagents by other names, so "unused" is a lead, not a verdict.
     **When any agent file looks stale, bloated, contradictory or full of dead references, or the
     user's instructions look written for an older model, tell them to run `/doctor prompt-audit`**
     (or `/doctor prompt-audit <path>` for one file or folder) in Claude Code. It audits CLAUDE.md,
     AGENTS.md, rules, skills, commands and subagents for outdated or conflicting content and
     missing references, reports proposed edits, and changes nothing until approved. It needs Claude
     Code v2.1.283 or later (check `meta.claude_code_versions`). The report shows this hint
     automatically on the Agent files tab; also put it in the `action_plan` with the file to audit.
   - *Context window:* read `references/context-window.md`, then check `aggregates.context.flags` and
     `sessions[].context` (peak, baseline, cold-cache gaps, hygiene commands). Confirm flags with `--show`,
     then fill `context_window` in insights.json.
   - *Models and effort:* read `references/model-routing.md`, then judge `by_model`, `by_effort`,
     `task_model_matrix` and `model_mismatch_candidates` (a starting list: also scan short sessions
     on the strongest tier yourself). Compare within a task type only. Subagent and workflow agents
     are measured from their own transcripts: `cost.by_subagent_type` shows model, effort, runs and
     cost per agent type, which is often the biggest routing lever. Recommend a model **and** an
     effort level per task type. If `slash_model_commands` lists a switch but `model_switches` is
     empty, the switch did not take effect on assistant messages. `model_default_saved` counts
     sessions where `/model` saved a new default for later sessions, which can change the model of
     future work silently; tell the user.
   - *Cost:* `aggregates.cost` prices measured tokens at the Claude API list prices in
     `scripts/pricing.py` (copied from https://platform.claude.com/docs/en/about-claude/pricing).
     It is an **estimate, not the user's cost**: a subscription, discounts or cloud pricing change the
     real bill. Say so every time you quote a figure ("about $X at API list prices"). Use
     `top_sessions[].drivers` and `by_subagent_type` to name what drives the estimate and write
     `spend.savings` with changes the user can make (a cheaper model or lower effort for a subagent
     type, fewer critic rounds, `/clear` before long context builds up). Never invent prices.
   - *Hooks and permissions:* `settings` lists hooks and allow/ask/deny rules on disk;
     `aggregates.permissions` counts manual approvals, rejected tool calls (each one is a correction
     without words) and blocks. A repeated correction that a command can check (format, tests,
     protected paths) belongs in a hook, not CLAUDE.md: give it `enforcement: "hook"` and a `hook`
     proposal. Commands approved by hand again and again are candidates for allow rules
     (`permissions.allow_rules`); never propose allowing destructive commands.
   - *Outcomes:* `aggregates.outcomes` shows per task type how many edit sessions ended on a passing
     check, a commit or a PR. A low verified-finish rate supports the verify-loop technique.
   - *Follow-up:* when `followup` is set, compare `metrics` before and after the previous report,
     check `advice` (did proposed lines land in the files?) and `previous_now_items`, and write a
     one-paragraph `followup_note`. Groups are small: say "early sign", not "proof".

7. **Write `prompt-insights/insights.json`** following `references/insights-schema.md`.
   `assets/example-insights.json` shows the shape; use it for structure only, never copy its text.
   Must include: a `quick_win`, 1 to 3 `techniques`, 3 to 5 `templates` (goal, context,
   constraints, approach, done_when), and a prioritized `action_plan`. Include `spend` when cost
   data exists, `permissions` when there were approvals or rejections, and `followup_note` when
   `followup` is set. Give the quick win a `metric` when one of the follow-up metrics measures it,
   so the next run can show whether it worked.

   Rules that keep the report honest:
   - `before` in each weakness is a **verbatim** excerpt copied from `--show` or
     `sessions[].prompts` (stored prompts are cut at 300 characters, so quote a short passage from
     a long brief). The report checks it against the transcript and flags what it cannot find.
     If the problem is behaviour with no prompt (a rule said in chat), use `before_kind: "behavior"`.
   - Only cite numbers that are in `summary.json`. Do not compare against "your average across all
     projects" unless the run included them.
   - Best vs worst: pick sessions of the same task type; otherwise set `comparable: false`.
   - Action plan items can name trusted sources: `{"text": "...", "sources": ["claude-md", "memory"]}`.
     The ids are in `references/insights-schema.md`; the report renders them as links to Anthropic's
     own documentation, and links items that name no source by topic. Never put free-form URLs in.

8. **Build the report.**
   ```
   python3 SKILL_DIR/scripts/build_report.py --summary prompt-insights/summary.json \
       --insights prompt-insights/insights.json
   ```
   The result, `prompt-insights/claude-prompt-insights-<UTC timestamp>.html`, is one self-contained HTML file with tabs
   and a theme button that switches between system, light and dark. The builder re-redacts, refuses to
   write a page that loads external resources (links the reader clicks are fine), and renders charts as
   inline SVG. (The warning "unrecognised entry types" lists harness bookkeeping lines that carry no
   prompt data and can be ignored.) Check its output: it prints how many quotes were verified and warns
   about missing sections. Open the file named in the builder's output (`open <file>` on macOS).
   The Overview tab states how many sessions the report covers and how to include more or fewer.
   When the user asks for "my last N sessions" use `--limit N`; for "the last N days" use
   `--since-days N` (maximum 7; offer `--limit` beyond that). Do not change those flags unasked.
   Tabs: Overview (quick win, since last report, headlines, numbers), Prompts (scores, weaknesses,
   strengths, best vs worst, how sessions ended), Techniques, Agent files, Hooks & permissions,
   Models & cost (effort, estimated cost, subagents, workflows), Templates, Action plan (with doc
   links), Method (limits, warnings, cost cross-check). The builder then copies `summary.json` and
   `insights.json` and the report to `~/.claude/prompt-insights/history/<timestamp>/` so the next run can follow up
   (`--no-snapshot` skips this).

9. **Reply in chat** with the file path and a short plain-text summary: the quick win, the
   biggest prompt weakness, the technique to try, the most important agent-file fix, the
   model-routing headline, the estimated cost at list prices (always "an estimate, not your bill"),
   what changed since the last report if there was one, and the sample size with its main limit.
   Keep it short; the report holds the detail.

## Quality bar

- Every claim cites a session id, a file path or a number from `summary.json`.
- The quick win is concrete and paste-ready, not advice. It is something the user can do today.
- Separate measured from estimated. Costs are estimates at API list prices from the pricing page,
  never the user's actual cost; say so wherever a figure appears. If token data or a model's price
  is missing (`unpriced_msgs`), say so; do not invent cost figures or model prices from memory.
- State the sample limits honestly (20 sessions is a start; say whether a larger sample is worth running).
- Prefer a few sharp, evidenced findings over a long generic list.
- Explain the "why" in rewrites so the user learns the principle, not just the fix.

## Files

- `scripts/analyze_sessions.py`: parser and aggregator (`--schema`, `--show`, default analysis).
- `scripts/build_report.py`: renders the tabbed HTML report from `summary.json` + `insights.json`.
- `scripts/outdir.py`: creates `prompt-insights/` and keeps it out of git.
- `scripts/redact.py`: shared redaction rules.
- `scripts/pricing.py`: list prices from the Claude API pricing page and the per-request cost estimate.
- `scripts/subagents.py`: reads subagent and workflow-agent transcripts.
- `scripts/settings_scan.py`: read-only inventory of hooks and permission rules.
- `scripts/history.py`: report snapshots and the follow-up comparison.
- `references/insights-schema.md`: the exact `insights.json` shape, writing rules and source ids.
- `references/prompting-techniques.md`: RPI and other techniques, and how to match them to the data.
- `references/prompt-library.md` and `assets/prompt-library.json`: official Claude Code prompts and how to match them to the data.
- `references/model-routing.md`: how to judge model fit; read before the model section.
- `references/context-window.md`: context-window knowledge base and thresholds; read before the context section.
- `scripts/context.py`: context-window measurements and flags used by the analyzer.
- `assets/example-insights.json`: structural example only.
- `assets/prompt-library.json`: the official prompt library data (copied from the docs page, with the origin of each prompt).
