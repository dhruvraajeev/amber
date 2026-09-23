# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Engineers who design systems that call LLMs, and people reviewing the owner's work (the project is also a portfolio piece). They sketch an architecture on a canvas, set traffic, run a simulation, and read what broke and what it costs, usually at a desk on a laptop or large monitor, in bursts of edit → run → compare.

## Product Purpose

Amber is a visual simulator for AI application architectures: "a flight simulator for AI apps". Users draw a system from seven building blocks (users, load balancer, service, cache, database, agent, LLM), set expected traffic, and run a deterministic discrete-event simulation that predicts latency percentiles over time, time to first token, per-component utilization and queues, GPU KV-cache pressure, monthly cost, and the bottleneck in plain English. Success is finding out what breaks and what it costs before building it.

## Positioning

It models the inference layer realistically (hosted API vs self-hosted GPUs, continuous batching, prefill vs decode, KV-cache memory, speculative decoding), and its LLM models are calibrated against real measurements with the measured error published. General system-design simulators don't do either.

## Operating Context

One screen: palette, canvas, inspector, run bar, results drawer (summary, latency, load, GPU, cost, bottlenecks, attribution), timeline playback, a Compare page for two pinned runs, and a model-assumptions popover. Keyboard: Delete removes, Esc clears selection, R runs, Space plays/pauses. Until phase 2 the results come from a seeded fake, shown by a "Demo data" badge.

## Capabilities and Constraints

- Stack: Vite + React 19 + TypeScript, Tailwind v4, React Flow (@xyflow/react), Zustand. Hand-rolled SVG charts, no chart library.
- Contracts (plan §7) and the simulation model (plan §8) are fixed; the UI never changes data shapes.
- Zero spend: nothing may bill the owner.
- Limits shown in the UI: ≤50 nodes, ≤100 edges, 10–600 s runs, ≤200k requests.
- Not built: accounts, collaboration, streaming progress, undo/redo.

## Brand Commitments

- Name: Amber. Dark, softly lit, professional; never over the top.
- Owner-pinned palette (2026-09-23): near-black ground, subtle red and orange throughout, hints of white, lit with restrained glows and gradients. Replaces the plan's earlier sepia/amber palette.
- Owner-pinned references: a dark rounded-card finance dashboard (heaviest UI reference), forge-beta-pied.vercel.app, the owner's site dhruvkraajeev.vercel.app, a HUD "mission deck" dashboard (moderate), and React Bits interaction concepts.

## Evidence on Hand

Three starter templates (`shared/templates/`) and presets (`shared/presets/`). Results are demo data from `api/fake.ts` until the backend lands. No calibration numbers, users, or testimonials exist yet; don't invent them.

## Product Principles

1. The canvas is the product: every surface serves reading the system under load.
2. Numbers carry units and never rely on color alone.
3. Same seed, same result: the UI never implies randomness it doesn't have.
4. Honest about being a model: assumptions stay one click away.

## Accessibility & Inclusion

Keyboard reachable controls, text summaries for every chart, ≥4.5:1 text contrast, status never conveyed by hue alone, prefers-reduced-motion respected.
