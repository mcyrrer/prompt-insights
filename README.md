# prompt-insights

A Claude Code skill that reads your own session history and tells you, in one self-contained HTML
report, **how to prompt better**, **which working technique to try next**, **whether your agent files
have gone stale**, **whether you are using the right model and effort level for each kind of task**
(subagents and workflows included), **roughly what your sessions cost at API list prices**, and, from
the second run on, **what changed since the last report**.

Everything runs locally. No network access is needed to build the report, and nothing leaves your machine.

## What you get

A single offline HTML file with tabs, a light/dark/system theme button, and a **quick win** you can
apply in five minutes at the top of the first tab.

| Tab | What is in it |
|---|---|
| **Overview** | The quick win (with a paste-ready block), what changed since your last report (4 to 6 tiles with green and red arrows for the biggest moves, full table behind a toggle), the highest-impact change, headline findings, key numbers |
| **Prompts** | Prompt-quality scores, the recurring weaknesses with before/after rewrites of your real prompts (quotes are checked against the transcript), strengths, a best-vs-worst comparison, how sessions ended (passing check, commit, PR) |
| **Techniques** | 1 to 3 techniques matched to your habits, with example prompts: RPI (research, plan, implement, with a one-liner and a full prompt for each phase plus one to iterate the plan, the full ones meant to live in a skill, adapted from the [goose RPI tutorial](https://goose-docs.ai/docs/tutorials/rpi/)), plan mode, staged delivery, verify loops, interview-first, hooks and more. Also up to 3 ready-to-send prompts from the [official Claude Code prompt library](https://code.claude.com/docs/en/prompt-library), filled in with your own project terms |
| **Agent files** | Health of CLAUDE.md, AGENTS.md, rules, skills, commands and subagents; what exists on disk; instructions you repeat across sessions; a `/doctor prompt-audit` hint when files look stale |
| **Hooks & permissions** | Hooks and allow/ask/deny rules in your settings files, tool calls you approved or rejected by hand, rules worth turning into hooks, allow rules worth adding |
| **Models & cost** | Messages and tokens per model and effort level, estimated cost by model, task type, subagent type and workflow, the most expensive sessions and why, context-window use (peak size, startup size, cache restarts after idle, missing /clear and /compact, with fixes; assumes a subscription's 1-hour cache), task-type vs model matrix, models that look too heavy or too light |
| **Templates** | Reusable prompts for your most common task types: goal, context, constraints, approach, done-when |
| **Action plan** | Do now / this month / ongoing, with links to Anthropic's own documentation |
| **Method** | What was measured vs guessed, every analysed session (start time, work directory, title, task, model), how to include more or fewer, warnings and limits |

## Requirements

- [Claude Code](https://code.claude.com/docs) with some session history in `~/.claude/projects`
  (Claude Code deletes old transcripts after a retention period; the
  [`cleanupPeriodDays`](https://code.claude.com/docs/en/settings-reference) setting controls it)
- Python 3.9 or newer (standard library only, nothing to `pip install`)

## Install

### With APM (recommended)

[APM](https://microsoft.github.io/apm/) installs agent skills from a GitHub repo into your project.

1. Install APM once:

   ```bash
   brew install apm                                  # macOS / Linux with Homebrew
   curl -sSL https://aka.ms/apm-unix | sh            # macOS / Linux
   irm https://aka.ms/apm-windows | iex              # Windows (PowerShell)
   apm --version
   ```

2. In the project you want to use it from:

   ```bash
   apm init        # only if the project has no apm.yml yet
   apm install mcyrrer/prompt-insights --target claude
   ```

   This deploys the skill to `.claude/skills/prompt-insights/` and records it in `apm.yml` and
   `apm.lock.yaml`. Commit those two files and teammates get the same skill with `apm install`.
   Pin a version with `mcyrrer/prompt-insights#<tag-or-commit>`.

### Without APM (manual)

```bash
git clone https://github.com/mcyrrer/prompt-insights.git
# for every project (user level):
mkdir -p ~/.claude/skills && cp -R prompt-insights/.apm/skills/prompt-insights ~/.claude/skills/
# or for one project only:
mkdir -p .claude/skills && cp -R prompt-insights/.apm/skills/prompt-insights .claude/skills/
```

Start a new Claude Code session so the skill is picked up.

## Use

Open Claude Code **in the project folder you want the report for** and ask in plain language:

> Run prompt insights on my last 20 sessions.
>
> Analyze my Claude Code history for this project: how can I prompt better, and are my CLAUDE.md and skills stale?
>
> Which model should I use for which kind of work, based on my sessions?

Or invoke it directly with `/prompt-insights`. Claude will build a summary, correct the task type of
each session (the keyword guess is often wrong, and the model comparison depends on it), read the
relevant turns, write its findings, and build the report.

When it finishes, open the file it names:

```bash
open prompt-insights/claude-prompt-insights-<timestamp>.html      # macOS
xdg-open prompt-insights/claude-prompt-insights-<timestamp>.html  # Linux
```

### Where the files go

Everything is written to **`./prompt-insights/`** in the directory Claude Code runs from:

```
prompt-insights/
  summary.json                     measured data (redacted)
  labels.todo.json                 task-type guesses to review
  labels.json                      your corrected task types
  insights.json                    Claude's findings
  claude-prompt-insights-<UTC timestamp>.html   the report (a new file per run)
  .gitignore                       ignores everything in this folder
```

Snapshots for the follow-up live outside the project, in one folder for all projects:

```
~/.claude/prompt-insights/history/<UTC timestamp>/
  summary.json  insights.json  claude-prompt-insights.html
```

Change the folder with `--history-dir DIR` (on both scripts) or the `PROMPT_INSIGHTS_HISTORY`
environment variable; the option wins over the variable. Snapshots from an older
`./prompt-insights/history/` are copied to the new folder on the next run.

### Cost is an estimate, not your bill

The cost figures multiply the token counts in your transcripts (main session and subagents) by the
Claude API **list prices** from the [pricing page](https://platform.claude.com/docs/en/about-claude/pricing),
copied into `scripts/pricing.py` with the date they were taken. They include cache writes (5-minute and
1-hour), cache reads, output, fast mode and long-prompt rates where they apply.

This is **not what you pay**. A Claude subscription, negotiated discounts, credits or a cloud provider's
price list all change the real bill, and requests Claude Code makes in the background without writing
them to the transcript are not counted. Use the figures to compare sessions, models and agent types
with each other. To price with your own rates, pass `--prices prices.json`.

### Follow-up between runs

Each report build saves a copy of its data and the report in `~/.claude/prompt-insights/history/<timestamp>/`.
A run is compared with the newest earlier snapshot made with the same `--project` filter (no filter
compares with no filter), so a one-project report is never measured against an all-projects one.
Because the snapshots are outside the project, they survive `git clean` and a fresh clone and can be
kept as long as you like, which lets you follow your habits over time. The next run compares the
sessions started since then with the sessions the previous report was built from (prompt habits,
corrections, sessions ending on a passing check, estimated cost per session) and checks whether the
lines it proposed for CLAUDE.md, rules and hooks are now in your files.

Reports contain redacted quotes from your sessions, so they must not be committed. The skill adds a
`/prompt-insights/` line to the enclosing git repository's `.gitignore` (and a `.gitignore` inside the
folder) automatically. The rule is anchored to the repository root, so an installed skill at
`.claude/skills/prompt-insights/` stays tracked.

### Useful options

The scripts can also be run by hand from your project folder:

```bash
python3 .claude/skills/prompt-insights/scripts/analyze_sessions.py --limit 30
python3 .claude/skills/prompt-insights/scripts/analyze_sessions.py --project my-app --limit 0
python3 .claude/skills/prompt-insights/scripts/analyze_sessions.py --since-days 7 --exclude-session 1a2b3c4d
python3 .claude/skills/prompt-insights/scripts/analyze_sessions.py --show <session-id> --turns 0:6
```

| Flag | Meaning |
|---|---|
| `--limit N` | Most recent N sessions (`0` = all; on its own it replaces the default 7-day window). The Method tab shows how many were included |
| `--project TEXT` | Only sessions whose project folder contains the text; also narrows the agent-file check to that project |
| `--since-days N` | Only sessions from the last N days (any N). Default: 7 days when neither this nor `--limit` is given. Combine with `--limit` to cap the count |
| `--history-dir DIR` | Where snapshots are kept (default `$PROMPT_INSIGHTS_HISTORY`, else `~/.claude/prompt-insights/history`) |
| `--exclude-session ID` | Skip a session (repeatable) |
| `--prices prices.json` | Your own prices (USD per 1M tokens, keyed by a model-name substring: `input`, `output`, `cache_read`, `cache_write`, `cache_write_1h`); overrides the built-in list prices for matching models |
| `--no-subagents` | Skip subagent and workflow transcripts (faster; their models, tokens and cost are then missing) |
| `--extra-redact REGEX` | Redact more terms, such as customer or host names (repeatable) |
| `--labels labels.json` | Your corrected task types |

## Privacy and safety

- **Read-only** on `~/.claude` and on your repositories. The only things it writes are the files in `./prompt-insights/`, the snapshots in `~/.claude/prompt-insights/history/` (or your chosen history folder) and one line in `.gitignore`.
- **Settings files:** only the `hooks` and `permissions` keys are read; environment variables and other settings never enter the summary.
- **Redaction in code** removes API keys, tokens, passwords, emails, IP addresses and long blobs before Claude sees any text, and again when the report is built. Skim `summary.json` before sharing anything.
- **Only your own typed prompts count.** Task notifications, messages from other sessions and injected reminders are excluded. Arguments of skill slash commands count, because you typed them.
- **The report loads nothing from the internet.** Only the documentation links in the Action plan are links you click.

## Tip: keep agent files healthy

When the report finds stale, bloated or conflicting instruction files, run Claude Code's built-in
audit. It checks CLAUDE.md, AGENTS.md, rules, skills, commands and subagents for instructions written
for older models, references to files that no longer exist, and files that contradict each other. It
shows proposed edits and changes nothing until you approve (needs Claude Code v2.1.283 or later):

```
/doctor prompt-audit
/doctor prompt-audit .claude/skills/my-skill
```

[Documentation](https://code.claude.com/docs/en/memory#audit-your-instruction-files)

## Repository layout

This repository is an [APM](https://microsoft.github.io/apm/) package.

```
apm.yml                               package manifest
.apm/skills/prompt-insights/
  SKILL.md                            the skill instructions
  scripts/                            analyze_sessions.py, build_report.py, pricing.py, subagents.py,
                                      settings_scan.py, history.py, outdir.py, redact.py
  references/                         report schema, prompting techniques, prompt library, model routing
  assets/                             example-insights.json (structure only), prompt-library.json (official prompts), technique-playbooks.json (RPI prompts), logo.png (report header)
```

Validate a change before sending it:

```bash
apm audit --file .apm/skills/prompt-insights/SKILL.md
apm install --dry-run --target claude
```

## License

MIT, see [LICENSE](LICENSE).
