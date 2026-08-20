---
title: Humalike Research Index
description: Distilled evidence grounding the Humalike API recreation specification.
tags: [humalike, research, index]
status: complete
---
# Research index

Production behavior is established by executable live tests:

- [Live-tested realtime and memory API](./tested-realtime-memory.md) — 60 assertions covering HTTP, WSS, turn-taking, Social Signals negative behavior, memory, idempotency, and billing.
- [Live-tested intelligence and personas API](./tested-intelligence-personas.md) — 592 assertions covering learning, foresee, observability, audit, personas, endpoint errors, timings, and polling cost.

Supporting research supplies documentary surface and implementation rationale:

- [Documented API surface](./docs-api-surface.md) — documented endpoints, limits, billing, and claimed errors; live results supersede conflicts.
- [Hermes plugin analysis](./plugin-analysis.md) — client request conventions, configuration, resilience, WSS consumption, and refresh cadence.
- [HUMA paper digest](./paper-huma.md) — group-chat routing, timing, interruption, reflection, and evaluation.
- [LoSoNA paper digest](./paper-losona.md) — local-norm evaluation design, prompt conditions, metrics, and results.
- [Early live experiment synthesis](./live-api-experiments.md) — the initial limited probe conclusions, reconciled with the exhaustive suites.

Primary documentary materials are cataloged in the [local source index](../sources/index.md). The normative rebuild contract begins at the [specification index](../spec/00-index.md).