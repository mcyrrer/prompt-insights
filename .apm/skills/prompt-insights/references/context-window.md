# Context window: knowledge base

Read this when filling `context_window` in insights.json (planned, see the implementation plan in the
conversation that created this file) or when judging the context numbers in `summary.json`. It was compiled on 2026-10-18 from the sources listed at the
end, so the skill never has to fetch a web page at run time. Prices, limits and version numbers
change: tell the user to re-check `/context`, `/usage` and `/model` for the current values.

## 1. What the context window is

- Everything the model reads for one request: system prompt, tool definitions, CLAUDE.md and auto
  memory, every earlier message, every tool result, images, and the model's own output including
  thinking. Claude Code re-sends the full conversation on every request.
- **Context rot:** more is not better. As tokens accumulate, accuracy and recall degrade. Curating
  what is in context matters as much as how much space is left.
- Anthropic's own summary: "Claude's context window fills up fast, and performance degrades as it
  fills." It is "the most important resource to manage".
- Token fields in a transcript's `usage`: `input_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens`. **All three count toward the window.** Prompt size of one request =
  their sum (`pricing.context_tokens`). Output tokens (including thinking) come on top.

## 2. Window sizes and compaction

| Fact | Value |
|------|-------|
| Native 1M window, no suffix needed | Fable 5.x, Sonnet 5 and later, Haiku 5.5, Opus 4.7 and later |
| 1M only via `[1m]` variant | Opus 4.6, Sonnet 4.6 (e.g. `/model opus[1m]`) |
| 200K window | older models, and any model when `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` |
| Default auto-compact point | the model's limit; about 967K tokens on native-1M models |
| Auto-compact window setting | `/autocompact 500k`, `claude --autocompact auto`, `"autoCompactWindow": 200000` in settings, env `CLAUDE_CODE_AUTO_COMPACT_WINDOW`; valid range 100K to 1M |
| Disable compaction | env `DISABLE_COMPACT` |
| Haiku 5.5 | over 100K prompt tokens costs more per token (other 1M models: standard pricing) |

Consequence for analysis: on a 1M model auto-compaction fires very late (near 967K), so "no
compaction happened" does **not** mean the context stayed healthy. Judge by absolute size and by
how long a session ran, not by compaction count alone. The window per message must come from the
model id in the transcript; if the id is unknown, say the window is unknown instead of guessing.

## 3. What loads automatically (the baseline)

From Anthropic's "Explore the context window" simulation (illustrative sizes, 200K scale):
system prompt (~4K), auto memory MEMORY.md (first 200 lines or 25 KB), environment info and git
status, MCP tool names (schemas deferred by default via tool search), skill descriptions (one line
each; skills with `disable-model-invocation: true` cost nothing until invoked), global CLAUDE.md,
project CLAUDE.md, path-scoped rules (load when a matching file is read). Reading a file adds its
full content (the user sees only "Read auth.ts"). Hooks add context only via
`hookSpecificOutput.additionalContext`.

Measurable proxy: the context size of the **first main-conversation request** of a session is the
startup baseline (system prompt + CLAUDE.md + memory + skills + MCP names). A large baseline is paid
on every request of every session.

## 4. What compaction does

- `/compact [instructions]` or auto-compaction replaces the history with a structured summary
  (code patterns, file states, key decisions). Skills the user invoked are re-injected, capped at
  5,000 tokens per skill; the startup skill listing is **not** re-injected.
- CLAUDE.md is reloaded from disk after `/clear` and `/compact`. Edits to CLAUDE.md mid-session do
  not apply until then.
