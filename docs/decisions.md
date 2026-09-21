# Decisions

Non-obvious choices, newest last. One entry: date — context → decision → why.

- 2026-09-21 — Guide assumes `~/amber` → repo lives at `main/cs-dev/dev@solo/sophomore/amber`, pushed to github.com/dhruvraajeev/amber (public) → owner's folder layout; public keeps Actions + ghcr.io free.
- 2026-09-21 — Plan §6 puts `IMPLEMENTATION_PLAN.md` and Step 1 puts `LEARNING_LOG.md` in the repo → both live in sibling `../learnAmber/` and are gitignored → owner's call, so handoff edits don't create commits.
- 2026-09-21 — §11.3 `--ok` #A8B060 and `--warn` #E8913A have ~equal luminance (1.06:1), failing Step 2's "distinguishable in greyscale" check → `--ok` darkened to #848C48 (same olive hue; ≥1.34:1 vs warn and crit, 5.2:1 on `--bg`), enforced by `theme.test.ts` → keeps the plan's palette and satisfies its own acceptance. The chart ramp keeps #A8B060.
- 2026-09-21 — Tailwind's default color palette is reset (`--color-*: initial`) so only §11.3 tokens exist as utilities → makes "no blue/cyan/purple/gray" a build-time fact, not a review item.
