# prompt-insights

## Short description

Claude Code skill that analyzes your session history and builds an offline HTML report: better prompts, matching techniques, stale agent-file checks and model-routing advice.

## Purpose

prompt-insights is a Claude Code skill that reads your own session history and turns it into one offline HTML report on how to work better with Claude Code.

You can't see most of what makes Claude Code work well for you from inside a single session. You type the same corrections every week, vague first prompts cost rounds of follow-ups, CLAUDE.md and other agent files drift out of date, and you pick a model out of habit, not because it fits the task. Your session history already holds the evidence, and this skill turns it into feedback you can act on:

- Better prompts: it finds the gaps that keep causing follow-ups and rewrites your own prompts to show the fix.
- Better techniques: it matches ways of working, such as research-plan-implement and plan mode, to your habits.
- Healthier agent files: it flags stale or conflicting instructions in CLAUDE.md, AGENTS.md, rules, skills and subagents, and instructions you keep repeating that belong there.
- The right model for the job: it compares the model you used with the kind of task, so a heavy model isn't spent on renames and a fast one isn't stuck on hard debugging.

Everything runs locally. Secrets are redacted before analysis, and nothing leaves your machine.

## The output

### What gets produced

One run writes a small set of files to `./prompt-insights/` in the folder Claude Code runs from. The
main result is **`claude-prompt-insights.html`**, a single self-contained report. The other files are
the steps that lead to it, and you can inspect them:

| File | What it holds |
|---|---|
| `summary.json` | Everything measured from your sessions, already redacted: prompts, turns, corrections, interruptions, tool errors, tokens per model, agent files on disk and when they were edited |
| `labels.todo.json` | A keyword guess of each session's task type (feature, bug fix, review, chore and so on) |
| `labels.json` | The same labels after Claude has corrected them by reading what each session was really about |
| `insights.json` | Claude's findings: scores, weaknesses with rewrites, techniques, agent-file verdicts, model advice, templates and the action plan |
| `claude-prompt-insights.html` | The report you open in a browser |
| `.gitignore` | Keeps the whole folder out of git, because the report quotes your own sessions |

### How the report is made

The work is split in two. **Scripts do the measuring**: they parse the session transcripts, count
turns, corrections, interruptions, tool errors and tokens, inventory your agent files, and redact
secrets. **Claude does the judging**: it reads the flagged turns in context, drops false positives,
scores your prompts, decides which agent files are really stale, and writes the advice. The report
puts both side by side and labels which is which.

Only what you typed counts as a prompt. Task notifications, messages from other sessions and injected
reminders are left out, so the numbers describe you, not the tooling. Earlier runs of this skill are
also excluded, so the report never analyses itself.

### The report, tab by tab

The report opens on the Overview tab. Tabs carry a small count badge (number of weaknesses,
techniques, flagged agent files and templates) so you can see where the findings are before you click.

#### 1. Overview: the five-minute version

- **The sample**: how many sessions were analysed out of how many exist, the date range, the project
  filter if one was used, and whether the task labels were reviewed or are still guesses. A warning
  appears when the sample is under 10 sessions.
- **Quick win**: the hero of the page. One concrete action that takes about five minutes and pays off
  in your very next session, such as a line to paste into CLAUDE.md or a sentence to add to your
  prompts. It comes with why it matters, the evidence behind it, and a copy button.
- **Highest-impact change**: the single bigger change that would help most, beyond the quick win.
- **What the sessions show**: around five headline findings, each tied to a number or a session.
- **Numbers that matter**: typed prompts per session, share of sessions with a correction or
  interrupt, number of agent files flagged, and number of instructions you repeat across sessions.
- **Technique to try**: the top recommended technique, with a link to the Techniques tab.

#### 2. Prompts: how well you brief the agent

- **Score bars** for six criteria, each scored 0 to 5 with a one-line reason, sorted weakest first so
  the top row is the one to work on:
  goal and why, scope and constraints, context pointers, done criteria, plan first, and task size.
- **Top recurring weaknesses** (up to five). Each shows one of your real prompts next to a rewritten
  version, marked up in red and green so you see exactly what was added or removed, plus why the
  rewrite works and which sessions show the pattern. Every quote is checked against the transcript
  and tagged "verbatim quote checked", "partly found" or "not found: may be reconstructed", so you
  know the before-text is really yours. Habits with no prompt to quote are tagged as behaviour.
- **Top strengths**: what you already do well, with examples, so you keep doing it.
- **Best vs worst session**: two sessions of the same task type side by side, with the first prompt,
  what happened, the traits of each prompt, and the key difference. If no fair pair exists, the
  report says so and calls them "smoother" and "rougher" instead.

#### 3. Techniques: ways of working that fit your habits

One to three techniques, picked only when your own sessions show the problem they solve. Each has:
when to use it, why it fits you (with evidence), three to five steps you can follow today, and an
example prompt written in your project's terms with a copy button. A collapsible catalogue lists
every technique the skill knows:

- **RPI (research, plan, implement)**: research to a file without editing, plan from the research,
  then implement in a fresh context
