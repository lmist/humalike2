---
title: Humalike Research Source Index
description: Local catalog of preserved documentary and code sources for the API recreation.
tags: [humalike, sources]
status: complete
---
# Source index

This project preserves four primary documentary/code source groups:

- [Humalike documentation corpus](./docs/source.md): discovery indexes, consolidated documentation, and individually fetched pages.
- [HUMA paper source](./papers/arXiv-2511.17315v1/source.md): LaTeX, bibliography, and included figures.
- [LoSoNA paper source](./papers/arXiv-2606.14600v1/source.md): LaTeX, bibliography, and included figures.
- [Hermes Humalike plugin source](./hermes-humalike-plugin/source.md): public client implementation and tests.

Production behavior is not represented by stored responses. It is established by the committed [realtime suite](../tests/realtime/run.mjs), [intelligence suite](../tests/intelligence/run.mjs), and their [research digests](../research/index.md). The normative rebuild contract is the [specification](../spec/00-index.md).