---
title: Live-Tested Intelligence and Personas API
description: Production behavior proven by runnable live tests for intelligence, observability, audits, and personas.
tags:
  - humalike
  - research
  - live-api
  - intelligence
  - personas
status: complete
---
# Live-tested intelligence and personas API

All observations below come from production calls to `https://api.humalike.com` made by the self-contained live suite. The suite reads `HUMALIKE_API_KEY` and an optional `HUMALIKE_API_URL` origin from the environment, stores no recorded responses, pins every learnable literal in a `PINNED` table, checks generated text by type and invariant rather than wording, and exits with code 3 when a 402 truncates billable checks. [Live intelligence suite](../tests/intelligence/run.mjs)

## Test method and credit accounting

The runner takes usage snapshots before and after the complete run and around a terminal-job re-poll burst. It reports total and `per_component` deltas because a concurrent suite can change unrelated components. A full run makes about 119 HTTP calls and completes roughly 1,350 assertions (the exact count moves by a few with poll counts and persona field counts) in 8–12 minutes; the latest confirming run is recorded in the [conformance strategy](../spec/08-parity-and-open-questions.md). [Live intelligence suite](../tests/intelligence/run.mjs)

Every sampled success and error response carried a non-empty `x-request-id` and a `content-type` beginning `application/json`. No sampled response carried `x-ratelimit-*`, `ratelimit-*`, or `retry-after`; this proves only header absence in the sample, not the absence of server-side throttling. The usage component slugs are exactly `personas`, `social-learning`, `social-memory`, `social-observability`, `theoryofmind`, and `turn-taking`; `daily_series` carries seven `Mon`–`Sun` entries. [Live intelligence suite](../tests/intelligence/run.mjs)

## Cross-cutting error behavior

Without a bearer, extract, foresee, analyze, audit_prepare, generate, and a GET repository route all return HTTP 401 `{"error":{"code":"UNAUTHORIZED","message":"missing or invalid credentials"}}`. [Live intelligence suite](../tests/intelligence/run.mjs)

Request-model validation consistently uses HTTP 422 with an envelope of exactly `{code:"validation_failed",message:"request validation failed",details}`; each detail is exactly `{loc,msg,type}`, `loc` never starts with `body`, and `details.length` equals the number of failing fields. Observed `type`/`msg` pairs per location: `transcript`→`missing`/`Field required`; `transcript.messages`→`too_short`/`List should have at least 1 item after validation, not 0`; `transcript.messages.0.id`→`missing`; `candidate_reply`→`missing`; `raw_text`→`missing`, `string_too_short`/`String should have at least 1 character`, or `string_too_long`/`String should have at most 300000 characters`; `prompt` and `persona`→`string_too_short`; `count`→`greater_than_equal`/`Input should be greater than or equal to 1`; `grounding`→`literal_error`/`Input should be 'off', 'web' or 'research'` on both generate and enhance; `personas`→`too_short` or `missing`; `run_id`→`uuid_parsing` on both launch and projection. Unknown request fields are ignored on extract, foresee, and generate—no `extra_forbidden` detail appears, only the genuine error. [Live intelligence suite](../tests/intelligence/run.mjs)

Semantic and repository validation uses HTTP 400 and uppercase `VALIDATION_ERROR` with route-specific bodies, pinned exactly:

| Case | Body |
| --- | --- |
| Malformed id on Report, Population, Enhancement, or Evaluation `by-id` | `{error:{code:"VALIDATION_ERROR",message:"invalid id"}}` with no `details` key |
| Unknown `run_id` on launch or projection | `message:"unknown run"`, `details:[{field:"run_id",message:"no such run"}]` |
| Launch with a nonparticipant | `message:"agent_name must be one of the transcript's speakers"`, `details:[{field:"agent_name",message:"'<name>' never speaks"}]` |
| Unparsable `raw_text` | `message:"no messages could be read from this text"`, `details:[{field:"raw_text",message:"no messages detected"}]` |
| 251 parsed messages | `message:"This transcript has 251 messages; the audit accepts at most 250."`, `details:[{field:"raw_text",message:"over the 250-message cap"}]` |
| 300,000 characters of `x` | `message:"This paste is too large to read: about 120,300 tokens, and the audit accepts about 32,768. Send at most 250 messages."`, `details:[{field:"raw_text",message:"at most ~32768 tokens allowed"}]` |

The last row shows a **~32,768-token budget** enforced after request validation, independent of the 250-message cap. 300,000 characters pass the request model (300,001 do not), and exactly 250 parsed messages are accepted (`messages:250`, about 12 s). [Live intelligence suite](../tests/intelligence/run.mjs)

## Social Learning

