# prompt-insights

A Claude Code skill that reads your own session history and tells you, in one self-contained HTML
report, **how to prompt better**, **which working technique to try next**, **whether your agent files
have gone stale**, and **whether you are using the right model for each kind of task**.

Everything runs locally. No network access is needed to build the report, and nothing leaves your machine.

## What you get

A single offline HTML file with tabs, a light/dark/system theme button, and a **quick win** you can
apply in five minutes at the top of the first tab.

| Tab | What is in it |
|---|---|
| **Overview** | The quick win (with a paste-ready block), the highest-impact change, headline findings, key numbers |
| **Prompts** | Prompt-quality radar, the recurring weaknesses with before/after rewrites of your real prompts (quotes are checked against the transcript), strengths, a best-vs-worst comparison |
| **Techniques** | 1 to 3 techniques matched to your habits, with example prompts: RPI (research, plan, implement), plan mode, staged delivery, verify loops, interview-first and more |
| **Agent files** | Health of CLAUDE.md, AGENTS.md, rules, skills, commands and subagents; what exists on disk; instructions you repeat across sessions; a `/doctor prompt-audit` hint when files look stale |
| **Models** | Usage and tokens per model, task-type vs model matrix, models that look too heavy or too light for the job |
| **Templates** | Reusable prompts for your most common task types: goal, context, constraints, approach, done-when |
| **Action plan** | Do now / this month / ongoing, with links to Anthropic's own documentation |
| **Method** | What was measured vs guessed, sample size, warnings and limits |

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
open prompt-insights/claude-prompt-insights.html      # macOS
xdg-open prompt-insights/claude-prompt-insights.html  # Linux
```

### Where the files go

Everything is written to **`./prompt-insights/`** in the directory Claude Code runs from:

```
prompt-insights/
  summary.json                     measured data (redacted)
  labels.todo.json                 task-type guesses to review
  labels.json                      your corrected task types
  insights.json                    Claude's findings
  claude-prompt-insights.html      the report
  .gitignore                       ignores everything in this folder
```

Reports contain redacted quotes from your sessions, so they must not be committed. The skill adds a
`/prompt-insights/` line to the enclosing git repository's `.gitignore` (and a `.gitignore` inside the
folder) automatically. The rule is anchored to the repository root, so an installed skill at
`.claude/skills/prompt-insights/` stays tracked.

### Useful options

The scripts can also be run by hand from your project folder:

```bash
python3 .claude/skills/prompt-insights/scripts/analyze_sessions.py --limit 30
python3 .claude/skills/prompt-insights/scripts/analyze_sessions.py --project my-app --limit 0
python3 .claude/skills/prompt-insights/scripts/analyze_sessions.py --since-days 14 --exclude-session 1a2b3c4d
python3 .claude/skills/prompt-insights/scripts/analyze_sessions.py --show <session-id> --turns 0:6
```

| Flag | Meaning |
|---|---|
| `--limit N` | Most recent N sessions (default 20, `0` = all) |
| `--project TEXT` | Only sessions whose project folder contains the text; also narrows the agent-file check to that project |
| `--since-days N` | Only sessions from the last N days |
| `--exclude-session ID` | Skip a session (repeatable) |
| `--prices prices.json` | Optional cost estimate (USD per 1M tokens, keyed by model name); without it no cost is shown |
| `--extra-redact REGEX` | Redact more terms, such as customer or host names (repeatable) |
| `--labels labels.json` | Your corrected task types |

## Privacy and safety

- **Read-only** on `~/.claude` and on your repositories. The only things it writes are the files in `./prompt-insights/` and one line in `.gitignore`.
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
  scripts/                            analyze_sessions.py, build_report.py, outdir.py, redact.py
  references/                         report schema, prompting techniques, model routing
  assets/                             structural example of insights.json
```

Validate a change before sending it:

```bash
apm audit --file .apm/skills/prompt-insights/SKILL.md
apm install --dry-run --target claude
```

## License

MIT, see [LICENSE](LICENSE).
