# Official prompt library

Read this when filling `official_prompts` in insights.json. The prompts come from the Claude Code
prompt library (https://code.claude.com/docs/en/prompt-library) and live in
`assets/prompt-library.json` (each entry: `id`, `phase`, `category`, `source`, `prompt`). Use the exact `id`; the report looks
the prompt up by it and warns about ids it does not know.

Recommend 0 to 3, never the whole list. Same rule as techniques: an official prompt earns a place
only when the user's own sessions show the situation it fits, so each needs `why_for_you` with a
session id or a number. Skip the section when nothing fits; do not pad it. A prompt the user already
writes in this style belongs under strengths.

A technique and an official prompt can point at the same habit. Then the technique explains the
method and the official prompt is the ready-to-send wording; do not repeat the same text in both.

## Picking by signal

| What the data shows | Library ids to consider |
|---|---|
| Big first prompt for a multi-file change, scope cut later | `plan-a-multi-file`, `narrow-the-scope-of`, `scope-a-change-before` |
| One-line prompt for a feature with many choices | `draft-a-spec-by`, `map-edge-cases-before` |
| Many turns exploring code the agent had to learn | `get-oriented-in-a`, `explain-unfamiliar-code`, `find-where-something-happens`, `see-what-depends-on` |
| Same correction in 2+ sessions | `turn-a-correction-into`, `capture-what-to-remember` |
| Fix told "not right" and redone | `course-correct-a-wrong`, `narrow-the-scope-of` |
| Bug fix bounced back, or failing test described loosely | `find-and-fix-a`, `investigate-a-reported-error`, `fix-a-build-error` |
| Feature right in code, wrong on screen | `implement-from-a-screenshot`, `fix-a-precise-visual` |
| Output style keeps missing | `follow-an-existing-pattern`, `draft-from-past-examples` |
| Tests written after, or not run | `write-tests-run-them`, `drive-implementation-from-tests` |
| Commits or PRs written by hand each time | `commit-with-a-generated`, `open-a-pull-request`, `review-your-changes-before` |
| Renames or migrations done file by file | `migrate-a-pattern-across`, `find-and-update-copy` |
| A multi-step routine typed again and again | `turn-a-recurring-task`, `add-a-hook-for` |
| Production or CI trouble | `investigate-a-production-incident`, `query-logs-in-plain`, `write-a-ci-workflow` |

## Filling the prompt

- `{slots}` in the library text are placeholders. Replace each with the user's real file, feature or
  term from `summary.json`, in the user's language. Keep the library wording around them; that is the
  point of recommending an official prompt.
- Leave a `<placeholder>` only for what you cannot know.
- Never invent a path or ticket number. If the session data does not name one, use a placeholder.
- Quote the library text unchanged when it has no slots.