- Custom compaction guidance goes in CLAUDE.md, e.g. a `# Compact instructions` section ("When
  compacting, always preserve the full list of modified files and any test commands"), or inline:
  `/compact Focus on the API changes`.
- Partial compaction: `Esc Esc` or `/rewind`, pick a checkpoint, then **Summarize from here** or
  **Summarize up to here**.
- Compacting is itself a large request (it reads the whole conversation). While the cache is warm it
  costs a fraction of the context size; after an idle gap longer than the cache TTL it reprocesses
  everything uncached. Best moment: at a natural break between tasks, not mid-task.
- If a path is abandoned, `/rewind` to an earlier turn is cheaper than compacting: it truncates to a
  prefix that is already cached.
- `idleCompaction` setting (v2.1.290+): Claude Code can compact an idle long conversation shortly
  before a 1-hour cache expires; set to `false` to turn off.

## 5. Prompt cache and the cost of a big context

- Every request re-reads the whole history at the **cached token rate** (cheaper than input, not
  free). So a one-line question in a huge, day-old session still draws usage for the whole
  conversation. Cost scales with context size times number of requests.
- **Cache TTL:** 1 hour on a Claude subscription within plan usage (main conversation); 5 minutes on
  an API key, cloud provider, subagents, compaction helper requests, or once subscription usage
  credits are in use. Configurable: `promptCacheTtl` / `CLAUDE_CODE_PROMPT_CACHE_TTL` (`5m`|`1h`,
  v2.1.242+). A request after a gap longer than the TTL is a **cache miss**: the full context is
  re-processed and re-written.
- In transcripts, `usage.cache_creation.ephemeral_1h_input_tokens` vs `ephemeral_5m_input_tokens`
  tells which TTL a write used (when present).
- **Actions that invalidate the cache** (next request is slow and expensive): switching model
  (each model has its own cache; `opusplan` switches on every plan-mode toggle), changing effort on
  most models (not Opus 5.5, Sonnet 5.5, Haiku 5.5, Fable 5.1 on API key/subscription), turning on
  fast mode, adding/removing MCP servers when tools are not deferred, denying a whole tool when tool
  search is off, compaction, accumulating many images, upgrading Claude Code.
- **Actions that keep the cache:** editing files, editing CLAUDE.md mid-session, changing permission
  mode, changing output style, invoking skills/commands, `/recap`, `/rewind`, spawning a subagent.
- Advice from the docs: pick model and effort at the top of a session; save `/compact` for natural
  breaks.
- `/usage` shows a `Prompt cache (main)` line (v2.1.251+): hit share, misses, expected rebuilds,
  warm/cold. On subscription plans it also flags "long context" and "cache misses" when they account
  for 10% or more of recent usage.

## 6. Habits that keep context healthy (with the doc's own wording)

| Habit | Why / how |
|-------|-----------|
| `/clear` between unrelated tasks | "Stale context wastes tokens on every subsequent message." Use `/rename` first, `/resume` later. Clearing costs nothing. |
| Two failed corrections means start over | "If you've corrected Claude more than twice on the same issue in one session, the context is cluttered with failed approaches. Run `/clear` and start fresh with a more specific prompt." |
| Subagents for investigation | They read many files in a separate context and return a summary (example in the docs: 6,100 tokens read, 420 returned). Also for tests, docs fetching, log processing. |
| `/btw` for side questions | The answer never enters conversation history. |
| Scope investigations | Unscoped "investigate" makes Claude read hundreds of files (the infinite exploration failure pattern). |
| Specific prompts | "improve this codebase" triggers broad scanning; name file, symptom and expected result. |
| Plan mode for complex work | Prevents expensive re-work from a wrong direction; skip it for one-sentence diffs. |
| Course-correct early | `Esc`, then `/rewind` or "undo that" rather than piling corrections on. |
| Keep CLAUDE.md short | Under about 200 lines; only what applies broadly; move workflow-specific instructions to skills (loaded on demand); a bloated file makes Claude ignore rules. `/doctor` proposes cuts. |
| Trim MCP overhead | Tool definitions are deferred by default; still run `/mcp` and disable unused servers; prefer CLI tools (`gh`, `aws`, `gcloud`) which add no per-tool listing. |
| Hooks to shrink output | A PreToolUse hook can filter a 10,000-line log or test run down to the failures. |
| Right model and effort | Sonnet for most coding, Opus for hard reasoning; lower `/effort` for simple tasks (thinking tokens are billed as output and, on newer models, stay in context). |
| Track it | `/context` shows what consumes space; a status line can show context usage continuously (the `context_window` object, `current_usage` with cache fields). |
| Resume carefully | `--continue`/`--resume` re-sends the whole history; an old session resumed after the TTL pays a full uncached re-read. |

## 7. Failure patterns named by Anthropic

1. **Kitchen sink session:** one task, then an unrelated one, then back. Fix: `/clear` between tasks.
2. **Correcting over and over:** context polluted with failed approaches. Fix: after two failed
   corrections, `/clear` and write a better first prompt.
3. **Over-specified CLAUDE.md:** important rules get lost. Fix: prune, or convert to a hook.
4. **Infinite exploration:** unscoped investigation. Fix: scope it or use a subagent.
5. **Trust-then-verify gap:** (not context-specific) give a check Claude can run.

## 8. What the transcripts can and cannot show

Measured today by `analyze_sessions.py`: per-session `peak_context_tokens` (max prompt size of any
main-conversation request), `compactions`, tokens by type per model, `corrections_strong`,
slash commands, subagent counts, models and effort per message.

Not measured today (needs the planned extension): context size over time, the startup baseline, the
number of requests made at large sizes, idle gaps longer than the TTL, `/clear` and `/compact`
usage per session, large tool results (which tools bloat the context), the model's actual window.

Cannot be measured from transcripts: what `/context` showed, auto-compact settings the user changed
outside the sampled sessions, true billed cost, quality loss from context rot. Say so; offer
heuristics, not verdicts.

## 9. Heuristic thresholds (implemented in `scripts/context.py`) (the skill's own choices, not from Anthropic)

Anthropic gives no numeric "unhealthy" line for a 1M window, so these are tunable defaults. Show
them in the report as "flagged because..." with the measured numbers and call them rules of thumb.

| Signal | Default flag |
|--------|--------------|
| Startup baseline | first request over 30K tokens (200K-window models: over 15% of the window) |
| Long-lived context | a session spent 30% or more of its requests above 200K tokens |
| Very large context | peak above 400K tokens |
| No hygiene in a big session | peak above 200K, zero `/clear`, zero `/compact`, zero compactions |
| Kitchen sink | judged by the model from the prompts (not an automatic flag): one session mixes 3 or more unrelated goals |
| Correction spiral | 3 or more strong corrections on the same theme with no `/clear` or `/rewind` between |
| Cache-miss tax | 2 or more gaps longer than the cache TTL followed by a big-context request |
| Mid-task model/effort switch at large context | switch while context is above 100K |
| Heavy reads in main context | a single tool result over 20K tokens (chars / 4 estimate) with no subagent used in that session |

## Sources (fetched 2026-10-18)

- Manage costs effectively: https://code.claude.com/docs/en/costs
- Best practices for Claude Code: https://code.claude.com/docs/en/best-practices
- Explore the context window: https://code.claude.com/docs/en/context-window
- How Claude Code uses prompt caching: https://code.claude.com/docs/en/prompt-caching
- Model configuration (auto-compact window, 1M per model): https://code.claude.com/docs/en/model-config
- Context windows (API): https://platform.claude.com/docs/en/build-with-claude/context-windows
- Effective context engineering for AI agents: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Status line (context fields): https://code.claude.com/docs/en/statusline

## Subscription versus API key

The report assumes a Claude subscription: 1-hour cache lifetime for the main conversation. The
transcript's cache-write type (`ephemeral_1h` or `ephemeral_5m`) is used when present. An API-key or
cloud-provider user has a 5-minute lifetime by default, so idle gaps over 5 minutes already cost a full
cache rewrite and the cache-miss numbers in the report understate their case. Subagent and compaction
requests use 5 minutes even on a subscription. Cost impact is an estimate at list prices.