`POST /v1/social-learning/actions/extract` accepts `{transcript:{messages:[{id,speaker,text,user_id?,channel?,timestamp?,reply_to?}],source?}}`. A successful response has exactly `{profile,prompt_block}` with a non-empty `prompt_block` for both a one-message and a six-message transcript; the two prompt blocks differ. The profile has exactly:

```ts
{
  meta:{source:string,channels:string[],message_count:number};
  register:{formality:string,warmth:string,casing:string,notes:string,confidence:number};
  style:{length:string,formatting:string,emoji:string};
  lexicon:{term:string,meaning:string,usage:string}[];
  banned_phrases:unknown[];
  address:{default:string,deference:unknown[]};
  taboos:{rule:string,scope:string,evidence:string[]}[];
  humor:{style:string,rules:string[]};
  roles:unknown[];
  norms:{rule:string,type:string,evidence:{breach:string,sanction:string}[],confidence:number}[];
  in_jokes:unknown[];
  summary:string;
}
```

`meta.source` echoes the request `source` and `meta.message_count` equals the input length. `meta.channels` is model-authored: the rich transcript (channel `lounge` on two messages) produced `["lounge","unlabelled"]` in every run, while a channel-less transcript produced `[]` once and `["general"]` once. `summary` may be the empty string. Observed `norms[].type` was `inferred_from_behavior` and `taboos[].scope` was `all`; every confidence lay in `[0,1]`. [Live intelligence suite](../tests/intelligence/run.mjs)

## Theory of Mind

`POST /v1/foresee/actions/foresee` accepts `{transcript:{speaker,text}[],candidate_reply,agent_name?,system_prompt?,subject_name?}`. The wrong names `conversation` and `draft` return 422 naming missing `transcript` and `candidate_reply`; an empty transcript is also 422. The success shape is exactly:

```ts
{
  mental_state:{name:string;beliefs:string[];goals:string[];emotions:{type:string,intensity:number}[]}[];
  predicted_reaction:{name:string;summary:string;predicted_message:string;risk:"low"|"medium"|"high"}[];
  refined_reply:string;
  refinement_rationale:string;
}
```

With `subject_name:"customer"`, both arrays contain exactly one entry whose `name` equals the subject; emotion intensity lies in `[0,1]`. [Live intelligence suite](../tests/intelligence/run.mjs)

## Social Observability

`POST /v1/social-observability/actions/analyze` accepts `{agent_name,transcript,focus?}` and returns exactly `{interactions,interaction_totals,per_user,findings,health_score,summary}`—no `id`, no `Location`, no `x-report-id`. Looking up the response's `x-request-id` as a report UUID returns HTTP 200 `null`. The persisted report therefore cannot be retrieved from a fresh analyze response through the public contract. [Live intelligence suite](../tests/intelligence/run.mjs)

The report schema is:

```ts
{
  health_score:number; summary:string;
  interactions:{type:"transactional"|"bonding"|"venting"|"banter"|"friction"|"hostile";topic:string;participants:{name:string,stance:string,user_id?:string|null}[];message_ids:string[]}[];
  interaction_totals:{type:string,count:number}[];
  per_user:{name:string;user_id?:string|null;reception:"engaged"|"neutral"|"bored"|"annoyed"|"churn_risk";frustration:number;trend:"improving"|"stable"|"declining";behaviors:string[];evidence:string[];confidence:number;note?:string;key_moments:{label:string,type:string,message_ids:string[],agent_critique?:string}[];interaction_count:number;dominant_type:string;distribution:{type:string,count:number}[]}[];
  findings:{issue:string;severity:"low"|"medium"|"high";affected_users:string[];evidence:string[];recommendation:string;before_message_id?:string;rewritten_reply?:string;suggested_component?:string;how_it_helps?:string;confidence:number}[];
}
```

`interaction_totals` and every `distribution` list exactly the six canonical types with counts consistent with `interactions` (zero counts included); `interaction_count` is the number of interactions the user participates in. Every referenced message id originates in the input. Supplied `user_id` values are echoed by analyze; audit-generated reports carry `user_id:null`. `health_score`, `frustration`, and every `confidence` lie in `[0,1]`. Observed `suggested_component` values were `social-memory`, `theory-of-mind`, and `norms`. [Live intelligence suite](../tests/intelligence/run.mjs)

`GET /v1/social-observability/repositories/Report/by-id/{random UUID}` returns HTTP 200 `null`; a malformed id returns the 400 `invalid id` body above. [Live intelligence suite](../tests/intelligence/run.mjs)

## Audit pipeline

`audit_prepare` accepts `{raw_text:string}` and returns exactly `{run_id:uuid,messages:integer,participants:string[],agent_guess:string|null}` with participants in first-appearance order. The parser accepts `[HH:MM] Name: text` lines and plain `Name: text` lines, including multi-word speakers such as `Support Bot`; timestamps are parsed and discarded. `agent_guess` was a participant (`support_bot`, `Support Bot`). [Live intelligence suite](../tests/intelligence/run.mjs)

