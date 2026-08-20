---
title: Core Engine Design
description: Algorithms and model pipelines implementing humanlike timing, norm adaptation, memory, analysis, and personas.
tags:
  - humalike
  - specification
  - engine
  - algorithms
status: complete
---
# Core engine design

## Turn router

Implement HUMA's strategy router over a configurable catalog of approximately 20 strategies. For each thread state and inbound batch, one structured-output model call returns appropriateness `A_s ∈ [0,1]` for each strategy. Maintain a recency ring of length `N` and compute `T_s=min(1,k/N)` for last use `k` steps ago; exempt Keep Silent, Directly Mentioned, Continue Pending, and Tell a Story with `T_s=1`. Select maximum `A_s+T_s`, with deterministic tie-breaking and explicit policy overrides for `skip_decide`, media, safety, direct mention, and account configuration. [HUMA paper digest](../research/paper-huma.md)

Persist prompt/model/version/scores/selection/latency for replay. A production catalog MUST include a strategy id, description, eligibility predicate, timeliness exemption, and tool policy. Because the paper does not publish all 20 definitions or prompts, keep this catalog versioned and test behavior, not assumed wording. [HUMA paper digest](../research/paper-huma.md)

## Epoch interruption

Each accepted batch increments thread epoch inside a serializable transaction. Model work records its source epoch. Respond atomically compares source/current epoch before charging or scheduling. Incoming events during generation are queued; stale intention/scratchpad are included in the next router context so Continue Pending can recover. This is the service equivalent of HUMA's interruption architecture. [HUMA paper digest](../research/paper-huma.md)

## Reply refinement and pacing

A structured Theory-of-Mind pass receives thread transcript, recalled context, local voice card, agent name/system prompt, and draft. It returns predicted reception, risk factors, refined content, and confidence. A naturalizer then splits content into 1–5 bubbles while preserving meaning. The production fixture proves that even a short draft may be paraphrased. [Live API experiments](../research/live-api-experiments.md)

For each bubble, derive words and typing time from `60000 * words / typing_wpm`, clamp to configured minimum and `max_typing_ms`, add optional reading delay before the first bubble, and add a small configurable inter-bubble pause. Persist the full schedule before publishing. Emit typing true, ordered message frames at delivery timestamps, then typing false. Default service values are unknown; the Hermes client chooses 115 WPM while docs mention a stock 150 WPM, so defaults MUST be parity-configurable. [Plugin analysis](../research/plugin-analysis.md)

## Social norm adaptation

Use LoSoNA's norm-informed approach as one signal, not an unconditional prompt. Retrieve analogous precedent turns and infer candidate local norms with evidence. Inject a compact voice/norm card into Router and refinement. Gate adoption by confidence, recency, and safety policy; models in LoSoNA sometimes regressed under explicit norm prompting. [LoSoNA paper digest](../research/paper-losona.md)

Build a continuous evaluation set using the released scenario structure: 20–34-turn group chats, two or three demonstrations, one elicitor, three samples, fixed judge, majority accuracy, compliance, consistency, paired recovery/regression, and scenario bootstrap intervals. Maintain both naive and norm-informed canaries per model. [LoSoNA paper digest](../research/paper-losona.md)

## Social Memory

Store raw attributed messages append-only. Asynchronously extract subject-centric facts `{subject,predicate,value,evidence_message_ids,confidence,valid_from,invalidated_by}` and embeddings. Recall combines speaker-aware query embedding, lexical/entity retrieval, recency, confidence, and contradiction resolution, then generates a short prompt-ready context. Ask performs the same retrieval but generates a direct answer and SHOULD cite internal evidence in traces even though public output is prose only. [Documented API surface](../research/docs-api-surface.md)

Integrated thread memory uses the thread's bank id. The decision path records inbound messages, retrieves once, and returns that same context to the caller; the caller may pass it back through system prompt for reply refinement. Separate agents MUST not share a bank unless intentionally configured. [Plugin analysis](../research/plugin-analysis.md)

## Social Learning

Parse attributed transcript, compute durable style/norm features, and produce a prompt block. Features include register, terseness, message length, emoji/slang/punctuation/capitalization, response conventions, directness, greetings/sign-offs, and local interaction rules. Keep style separate from factual memory to avoid stale duplication. Refresh asynchronously over a bounded window and persist versioned cards. [Plugin analysis](../research/plugin-analysis.md)

## Observability

Normalize one conversation and segment contiguous interactions into the six canonical types. For each non-agent person, aggregate stance counts, reception, frustration, trend, evidence, key moments, and confidence. Findings must be evidence-backed and produce a concrete recommendation plus optional rewritten reply/component mapping. Compute deterministic totals/distributions from model-produced segmentation rather than asking the model to count. [Documented API surface](../research/docs-api-surface.md)

Audit first parses raw text into messages/speakers, then waits for explicit agent selection. The launched pipeline runs reception analysis, missing-context retrieval analysis, per-turn risk scoring, and targeted rewrites. Each stage writes partial state so polling remains informative and retries resume idempotently. [Documented API surface](../research/docs-api-surface.md)

## Personas

Generate a blueprint before personas: field DAG/order, distributions, ordered values, dependencies, and constraints. Sample categorical/numeric fields conditionally in topological order; reject/resample constraint violations; render identity/backstory/system prompt/markdown from sampled facts. Validate schema and constraints deterministically, then compute pairwise diversity and marginal fidelity. Enhancement treats seed text as immutable facts and fills the same target schema. [Documented API surface](../research/docs-api-surface.md)

## Model abstraction and safety

All model stages MUST use versioned prompt templates, JSON-schema outputs, timeouts, bounded retries, provider fallbacks, trace ids, and recorded token/cost metrics. Safety policy MUST prevent adaptation to harmful local norms, disclose bot identity where required, avoid manipulative impersonation, and minimize retention of sensitive conversation data. Both papers explicitly raise deception/social-engineering risk or leave long-horizon safety unresolved. [HUMA paper digest](../research/paper-huma.md) [LoSoNA paper digest](../research/paper-losona.md)