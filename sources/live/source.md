---
title: Live Humalike API Fixtures
description: Redacted production API request and response observations captured on 2026-08-20.
tags:
  - humalike
  - source
  - live-api
  - fixtures
retrieved_at: 2026-08-20
---
# Live API fixtures

[raw-experiments.json](./raw-experiments.json) contains redacted production observations for authentication failures, token verification, usage, thread opening, event recording, turn decisions, reply scheduling, Social Memory ingest/idempotent replay/recall/ask, and validation failures. Authorization values, account identity, and the WebSocket grant query are redacted. The API key itself was never written to this file.

The probes deliberately avoided deletes, account mutation, bulk generation, rate-limit hammering, and large requests. See the [live experiment report](../../research/live-api-experiments.md) for interpretation and discrepancies from documentation.