Before launch, `POST /v1/social-observability/projections/audit-run` already returns exactly `{run_id,agent_name:<agent_guess>,transcript:{messages,source:null},read:null,verdicts:null,report:null,replies:[]}`—`replies` starts as `[]`, the other sections as `null`. Parsed messages are `{id:"m1".."mN",speaker,text,user_id:null,channel:null,timestamp:null,reply_to:null}`. [Live intelligence suite](../tests/intelligence/run.mjs)

`audit_launch` accepts `{run_id,agent_name}`. First launch returns exactly `{run_id,agent_name,status:"queued"}`; an immediate repeat returns `queued`, a repeat after completion returns `status:"completed"`, and a relaunch naming another participant returns 200, keeps the first agent, and leaves the projection deep-equal (no restart). [Live intelligence suite](../tests/intelligence/run.mjs)

The projection never exposes `status` or `stage`. Sections become non-null monotonically in the order report ≤ read ≤ verdicts ≤ replies by first-seen poll (report and read often land in the same poll). The terminal rule that held is `replies.length === verdicts.length` and unchanged across two consecutive polls, reached in 20–23 s (7–8 polls at 3 s). `read` has keys `prompt_block`, `portrait:{role,personality,register}`, `mental_state` (modeling the non-agent humans), and `profiles:{name,facts[]}[]` (all non-agent humans). `verdicts` is `{index,risk,summary,predicted_message}[]` where `index` is the **0-based position in `transcript.messages`** of each agent turn (e.g. `[1,3,5]`) and `risk` is `low|medium|high`; `replies` is `{index,reply,messages:string[],risk}[]` with one entry per verdict at the same indexes, `messages` being the rewritten reply split into 1–3 bubble strings, and `risk` the rewrite's own risk rather than a mirror of the verdict. [Live intelligence suite](../tests/intelligence/run.mjs)

## Persona generation

`POST /v1/personas/actions/generate` accepts `{prompt,count,grounding}` and returns exactly `{id:uuid,status:"pending"}`. Every `Population` poll has exactly `{id,created_at,updated_at,status,progress,prompt,count,grounding,result,error}` with `id` equal to the action id, ISO timestamps, request fields echoed, and `result`/`error` both `null` until terminal. `progress` moves `null` → `{phase:"designing",produced:0,total:count}` → sometimes `generating` → `{phase:"complete",produced:count,total:count}`. A random repository UUID returns HTTP 200 `null`. [Live intelligence suite](../tests/intelligence/run.mjs)

The success result is exactly `{personas,blueprint,diversity,marginals}` with `personas.length === count`. Each persona is exactly `{persona_id,fields,system_prompt,markdown}`: ids are `p0001`, `p0002`, …; `fields` is a non-empty flat string map whose keys equal the blueprint field names; `markdown` starts with `# Persona\n`; `system_prompt` starts with `You are the person described below. Stay in character, speak in their voice, and never break character or mention being an AI.` and differs from `markdown`. [Live intelligence suite](../tests/intelligence/run.mjs)

The blueprint shape is:

```ts
type NumericDistribution={min:number,max:number,mean:number,sd:number,integer:boolean};
type FieldSpec={
  name:string; label:string; kind:"categorical"|"numeric"|"text"|"derived";
  description:string; formula:string; parents:string[];
  categorical:null|{weights:Record<string,number>};
  numeric:null|NumericDistribution;
  conditionals:{when:Record<string,string>;categorical:null|{weights:Record<string,number>};numeric:null|NumericDistribution}[];
  ordered_values:null|string[];
};
type Blueprint={
  domain:string; language:string; order:string[]; fields:FieldSpec[];
  constraints:{name:string,lhs:string,op:string,rhs:string}[];
  style_axes:Record<string,string[]>; name_origins:string[]; rationale:string; sources:string[];
};
```

Labels are populated; derived fields carry a `formula` such as `career_fraction * (age - 22)`; `conditionals[].when` keys are a subset of `parents`, and a numeric parent's `when` value is a range string such as `"23-35"`. A sampled field may have both top-level `categorical` and `numeric` set to `null` with its distribution defined only inside `conditionals`. `order` is a subset of the field names that always includes every categorical, numeric, and derived field and sometimes omits text fields. `categorical.weights` are relative numbers. `diversity` is exactly `{max_pairwise_similarity,mean_pairwise_similarity,duplicate_pairs}` with similarities in `[0,1]`; each marginal is exactly `{attribute,cells:{key,requested,achieved}[],total_variation_distance}` where `requested` and `achieved` are **fractions summing to 1** and `total_variation_distance = ½·Σ|requested−achieved|`. [Live intelligence suite](../tests/intelligence/run.mjs)

