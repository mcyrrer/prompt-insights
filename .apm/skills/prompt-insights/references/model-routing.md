# Model routing: how to judge fit from the session data

Read this when filling `model_routing` in insights.json.

Available models and prices change often. Reason in **tiers**, use the model names the user's
sessions actually contain, and tell the user to re-check the current list with `/model`.

| Tier | Typical use | Signs it was the wrong tier in the data |
|------|-------------|------------------------------------------|
| Most capable (Opus-class and above) | Architecture and design, planning non-trivial changes, tricky multi-file debugging, security-sensitive work, ambiguous tasks | Used on 1-3 turn sessions with no corrections and 0-1 files edited |
| Balanced (Sonnet-class) | Everyday implementation with a clear spec, refactors with tests, CI/YAML fixes, most reviews | High friction per turn on hard tasks (many strong corrections, restarts) |
| Fast (Haiku-class) | Renames, boilerplate, log and file lookups, commit messages, simple Q&A, exploration subagents | Many turns, repeated corrections or interruptions on multi-file work |

## What the data can and cannot tell you

- **Measured:** model per assistant message, switches, `/model` commands, tokens per model,
  subagent models, turns, tool errors, interruptions.
- **Heuristic:** task type, corrections, friction score, mismatch candidates.
- **Not measured:** models used by subagents (their transcripts are separate files), so
  `subagent_model_msgs` is empty; say so rather than inferring worker models.
- **Not measurable from transcripts:** true quality, wall-clock latency, billed cost. Cost is only
  estimated if the user supplied `--prices`; say "n/a" otherwise.

## Procedure

1. Start from `aggregates.by_model`, `by_task_type` and `task_model_matrix`.
2. Treat any matrix cell with fewer than 3 sessions as an anecdote. Say so in `evidence`.
3. Confirm each entry in `model_mismatch_candidates` by reading the session with
   `analyze_sessions.py --show <id>`. Drop candidates that were fine (for example a short session
   that was legitimately deep thinking, such as a one-question architecture review).
4. Look for these patterns:
   - **Heavy model on trivial work:** short sessions, few tool calls, no corrections.
   - **Light model on hard work:** many turns, strong corrections, interruptions, restarts.
   - **Switches mid-session** (`model_switches`, `slash_model_commands`): did friction drop after?
   - **Planning vs execution:** was a stronger model used for planning and a faster one for
     implementation? If the user's Claude Code version offers a plan-mode hybrid alias (check
     `/model`), mention it as an option rather than assuming it exists.
   - **Subagents** (`subagent_model_msgs`, `subagents_used`): exploration and search subagents are
     good candidates for a faster tier.
5. Write one `guide` row per task type that appears in the sample. If a task type has no usable
   data, still recommend a tier from the table above and write `evidence: "no data in sample"`.
6. Add 3 to 6 `rules_of_thumb`, concrete and tied to the user's habits (for example "start infra
   debugging sessions with /model set to X because 4 of 5 sessions on the lighter tier needed
   restarts").

## Caveats to state in the report

- Friction depends on the prompt as much as on the model. If the same task type shows high
  friction on every model, the prompt is the more likely cause. Say that instead of blaming a tier.
- Sessions are not randomized: people tend to use stronger models on harder tasks, so raw friction
  comparisons can point the wrong way. Compare within a task type only.
