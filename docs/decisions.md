# Decisions

Non-obvious choices, newest last. One entry: date — context → decision → why.

- 2026-09-21 — Guide assumes `~/amber` → repo lives at `main/cs-dev/dev@solo/sophomore/amber`, pushed to github.com/dhruvraajeev/amber (public) → owner's folder layout; public keeps Actions + ghcr.io free.
- 2026-09-21 — Plan §6 puts `IMPLEMENTATION_PLAN.md` and Step 1 puts `LEARNING_LOG.md` in the repo → both live in sibling `../learnAmber/` and are gitignored → owner's call, so handoff edits don't create commits.
- 2026-09-21 — §11.3 `--ok` #A8B060 and `--warn` #E8913A have ~equal luminance (1.06:1), failing Step 2's "distinguishable in greyscale" check → `--ok` darkened to #848C48 (same olive hue; ≥1.34:1 vs warn and crit, 5.2:1 on `--bg`), enforced by `theme.test.ts` → keeps the plan's palette and satisfies its own acceptance. The chart ramp keeps #A8B060.
- 2026-09-21 — Tailwind's default color palette is reset (`--color-*: initial`) so only §11.3 tokens exist as utilities → makes "no blue/cyan/purple/gray" a build-time fact, not a review item.
- 2026-09-21 — `agent-self-hosted` needs a `profileId` but `shared/profiles/` is filled only by calibration (Part 2) → the template uses `"profileId": "default"`; the backend must ship a matching uncalibrated default profile when self-hosted LLMs land (Step 22) → keeps the template valid against §7 without inventing calibration data now.
- 2026-09-21 — JSON imports widen string literals, so tsc can't check templates against `Design` → `contracts.test.ts` compares every template node to a type-checked exemplar (same keys, same value types, known enum values, preset ids that exist) → catches `p50` vs `p50Ms` and unknown/missing fields at test time.
- 2026-09-21 — GPU `usdPerHour` in `gpus.json` are rough on-demand numbers instead of Appendix A's `0.0` → a $0 GPU makes the cost card meaningless in demos; all stay `verifiedAt: null` and are labeled "verify".
- 2026-09-21 — §18 said one branch + PR per phase → all work goes straight onto `main`, pushed after each step; `phase-0-ui-shell` deleted after its Step 3 commits were replayed onto main → owner prefers a linear, no-merge workflow. CI runs on pushes to main.
- 2026-09-21 — CLAUDE.md was committed in Step 1 → untracked and gitignored; it stays on the owner's disk in the repo folder (so Claude Code still auto-loads it) but is never pushed again → owner's call.
