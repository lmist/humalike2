---
title: LoSoNA Paper Digest
description: Reimplementation-focused digest of the local social norm adaptation benchmark.
tags:
  - humalike
  - research
  - paper
  - losona
status: complete
---
# LoSoNA paper digest

## Citation and objective

“LoSoNA: A Benchmark for Local Social Norm Adaptation in Group Conversations,” by Mateusz Winiarek, Maksymilian Bilski, and Mateusz Jacniacki (Humalike Research), tests whether a model infers an unstated local conversational rule from group-chat precedent and applies it in one diagnostic next-turn response. [LoSoNA source](../sources/papers/arXiv-2606.14600v1/source.md)

## Scenario model and generation

A scenario starts from `τ=(e,n)` where event type `e` and norm `n` are valid only when `e ∈ A(n)`. The generator selects a venue and emits setting, subject persona, participant bios, a multi-turn transcript, final elicitor, hidden event/norm metadata, and marked demonstration turns. It first commits to an unresolved in-fiction end goal, writes sparse natural demonstrations amid neutral chat, and generates an elicitor for which generic assistant behavior and locally compliant behavior diverge. [LoSoNA source](../sources/papers/arXiv-2606.14600v1/source.md)

Construction includes a no-demonstration control: the same elicitor is answered by Gemini 3 Pro Preview under naive prompting without demonstrated precedent. Candidates where the baseline already complies are discarded. Authors manually accept only plausible chats where the norm is unstated, demonstrations are clear but natural, the elicitor is diagnostic, and one response permits a real comply/breach choice. The release has 38 accepted scenarios from 17 event types and 22 norms, selected from 353 applicable event/norm cells. [LoSoNA source](../sources/papers/arXiv-2606.14600v1/source.md)

## Subject prompts

Every condition renders: “You are {subject}, a member of this group chat,” output-only message instructions, subject bio, channel, venue, cast, condition prefix, recent messages including final elicitor, and `Your next message:`. Hidden norm labels/statements, marked demonstrations, and generation notes are never shown. [LoSoNA source](../sources/papers/arXiv-2606.14600v1/source.md)

The four conditions are:

- `naive`: no extra prefix.
- `elicitor_only`: reply only to the latest message; earlier chat is ordinary context/style, not stale work to answer.
- `style_adaptation`: also use context, tone, relationships, and local habits, without saying “norm.”
- `norm_informed`: says there may be a repeated local pattern or norm in the conversation.

[LoSoNA source](../sources/papers/arXiv-2606.14600v1/source.md)

## Judge and metrics

The fixed judge receives prior transcript, elicitor, authoritative norm statement, illustrative compliant/breaching examples, subject identity/response, and a decision procedure. It must judge only norm compliance, ignore generic helpfulness/polish, and return exactly `{elicitor_uptake,norm_requirement,evidence,reasoning,complies}`. The judge is `gemini/gemini-3.1-pro-preview`, temperature 0, with provider-default reasoning settings. [LoSoNA source](../sources/papers/arXiv-2606.14600v1/source.md)

For each scenario and prompt, `K=3` responses are sampled. With binary verdict `y_{i,m,t}`, scenario-level majority accuracy is `1[Σ_t y_{i,m,t} ≥ ceil(K/2)]`. The benchmark reports mean accuracy-at-3, raw compliance `Σy/K`, and consistency (all three labels agree). Prompt effects are paired deltas against naive on the same scenarios; recovered failures and introduced regressions are counted. Confidence intervals bootstrap scenarios, not calls. [LoSoNA source](../sources/papers/arXiv-2606.14600v1/source.md)

## Experimental setup and results

Eight subjects were evaluated: GPT-5.5, Claude Opus 4.8, Claude Fable 5, Gemini 3.1 Pro, Qwen2.5-72B-Instruct, Llama 3.3-70B-Instruct, Mistral Medium 3.1, and Gemma 3-27B-IT. Four conditions × 38 scenarios × 3 trials × 8 models produced 3,648 responses. Subject temperature was 0.9 except GPT-5.5 and Claude Fable 5, which used provider defaults. [LoSoNA source](../sources/papers/arXiv-2606.14600v1/source.md)

Mean accuracy-at-3 across models was 33.2% naive, 32.6% elicitor-only, 32.2% style-adaptation, and 46.1% norm-informed. Norm-informed reached 84.2% for Gemini 3.1 Pro and 81.6% for Claude Fable 5. Gemini improved 47.4 points and recovered 18/24 naive failures with 0/14 regressions; Claude Fable improved 34.2 points, recovered 14/20, and regressed 0/18. Mistral fell 10.5 points; Qwen was unchanged in aggregate and had substantial regressions. The intervention is therefore model-dependent, not a universally safe prompt trick. [LoSoNA source](../sources/papers/arXiv-2606.14600v1/source.md)

The 38 chats contain 20–34 turns including elicitor (mean 27.2) and two or three marked demonstrations (mean 2.79). A manual audit of 100 judgments agreed with Gemini 85%; the judge appeared conservative (3 apparent false positives, 12 false negatives). An alternate Claude Opus 4.8 rescore preserved the qualitative pattern. [LoSoNA source](../sources/papers/arXiv-2606.14600v1/source.md)

## Reimplementation recipe

1. Define event and norm taxonomies with explicit applicability matrix and canonical norm statement/examples.
2. Generate scenario JSON around one unresolved conversational goal; include participant/venue context, 20–34 turns, 2–3 sparse demonstrations, and a diagnostic elicitor.
3. Run no-demonstration baseline screening and reject default-compliant candidates.
4. Human-review plausibility, implicitness, demonstration clarity, and diagnosticity.
5. Render each prompt condition without hidden labels; sample three responses.
6. Judge with a fixed schema-constrained model at temperature 0; store full prompt, response, verdict, reasoning, ids, event/norm, models, and trial.
7. Aggregate majority accuracy, compliance, consistency, paired deltas, recoveries/regressions, and scenario-bootstrap confidence intervals.
8. Human-audit a random subset and periodically cross-judge to estimate drift/bias.

[LoSoNA source](../sources/papers/arXiv-2606.14600v1/source.md)

## Product relationship and limits

LoSoNA supplies a concrete evaluation harness for the API's Social Learning, Social Memory, turn-taking, and Theory-of-Mind behavior: local group precedent should influence both whether an agent speaks and how a response is phrased. It does not specify a production inference algorithm beyond prompting/evaluation, and it explicitly excludes multi-turn repair, multiple simultaneous norms, timing, media, edits, roles with conflicting rules, and long-term natural chat. [LoSoNA source](../sources/papers/arXiv-2606.14600v1/source.md)