- **Plan mode**: get a plan and approve it before any edit
- **Interview first**: let Claude ask questions until it can write the spec
- **Staged delivery**: do one stage, stop and report, then choose the next
- **Verify loop**: end every prompt with "done when" and a command or visible result
- **Builder plus critic**: a second agent grades the work against a written bar
- **Repro first**: a failing test or exact repro steps before the fix
- **Subagent research**: hand exploration to subagents to keep the main context free
- **Context hygiene**: `/clear` between unrelated tasks, handoff notes for long work
- **Standing rules**: once you say something twice, put it in CLAUDE.md, a rule or a skill
- **Pattern reference**: point at an existing file to copy the style from
- **Deep thinking**: ask for options and trade-offs on hard design decisions and bugs

#### 4. Agent files: are your instructions still pulling their weight?

- **`/doctor prompt-audit` hint**: when anything looks stale, bloated or contradictory, the tab tells
  you to run Claude Code's built-in audit, including the exact command for the first flagged file. It
  also warns when your sessions ran a Claude Code version too old to have it.
- **Checked on disk**: per project, whether CLAUDE.md and AGENTS.md exist, and how many rules,
  subagents, skills and memory notes there are.
- **File health**: a table with one row per working folder (`~/.claude/` counts as one folder) and
  the number of files in each status (healthy, stale, bloated, thin, at-risk), plus the healthy
  total. Below it, the files that need attention with kind, last edit date, length, sessions since
  the last change, the evidence and the next step. References to files that no longer exist are
  listed as leads.
- **Update timeline**: when each agent file was edited, from which project and with which tool,
  including files that have since been renamed or deleted.
- **Repeated corrections to capture**: corrections you made in more than one session, how often, which
  file they belong in, and the exact line to paste, with a copy button.
- **Instructions you repeat across sessions**: sentences you typed in two or more sessions, and
  whether any agent file already covers them.
- **Rules and skills to rewrite, merge or remove**, with proposed text.
- **Skills you invoked by slash command** and **skills never triggered in this sample**, so you can see
  which skills earn their place.
- **Maintenance routine**: a short checklist for keeping agent files fresh.

#### 5. Models: the right model for each kind of task

- **Assistant messages by model** and **sessions by task type**, as bar charts.
- **Tokens per model**: input, output, cache read and cache write, all measured. Cost is only
  estimated if you supply a price file; otherwise it says "n/a" rather than guessing.
- **Task type x model friction matrix**: a heat map of how much friction each model met on each kind of
  task (average turns and friction per typed prompt), with a note that cells under three sessions are
  anecdotes.
- **Mismatches**: sessions where the model looks too heavy for a trivial job or too light for a hard
  one, with what to use instead.
- **Model routing guide**: a recommended model tier per task type, with the reason and the evidence.
- **Rules of thumb**, such as when to switch with `/model` or use plan mode, plus a reminder to
  re-check against the current model list because models change.

#### 6. Templates: reusable prompts for your common work

Three to five templates, one for each of your most common task types. Each names the recommended model
and technique and is built from five parts: **goal** (what and why), **context** (files and docs to
read first), **constraints** (what must not change), **approach** (how to work) and **done when**
(the check that proves it). Replace the `<placeholders>` and send it; each has a copy button.

#### 7. Action plan: what to do and when

Three columns: **Do now**, **This month** and **Ongoing**. Every item links to the matching page in
Anthropic's own Claude Code documentation, and a **Further reading** list collects the guides behind
the techniques and settings recommended above. Only links from a fixed, trusted list are used.

#### 8. Method: how much to trust it

- **All numbers**: sessions analysed, typed prompts per session, automated turns excluded, share of
  very short prompts, share of sessions with a correction or interrupt, agent files touched and edit
  calls, model families used, active hours and tool errors.
- **Measured vs heuristic vs not covered**: what was counted exactly, what is a pattern match that
  Claude confirmed by reading context, and what the data cannot show (true quality, latency, billed
  cost, the models used inside subagents).
- How typed prompts are counted, how redaction works, any warnings from the run, and the limits the
  analysis itself noted, including whether a bigger sample would be worth running.

### How the report keeps itself honest

- Every finding points to a session id, a file path or a number from the measured data.
- Quoted prompts are checked against the transcript, and the check result is shown.
- Measured numbers and judgements are kept apart and labelled.
- No invented costs or model prices; cost appears only when you provide prices.
- Small samples and unreviewed task labels trigger visible warnings.
- Best-vs-worst comparisons are only called that when the two sessions are the same kind of work.

### The page itself

- One HTML file with everything inside it. It loads nothing from the internet; the build refuses to
  write a page that would. Only the documentation links you click go online.
- Theme button that switches between system, light and dark.
- Copy buttons on every paste-ready block: quick win, rewrites, example prompts, CLAUDE.md lines and
  templates.
- Keyboard navigation between tabs, and links to a tab by `#name` in the address.
- Works without JavaScript (all tabs shown in one page) and prints with every tab expanded.
- Usable on a phone: the tab bar scrolls sideways.
- Redacted twice: once when the summary is built and again when the page is built. Skim
  `summary.json` before sharing anything anyway.
