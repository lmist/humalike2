---
title: Core Engine Design
description: Reimplementation pipelines for routing, memory, intelligence, observability, and personas.
tags: [humalike, specification, engine, algorithms]
status: complete
---
# Core engine design

This document specifies one sufficient internal design. Internal models and prompts may differ, but every externally visible result MUST satisfy the [live conformance contract](./08-parity-and-open-questions.md).

## Turn router and interruption

Implement a configurable HUMA-style strategy router. HUMA scores strategy appropriateness `A_s`, adds recency timeliness `T_s=min(1,k/N)`, exempts Keep Silent, Directly Mentioned, Continue Pending, and Tell a Story from decay, and selects the maximum. The paper does not publish its exact model, prompts, or complete strategy catalog, so those are implementation choices rather than production claims. [HUMA digest](../research/paper-huma.md)

Each accepted batch MUST append its messages and increment the thread epoch once in one serialized transaction. `skip_decide` and media MUST return `speak` without modeled decision work. The modeled path MUST be capable of both `speak` and `stay_silent`; the captured silent shape has empty tags/context. Respond MUST compare the supplied epoch immediately before billing and scheduling so newer input suppresses stale work. [Realtime evidence](../research/tested-realtime-memory.md)

Persist router input references, prompt/model version, strategy scores, decision, epoch, and latency for debugging. This trace is internal and MUST NOT alter public response fields. [HUMA digest](../research/paper-huma.md)

## Refinement, splitting, and pacing

A Theory-of-Mind stage consumes transcript, recalled context, learned social profile, system prompt, agent identity, and draft. It produces modeled mental state/reaction and a refined reply; a naturalizer may materially rewrite and split into 1–5 bubbles. Exact prose is not preserved, but required facts and intent SHOULD remain grounded. [Intelligence evidence](../research/tested-intelligence-personas.md) [Realtime evidence](../research/tested-realtime-memory.md)

For each bubble, compute `typing_ms=min(max_typing_ms, max(500, word_count/typing_wpm*60000))` with a whitespace word count; the 500 ms floor is mandatory. Add reading delay only before the first bubble and exactly 200 ms plus the next bubble’s typing time between later deliveries. Stamp each scheduled entry's `created_at` at scheduling time and set `status:"scheduled"`. Persist all schedules before publication. Emit typing true, ordered messages, then typing false. Each delivery creates a distinct WSS message UUID and copies request metadata into every bubble. [Realtime evidence](../research/tested-realtime-memory.md)

Default pacing is proven: when `pacing` or any member is omitted, resolve to `reading_delay_ms=0`, `typing_wpm=150`, and `max_typing_ms=8000`. The Hermes client overrides to 115 WPM. A draft that naturalizes to more than five bubbles MUST be merged down to at most five with all content preserved, never truncated. The split heuristic itself is model-driven and not a conformance claim. [Plugin analysis](../research/plugin-analysis.md) [Realtime evidence](../research/tested-realtime-memory.md)

## Social Memory

Store raw messages in owner/scope order. Idempotency storage MUST retain the first response and body association for each `(owner,key)`; later identical or changed bodies, on the same or any other scope, return the first result and perform no append. [Realtime evidence](../research/tested-realtime-memory.md)

Extract subject-centric facts with evidence links and contradiction metadata. Recall combines entity/speaker-aware lexical and vector retrieval, confidence, recency, and contradiction resolution, then renders concise context. Ask uses the same evidence retrieval but renders a direct answer. The public text MUST preserve tested subject attribution and transcript ordering while allowing paraphrase. [Realtime evidence](../research/tested-realtime-memory.md)

## Social Learning and norm adaptation

Normalize attributed messages and derive the exact profile fields specified by the API, then render `prompt_block`. Keep learned register, style, norms, and local vocabulary separate from durable facts. A client-compatible implementation SHOULD refresh over a bounded recent window and inject the current prompt block into later turns. [Intelligence evidence](../research/tested-intelligence-personas.md) [Plugin analysis](../research/plugin-analysis.md)

LoSoNA shows that explicit norm prompting improves some models and regresses others. Treat inferred local norms as confidence-weighted evidence, not unconditional commands. Maintain naive and norm-informed evaluations with three samples, paired recovery/regression, consistency, and scenario-level confidence intervals. [LoSoNA digest](../research/paper-losona.md)

## Observability and audit

Analyze one normalized conversation. A model may identify interactions, reception, risks, and findings, but code MUST deterministically populate all-six-type totals/distributions consistent with the interaction list, compute each user's `interaction_count`, clamp scores and confidences to `[0,1]`, echo supplied `user_id` values (`null` for audit-derived reports), and validate that every referenced message id originates in the input. The action returns the complete report without adding an id. [Intelligence evidence](../research/tested-intelligence-personas.md)

Audit preparation parses raw speaker-labelled text (`[HH:MM] Name: text` or `Name: text`, multi-word speakers allowed, timestamps discarded), assigns ids `m1`…`mN`, enforces the 250-message cap and the ~32,768-token budget, guesses the agent from the participants, and persists the parked run with `replies:[]`. Launch performs a first-write-wins transition with one selected participant. Workers MUST execute report, context/read, verdict, and rewrite stages in that order, persisting each section as it completes so the projection exposes monotonic nullable-section progress and retries can resume; verdicts and replies index agent turns by 0-based transcript position, and each rewrite is split into 1–3 bubbles. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Personas

Generation MUST design the full blueprint first, including explicit nulls, field labels/formulas, categorical or numeric distributions (possibly conditional-only), conditionals keyed on parents, style axes, name origins, rationale, and sources, exposing `designing` then `generating` progress. Sample fields in `order`; then derive text fields and render each flat string map, a `# Persona` markdown document, and a system prompt opening with the fixed stay-in-character preamble, numbering personas `p0001`…. Compute diversity (pairwise similarity in `[0,1]`) and marginals (requested/achieved fractions, TVD = ½·Σ|Δ|) deterministically from the completed batch. [Intelligence evidence](../research/tested-intelligence-personas.md)

Enhancement treats input text as immutable seed evidence, renders one `CHARACTER PROFILE` text used for both `system_prompt` and `markdown` with the seed quoted verbatim under `USER-PROVIDED AGENT INFORMATION`, assigns `enhanced-<12 hex>` ids, and returns `fields:{}`. Validation fills persona and blueprint defaults, runs a `schema` gate, aggregates all applicable named constraints into one `constraints` gate per persona (non-applicable when schema failed), then computes the batch gates `max_pairwise_similarity` and `marginal_tvd:<attribute>` (none for a single persona), sparse soft scores, diversity, marginals, and notes; `passed` is the conjunction of all gates. Job success and quality `passed` MUST remain independent. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Model operations and safety

Model stages SHOULD use versioned prompts, schema-constrained output, bounded retries, timeouts, provider failover, cost traces, and evidence references. Implementations MUST prevent learned harmful local behavior from overriding safety policy, minimize retained sensitive chat content, and support internal deletion/retention controls even where no public delete route exists. The papers identify social-engineering and long-horizon safety concerns but do not prescribe a unique production policy. [HUMA digest](../research/paper-huma.md) [LoSoNA digest](../research/paper-losona.md)