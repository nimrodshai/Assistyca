# Assistyca Working Rules

This file is the default operating guide for work in this repository.

When working here:
- Read this file first.
- Prefer shared, reusable components over one-off duplication.
- Keep feature-specific work isolated from shared infrastructure.
- Add new rules here when they become stable enough to reuse.

## Core Structure

- `packages/tools/` for reusable user-facing tools.
- `packages/infrastructure/` for shared backend support such as auth, billing, persistence, and delivery helpers.
- Keep `packages/` free of loose root-level modules and compatibility shims.
- If code moves between package areas, delete the old path in the same change and update imports immediately.
- `portal/` for the user-facing web pages and the chat workspace.
- `scripts/` for shared automation such as setup, sync, evals, and deploy helpers.
- `docs/` for internal process notes, onboarding, and operating guidance.
- `docs/product-brief.md` for what a product review (feature value and the assistant's voice) needs to know about this project.
- `docs/qa-brief.md` for what a QA pass needs to know: live code, how to run the tests, harnesses and a local app, and the flows to cover.
- `docs/dev-brief.md` for how to change code here: the working branch, the shared checkout, and how to test and push.

## Reuse Rules

- If a piece of logic is likely to be used by more than one feature, put it in shared infrastructure.
- If a file only changes because of a single feature, keep it with that feature.
- If you copy something twice, stop and consider moving it into shared code.
- Prefer config over custom code when the difference is mostly a setting, not a behavior.
- Keep the portal generic and data-driven so the same surface can serve every family.

## Shared Capability Rules

- A new thing the assistant can do is a `ToolSpec` in `packages/infrastructure/agent_loop.py`, not a new branch in a turn: declare what it needs connected, whether it changes anything, whether it needs a yes, and return the shared result envelope.
- Code never writes a customer-facing sentence for a failure. Build a situation report (`packages/infrastructure/recovery_reply.py`) and let the composer write it; the assembled sentence is the floor, never the design.
- Build reusable capabilities around stable family workflows such as intake, scheduling, reminders, the family week, and knowledge retrieval.
- Keep shared capabilities generic and parameterized.
- Avoid embedding account names, secrets, or one-family assumptions in shared code.
- For insurance, keep the supplied policy wording as the authority and its structured coverage as a versioned index. Never overwrite an earlier version, never present a summary-only receipt match as confirmed coverage, and always retain the evidence pointer behind a source-backed match.

## OpenAI Access

- All tools and shared services must use `packages/infrastructure/openai_api.py` as the single integration point for OpenAI requests.
- Do not call the OpenAI API directly from tool code, feature code, or portal code.
- If a workflow needs new OpenAI behavior, extend the centralized gateway first so request construction, event emission, token tracking, and billing stay consistent.

## Model Selection

- Every task that calls an LLM must declare a `TaskComplexity` level from `packages/infrastructure/task_complexity.py`.
- The level decides the model: `IMPORTANT` runs on the strongest model, `MEDIUM` on the mid tier, `SMALL` on the cheapest.
- Do not hardcode a model name at a call site. Change the mapping in `task_complexity.py` instead.
- Environment variables stay available as per-task overrides for incident response, not as the normal way to pick a model.
- Pick the level from the work, not the feature's importance: open-ended reasoning is `IMPORTANT`, constrained drafting or structured edits are `MEDIUM`, short mechanical extraction is `SMALL`.
- The level also decides how hard the model thinks: pass `resolve_task_reasoning(complexity, ...)` as `reasoning` on conversational calls, and size `max_output_tokens` to include that thinking. A budget the thinking uses up comes back as an incomplete reply; the gateway retries it once with double the room, and raises `OpenAIIncompleteError` if there is still no text.

## Secrets And Access

- Never commit secrets to the repo.
- Use environment variables or a secret manager for credentials.
- Keep access scoped to the minimum needed for each integration.

## Scripts And Automation

- Prefer a shared script over a one-off manual process when a task may repeat.
- Name scripts by intent, not by feature.
- Keep setup and deployment scripts reusable whenever possible.
- Run `python3 scripts/check_package_layout.py` after moving shared code between package folders.

## Git Workflow

- In every thread, if you make a repo change, finish by committing it and pushing it to the `staging` branch before you hand back unless the user explicitly asks you not to. Render deploys `staging` to the staging service automatically.
- `main` is production: the production service deploys from it automatically, so a push to `main` is a production deploy. Merge `staging` into `main` only when Nimrod says to push prod, never on your own.
- Use focused commits with short, specific messages.
- If a change must stay local, say so clearly before you leave it uncommitted.

## New Work Checklist

Before adding anything new, ask:
- Is this reusable?
- Does this belong to a single feature?
- Can this be config instead of code?
- Will another feature likely need this later?

If the answer suggests reuse, implement it once in shared code and connect features through configuration.
