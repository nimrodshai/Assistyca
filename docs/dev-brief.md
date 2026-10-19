# Dev brief: Assistyca

How to change code in this repository without stepping on anyone. The general
method lives with the developer (Dean, in the user's Claude settings);
`AGENTS.md` holds the project's coding rules and wins over both.

## Branches

- `staging` is the working branch and deploys to the staging service on push.
- `main` is production. Nothing goes there unless the owner says so in the
  request.

## The checkout is shared

Several sessions work in `/Users/nimrodshai/Documents/Projects/AgentsForAll`
at once. Its local `main` is stale and full of other sessions' uncommitted
files; never edit, stage or commit there, and never use its index.

Work in your own detached worktree of `origin/staging`:

    git fetch origin
    git worktree add --detach <scratch dir>/wt origin/staging
    # edit, test, commit inside <scratch dir>/wt
    git fetch origin && git rebase origin/staging
    git push origin HEAD:staging
    git worktree remove <scratch dir>/wt

Rebase right before pushing; other sessions push to `staging` too. If the
rebase conflicts in a file you didn't touch, stop and report rather than
resolve someone else's work.

## Tests

- `/usr/bin/python3 -m unittest tests.test_a tests.test_b` for the modules
  that cover the files you changed (`grep -l <module> tests/test_*.py`).
  Don't run the whole suite with `discover`: a test reaches the network here
  and hangs.
- Before pushing: `git show HEAD -- tests/ | grep '^-    def test'` and
  account for every name it prints. A slice once deleted four unrelated
  tests.
- Run `python3 scripts/check_package_layout.py` if you moved shared code.
- The harnesses (simulator, mock families, conversation eval) and how to run
  them are in `docs/qa-brief.md`. They call OpenAI on the key in `~/.zshrc`;
  if it is rejected, say so and rely on unit tests.

## Rules that bite here

- What the assistant says is written by the model. Code gives it the facts
  and a short instruction; a sentence assembled in code is only the fallback
  (`AGENTS.md`, "Shared Capability Rules"). The shared voice is
  `packages/infrastructure/assistant_voice.py`.
- Every LLM call goes through `packages/infrastructure/openai_api.py` and
  declares a `TaskComplexity`.
- A new capability is a `ToolSpec` in `agent_loop.py`.
- Production's database is older than the schema: a new index over a column
  added by a migration can boot in tests and crash production. Guard it.
- Commit messages: short, specific, in plain words about what changed for
  the family.
