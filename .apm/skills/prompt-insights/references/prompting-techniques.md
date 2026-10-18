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

Three phases, each in its own session, each ending in a file. The point is to put your judgment where
it is cheapest: a wrong research finding or a wrong plan costs a minute to fix; wrong code costs an
hour. Adapted from the goose RPI tutorial (https://goose-docs.ai/docs/tutorials/rpi/), which reports a
10-phase, 32-file removal done in about an hour (9 min research, 4 min plan, 39 min implement) that
the author estimated at several hours by hand.

Principles (from the tutorial, restated for Claude Code):
- **One goal per session.** `/clear` between phases. The file is the hand-off, not the chat.
- **Review at the two cheap gates**: after Research (is it accurate and about the right thing?) and
  after Plan (would you approve this in a code review?). Not after Implement alone.
- **Iterate, do not restart.** A plan that is slightly off is edited in place, researching only what
  the feedback needs.
- **The plan is the memory.** Checkboxes in the plan file let work resume after compaction or a new session.
- **Implementation should feel mechanical.** If it feels creative, the plan is missing something.

| Phase | Rule | Produces | You check |
|---|---|---|---|
| 1 Research | Read only. Document what exists. No opinions, no critique, no plan. Parallel subagents: locate files, analyze code, find similar patterns. Every claim as `path:line`. | `thoughts/research/<date>-<topic>.md` (summary, flow, references, patterns, tests, open questions) | Accurate? Right topic? Too broad: rerun narrower. |
| 2 Plan | No code. Ask clarifying questions, give options where several approaches fit, wait for answers. Phases in dependency order. | `thoughts/plans/<date>-<topic>.md` (scope, phases, exact files, checkboxes, automated and manual success criteria, risks) | Read it like a review. Wrong: iterate. |
| 3 Implement | Read the whole plan, phases in order, verify after each, tick checkboxes, stop and report on mismatch. | The change plus a ticked plan | Manual checks and the diff. |

Each phase has a **one-liner** (paste as is) and a **full prompt**. Suggest keeping the full prompts in
a skill (`.claude/skills/rpi-research/SKILL.md`, `rpi-plan`, `rpi-implement`, `rpi-iterate`, run as
`/rpi-research <topic>`) once the user uses RPI more than a few times, because the full text is long
and a skill gives every project the same rules. The prompts for each phase and for iterating the plan live in
`assets/technique-playbooks.json`; `build_report.py` renders them in the Techniques tab whenever
`rpi` is recommended (and in a collapsed section otherwise). So for `rpi`:
- keep `steps` to 3 to 5 lines and say why it fits (session id, number);
- do not repeat the generic prompts in `example_prompt`; it is not shown when a playbook exists;
- if the user's sessions give you real terms (paths, features, test commands), pass `phases`:
  `[{"id": "research", "short": "...", "prompt": "..."}, {"id": "plan", ...}, {"id": "implement", ...}]`
  (`short` is the one-liner, `prompt` the full text; either may be given alone).
  Keep the structure of the shipped prompt (read-only rule, output file with sections, stop
  conditions) and replace the `<placeholders>` with their real topic, files and checks.

Use it when: unfamiliar code, changes across several files (refactors, migrations, upgrades), or work
that will outlive one sitting. Skip it when: the change is one file and you can describe the diff in a
sentence.

Common mistakes: research that drifts into suggestions; a topic too broad (catch it in the first
minutes); all three phases in one session; approving a plan unread; restarting instead of iterating.

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
