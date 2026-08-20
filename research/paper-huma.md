---
title: HUMA Paper Digest
description: Reimplementation-focused digest of the Humanlike Multi-user Agent architecture and evaluation.
tags:
  - humalike
  - research
  - paper
  - huma
status: complete
---
# HUMA paper digest

## Citation and problem

“Humanlike Multi-user Agent (HUMA): Designing a Deceptively Human AI Facilitator for Group Chats,” by Mateusz Jacniacki and Marti Carmona Serrat (Soofte Research), targets asynchronous multi-party chat rather than one-to-one turn-taking. It frames three core decisions: when to speak or stay silent, whom/how to address, and how to adapt when overlapping messages interrupt ongoing work. [HUMA source](../sources/papers/arXiv-2511.17315v1/source.md)

## Architecture

HUMA receives initial history and participants, then processes join, message, reaction-add/remove, reply, and typing events. Each event drives three stages: Router, Action Agent, and Reflection. New events may interrupt the workflow; queued intentions and scratchpad survive so the next routing pass can resume or abandon them. [HUMA source](../sources/papers/arXiv-2511.17315v1/source.md)

The Router chooses among 20 predefined conversational strategies, including Keep Silent, Go Deeper, Ask Question, Bridge Perspectives, Recall Message, Refocus to Goal, Directly Mentioned, Continue Pending Action, and Tell a Story. For each strategy `s`, an LLM gives contextual appropriateness `A_s ∈ [0,1]`. Timeliness penalizes repetition: if the strategy was last used `k` steps ago and `N` is the strategy count, `T_s = min(1, k/N)`. Selection maximizes `A_s + T_s`. Keep Silent, Directly Mentioned, Continue Pending, and Tell a Story remain at `T_s = 1`. [HUMA source](../sources/papers/arXiv-2511.17315v1/source.md)

The Action Agent executes the selected strategy with `send_message`, `send_reply`, and `add_reaction`. Calls may run in parallel, but multiple parallel message sends are forbidden; multi-message narration must happen sequentially. The scratchpad persists through interruption. Timing is applied inside send tools using a human typing-rate model; the paper cites roughly 50–100 WPM as human scale but does not publish a fitted delay distribution. Incoming events during generation queue until generation completes; then routing restarts with prior intended calls visible. [HUMA source](../sources/papers/arXiv-2511.17315v1/source.md)

After an uninterrupted action, Reflection emits one sentence that summarizes context/recent behavior, suggests adjacent topics, and maintains a coherent arc for later iterations. [HUMA source](../sources/papers/arXiv-2511.17315v1/source.md)

## Reimplementation algorithm

1. Hydrate a conversation actor with history, participants, recent-strategy ring buffer of length `N`, persistent scratchpad, pending tool calls, and last reflection.
2. Append each platform event to an ordered event log and increment an epoch.
3. Render full context plus reflection/pending state and score every strategy for appropriateness.
4. Compute timeliness from the recency ring, apply exemptions, and choose `argmax_s(A_s + T_s)`.
5. If Keep Silent, record the strategy and stop. Otherwise invoke the Action Agent under the chosen strategy and strict tool constraints.
6. Before/during simulated typing, watch for a newer epoch. Queue interruptions; after generation, abort stale sends and rerun routing with pending intentions.
7. Deliver message/reply/reaction tools with timing and typing indicators. Only one message-send pipeline may own delivery at a time.
8. On uninterrupted completion, generate and persist one reflection sentence; update strategy recency.

This algorithm maps most directly to the API's thread, turn epoch, speak/silence decision, typing events, paced messages, and stale-response suppression. [HUMA source](../sources/papers/arXiv-2511.17315v1/source.md)

## Evaluation

The study used 97 Prolific participants aged 18–40 in four-person role-play chats: 41 in human-community-manager condition and 56 in AI condition. Live chat was approximately 10 minutes inside a 30-minute session. Roles were Community Manager, Interested, Regular, and Critic; participants created backstory, completed a 100+ character writing exercise, reflected on goals/emotions, and chose nicknames. [HUMA source](../sources/papers/arXiv-2511.17315v1/source.md)

Participants labeled the AI manager as AI 55.4% of the time (thus human 44.6%) and labeled the human manager as human 46.7%; confidence intervals overlapped chance. Mean five-point scale results were human versus AI: effectiveness 4.48 vs 4.14 (`d=-0.37`), social presence 4.89 vs 4.71 (`d=-0.21`), engagement/satisfaction 4.58 vs 4.32 (`d=-0.30`), and human-likeness/competence 4.13 vs 4.14 (`d=0.01`). All reported absolute effects were below 0.4. [HUMA source](../sources/papers/arXiv-2511.17315v1/source.md)

## Missing implementation detail

The paper does not identify the Router/Action/Reflection model, exact prompts, all 20 strategy definitions, appropriateness output schema, token budgets, persistence backend, concurrency primitives, message-splitting policy, timing distribution, retry policy, or deployment throughput. These are true implementation unknowns, not details to infer. Product parity therefore requires fixture-driven behavior and configurable policies rather than pretending the paper specifies a unique engine. [HUMA source](../sources/papers/arXiv-2511.17315v1/source.md)

## Product relationship

The public turn-taking API operationalizes the paper's key mechanisms: `submit_messages` is Router-like speak/silence selection, `turn_epoch` is interruption control, `respond` is refinement plus Action-Agent delivery, WebSocket typing/message frames expose timing, `record_event` feeds non-message signals, and the optional memory integration extends the state available to routing/refinement. [HUMA source](../sources/papers/arXiv-2511.17315v1/source.md)