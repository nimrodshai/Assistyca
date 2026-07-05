# Assistyca Working Rules

This file is the default operating guide for work in this repository.

When working here:
- Read this file first.
- Prefer shared, reusable components over client-specific duplication.
- Keep client-specific work isolated from shared infrastructure.
- Add new rules here when they become stable enough to reuse.

## Core Structure

- `packages/tools/` for reusable client-facing tools.
- `packages/infrastructure/` for shared backend support such as auth, billing, persistence, and delivery helpers.
- Keep `packages/` free of loose root-level modules and compatibility shims.
- If code moves between package areas, delete the old path in the same change and update imports immediately.
- `clients/` for per-client configuration, knowledge, overrides, and tests.
- `portal/` for the client-facing guidance editor and preview workspace.
- `scripts/` for shared automation such as setup, sync, evals, and deploy helpers.
- `docs/` for internal process notes, onboarding, and operating guidance.

## Reuse Rules

- If a piece of logic is likely to be reused by more than one client, put it in shared code.
- If a file only changes because of a particular customer, keep it under that client.
- If you copy something twice, stop and consider moving it into shared code.
- Prefer config over custom code when the difference is mostly business-specific.
- Keep the portal generic and data-driven so the same surface can support many clients.

## Client Folder Rules

- Each client gets its own folder under `clients/`.
- Keep client folders small and focused.
- Store only that client's business context, knowledge, overrides, and tests there.
- Do not place shared libraries or generic helpers inside a client folder.

## Shared Capability Rules

- Build reusable capabilities around stable workflows such as intake, scheduling, quoting, follow-up, handoff, and knowledge retrieval.
- Keep shared capabilities generic and parameterized.
- Avoid embedding client names, client secrets, or client-specific assumptions in shared code.

## Secrets And Access

- Never commit secrets to the repo.
- Use environment variables or a secret manager for credentials.
- Keep access scoped to the minimum needed for each client integration.

## Scripts And Automation

- Prefer a shared script over a one-off manual process when a task may repeat.
- Name scripts by intent, not by client.
- Keep setup and deployment scripts reusable whenever possible.
- Run `python3 scripts/check_package_layout.py` after moving shared code between package folders.

## Git Workflow

- In every thread, if you make a repo change, finish by staging, committing, and pushing it before you hand back unless the user explicitly asks you not to.
- Use focused commits with short, specific messages.
- If a change must stay local, say so clearly before you leave it uncommitted.

## Scope Spec Workflow

- Keep the source spec for each client in `clients/<client-id>/spec/spec.json`.
- Keep the generated approval PDF beside the source spec.
- Use `scripts/generate_spec_pdf.py` to render spec PDFs from the JSON source.
- Treat anything not explicitly listed in the spec as out of scope until the spec is revised.

## New Work Checklist

Before adding anything new, ask:
- Is this reusable?
- Is this client-specific?
- Can this be config instead of code?
- Will another client likely need this later?

If the answer suggests reuse, implement it once in shared code and connect clients through configuration.
