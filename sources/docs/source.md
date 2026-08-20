---
title: Humalike Documentation Corpus
description: Preserved raw Humalike public API documentation fetched on 2026-08-20.
tags:
  - humalike
  - source
  - documentation
source_url: https://docs.humalike.com/llms.txt
retrieved_at: 2026-08-20
---
# Humalike documentation corpus

The raw discovery index is preserved as [llms.txt](./llms.txt), and the complete consolidated export as [llms-full.txt](./llms-full.txt). The `pages/` directory contains 29 separately fetched page bodies corresponding to every link in the discovery index. These raw text artifacts are intentionally unmodified and provide the documentary baseline for the API surface.

The corpus states `https://api.humalike.com` as the production base URL and specifies `Authorization: Bearer <token>` for every endpoint. Its endpoint descriptions, examples, limits, billing notes, and error tables are distilled in [the documentation API-surface note](../../research/docs-api-surface.md).