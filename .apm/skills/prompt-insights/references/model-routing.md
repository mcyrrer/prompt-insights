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

- **Measured:** model and effort level per assistant message, switches, `/model` and `/effort`
  commands, tokens per model, turns, tool errors, interruptions, rejected tool calls. Subagents
  and workflow agents are read from their own transcripts (`<session-id>/subagents/`), so
  `subagent_model_msgs` and `cost.by_subagent_type` show which model and effort each agent type
  ran on, how often, and roughly what it cost.
- **Estimated:** cost. Measured tokens are priced at Claude API list prices from
  https://platform.claude.com/docs/en/about-claude/pricing (`scripts/pricing.py`). It is not the
  user's bill; a subscription or discounts change what they pay. Always call it an estimate.
- **Heuristic:** task type, corrections, friction score, mismatch candidates, cost drivers.
- **Not measurable from transcripts:** true quality, billed cost, background requests Claude Code
  does not write to the transcript.

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
   - **Subagents** (`cost.by_subagent_type`, `cost.workflows`): an agent type that runs dozens of
     times on the strongest tier (critics, reviewers, explorers) is usually the largest saving.
     Exploration and search agents are good candidates for a faster tier; critics that decide
     whether work passes may need the strong tier but rarely high effort. Check `tool_errors` per
     type before downgrading.
   - **Effort** (`by_effort`, `primary_effort`, matrix `efforts`): high or xhigh effort on short,
     uncorrected sessions is the effort version of "heavy model on trivial work". Low effort on
     sessions with strong corrections may be too little thinking. Recommend effort per task type in
     `guide[].effort`.
   - **Cost drivers** (`cost.top_sessions[].drivers`): many cache writes point at context rebuilt
     often (long sessions, resumes, compactions); large cache reads at a big context re-read every
     turn (`/clear` or a handoff helps); subagent share at delegation patterns.
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