## Persona enhancement

`POST /v1/personas/actions/enhance` accepts `{persona:string,grounding?}` and returns exactly `{id,status:"pending"}`. Every `Enhancement` poll has exactly `{id,created_at,updated_at,status,source,grounding,persona,error}`; `source`/`grounding` echo the request, `persona` and `error` are `null` until terminal, and polls show `running` (occasionally `pending`) before `succeeded`. Repository absence is HTTP 200 `null`. [Live intelligence suite](../tests/intelligence/run.mjs)

The enhanced persona has `persona_id` of the form `enhanced-<12 hex>`, `fields:{}`, and identical `system_prompt` and `markdown` strings (about 8 kB) that start with `CHARACTER PROFILE\n` (no `#` headings) and embed the seed verbatim under the section `USER-PROVIDED AGENT INFORMATION\nUse this as high-priority context for identity, preferences, and behavior:`. Distinctive seed facts and a per-run UUID marker were all retained. [Live intelligence suite](../tests/intelligence/run.mjs)

## Persona validation

`POST /v1/personas/actions/validate` accepts `{personas,blueprint?}` and returns exactly `{id,status:"pending"}`; empty `personas` returns 422. The persona request model requires only `persona_id`: `{persona_id:"p"}` is accepted and echoed as `{persona_id:"p",fields:{},system_prompt:"",markdown:""}`. Every `Evaluation` poll has exactly `{id,created_at,updated_at,status,progress,personas,blueprint,result,error}`. A submitted partial blueprint is normalized before echo with defaults `language:""`, `label:""`, `formula:""`, `categorical:null`, `ordered_values:null`, `style_axes:{}`, `name_origins:[]`, `rationale:""`, `sources:[]` (asserted deep-equal); omitting the blueprint echoes `blueprint:null`. `progress.phase` is `evaluating` then `complete` for two personas, or `complete` alone. [Live intelligence suite](../tests/intelligence/run.mjs)

The success result is exactly `{passed,gates,scorecards,diversity,marginals,notes}`. Each scorecard has exactly two gates, `schema` and `constraints`, with details such as `13 field(s) valid`, `N applicable constraint(s) passed`, `hours='unknown' is not numeric`, `age_nonnegative: age=-3 >= 0 (0)`, and `0 applicable constraint(s) passed`. Batch `gates` are `max_pairwise_similarity` (score = `diversity.max_pairwise_similarity`, detail like `max pairwise 0.667 (cap 0.850); 0 near-duplicate pair(s)`) plus one `marginal_tvd:<attribute>` per marginal (score = the TVD, detail like `(max 0.504 at n=2)` with an `[advisory: n<50]` prefix); batch gates are `[]` for a single persona. `soft_scores` is sparse with keys ⊆ `{voice_attribution}` and values in `[0,1]`. `passed` is true exactly when every gate passed; a generated population validates with `passed:true`, a negative numeric plus a nonnumeric numeric field yields `succeeded` with `passed:false`, and a nonnumeric numeric field alone fails `schema` while `constraints` passes as non-applicable. Validating a population echoes the population's `diversity` and `marginals`; single-persona runs return `diversity:null` and `marginals:[]`; validating without a blueprint returns exactly `{passed:true,gates:[],scorecards:[],diversity:null,marginals:[],notes:[]}`. [Live intelligence suite](../tests/intelligence/run.mjs)

## Timings and billing

Observed durations: extract 3.4 s (one 15.6 s outlier), foresee 2.0 s, analyze 3.4 s, audit_prepare 1.5 s (11–16 s at 250 messages), launch/generate/enhance/validate actions 0.2–0.3 s, population 52–59 s, enhancement 37 s, evaluations 3.5–3.7 s (one 0.4 s), audit 20–23 s. [Live intelligence suite](../tests/intelligence/run.mjs)

A full run costs about 800–880 credits: across the two latest runs `personas` was +7 calls/578–639 credits, `social-observability` +13–15/153–166, `social-learning` +2/28–31, and `theoryofmind` +8–10/32–40 (the last mixed with sibling `respond` refinements when run concurrently). The confirming sequential run passed 1,278 assertions with 0 failures and 0 skips over 114 calls. A bracketed burst that re-polled all eight completed audit/persona resources changed usage by exactly zero calls and zero credits. No 402 occurred. [Live intelligence suite](../tests/intelligence/run.mjs)

## Remaining unknowns

Read-back of the exact report created by `analyze` remains unreachable because the action exposes no identifier, `Location`, or list mechanism. No persona job or audit ever reached `status:"failed"`, so the non-null `error` payload is known only from documentation. `meta.channels` for channel-less transcripts is model-authored and not stable. [Live intelligence suite](../tests/intelligence/run.mjs)