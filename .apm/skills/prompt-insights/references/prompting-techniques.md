# Prompting techniques to recommend

Read this when filling `techniques` in insights.json. Recommend 1 to 3, never the whole list.
A technique earns a place only when the user's own sessions show the problem it solves, so every
recommendation needs `why_for_you` with a session id or a number. A technique the user already
uses well belongs under strengths, not here.

## Picking by signal

| What the data shows | Try first | Then |
|---|---|---|
| Big first prompt, scope cut at turn 2-3, or "rerun from ..." | `staged` | `rpi` |
| Many turns on code the agent had to learn (long exploration, wrong files touched) | `rpi` | `subagent-research` |
| Feature was right in code but wrong for the user (missing UI, unclear output) | `verify-loop` | `builder-critic` |
| Short, vague first prompt for something with many choices | `interview` | `plan-mode` |
| Same correction in 2+ sessions | `standing-rules` | `hooks` |
| A rule a command can check keeps breaking although it is in CLAUDE.md | `hooks` | - |
| Edit sessions rarely end on a passing check (`outcomes.verified_finish_pct`) | `verify-loop` | `hooks` |
| Bug fix bounced back | `repro-first` | `deep-thinking` |
| Sessions with 30+ typed prompts, agent forgets earlier decisions | `context-hygiene` | `rpi` |
| Style or structure of output keeps missing | `pattern-reference` | - |
| User already runs loops with a critic but still finds gaps | improve the critic's rubric (`builder-critic`) | `verify-loop` |

## RPI: Research, Plan, Implement

Three phases with a hand-off between each. The point is to put your judgment where it is cheapest:
a wrong research finding or a wrong plan costs a minute to fix; wrong code costs an hour.

1. **Research** (read-only). Ask for how the relevant code works today, which files matter, and
   what could break. Output goes to a file, for example `research.md`. No edits.
2. **Plan**. From `research.md`, a numbered plan: files to change, the order, how each step is
   checked. You review and edit it. Plan mode or "do not edit yet" enforces the gate.
3. **Implement**. In a fresh context (`/clear`, then point at `plan.md`), execute step by step and
   run the checks the plan names. Stop and report if reality differs from the plan.

Skeleton prompts:

```
Research: <area>. Read <paths>. Write research.md with: how it works today, files involved,
risks, open questions. Do not change any code.
```
```
Plan: using research.md, write plan.md for <change>. Numbered steps, each with the file, the
edit, and how to verify it. Stop after writing the plan so I can review.
```
```
Implement plan.md. Do steps in order, run the verification of each step, and stop at the first
failure to report what you found.
```

Use it when: unfamiliar code, changes across several files, or work that will outlive one sitting.
Skip it when: the change is one file and you can describe the diff in a sentence.

## Others (one line each, expand to fit the user)

- **plan-mode**: "Propose a plan, do not edit yet" or Shift+Tab. Good when you want to choose between approaches.
- **interview**: "Ask me questions until you can write the spec, then wait." Turns a one-liner into a spec in a few answers.
- **staged**: "Do stage 1, stop and report. I pick the next stage." Makes cutting scope cost one message.
- **verify-loop**: end with "Done when <command passes / I can see X on screen>". The agent can only check what the prompt names.
- **builder-critic**: a second agent grades the first against a written bar; add the user's recurring misses to the bar.
- **repro-first**: failing test or exact repro steps first, then fix, then show it passing.
- **subagent-research**: exploration to subagents so the main context keeps room for decisions.
- **context-hygiene**: `/clear` between unrelated tasks; write a handoff note before restarting a long session.
- **standing-rules**: say it twice, then put it in CLAUDE.md, a rule or a skill. Write it as a positive instruction.
- **pattern-reference**: "Follow the pattern in <file>" or paste one good example.
- **deep-thinking**: ask for options and trade-offs on design decisions and hard bugs; keep routine edits fast.
- **hooks**: a settings.json hook runs a command at a fixed point (PostToolUse after an edit, PreToolUse
  before a call, Stop when Claude finishes) every time. Use it for rules a command can check or do:
  format after edits, run tests before stopping, block edits to a protected path.

## Writing the recommendation

- `why_for_you`: one or two sentences, with the evidence (session id, turn, number).
- `steps`: 3 to 5 short steps the user can follow today.
- `example_prompt`: written in the user's domain and language, using their real project terms, with
  `<placeholders>` only for what you cannot know.
- Name the cost honestly (RPI adds a review step; staging adds round trips). The user decides.
