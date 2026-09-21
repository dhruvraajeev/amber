# Amber — rules for Claude
- The spec is ../learnAmber/IMPLEMENTATION_PLAN.md (outside the repo; session handoffs go in
  ../learnAmber/LEARNING_LOG.md). Never commit either file. Contracts (§7) and the simulation model (§8) are law.
- One step at a time from §18. Don't start the next step unless asked.
- After each step: files changed, a 4–6 sentence plain-English explanation, verify commands.
- Five pieces are "owner writes by hand" (Steps 10, 11, 16, 21, 28). Leave TODO stubs; review,
  don't rewrite.
- ZERO SPEND: never introduce anything that can bill me. No Azure Container Registry (use ghcr.io),
  no Datadog, no rented GPUs, no min-replicas above 0. Before any cloud step, state in one line
  what it costs and why that is zero. If you can't honestly say zero, stop and ask.
- Never ask for secrets in chat. Secrets live in .env, GitHub secrets, or Azure secrets.
- Log non-obvious choices in docs/decisions.md. Out-of-scope ideas go in docs/later.md.
- Prefer clear code over clever code.
- Visual identity is warm: sepia, amber, orange, rust, brown. Use only the theme.css tokens (§11.3);
  never add blue, cyan, purple, or neutral gray.
