---
title: Intelligence and Personas API Reference
description: Normative live-tested schemas for learning, foresee, observability, audits, and personas.
tags: [humalike, specification, api-reference, personas, observability]
status: complete
---
# Intelligence and personas API reference

All routes inherit the [protocol contract](./02-protocol-auth-errors.md). Exact shapes, literals, and ranges below are live-tested; model-authored strings remain semantic outputs. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Shared types

```ts
type TranscriptMessage={
  id:string;speaker:string;text:string;
  user_id?:string;channel?:string;timestamp?:string;reply_to?:string;
};
type Transcript={messages:TranscriptMessage[];source?:string};
type Persona={persona_id:string;fields:Record<string,string>;system_prompt:string;markdown:string};
type NumericDistribution={min:number;max:number;mean:number;sd:number;integer:boolean};
type FieldSpec={
  name:string;label:string;kind:"categorical"|"numeric"|"text"|"derived";
  description:string;formula:string;parents:string[];
  categorical:null|{weights:Record<string,number>};
  numeric:null|NumericDistribution;
  conditionals:{when:Record<string,string>;categorical:null|{weights:Record<string,number>};numeric:null|NumericDistribution}[];
  ordered_values:null|string[];
};
type Blueprint={
  domain:string;language:string;order:string[];fields:FieldSpec[];
  constraints:{name:string;lhs:string;op:string;rhs:string}[];
  style_axes:Record<string,string[]>;name_origins:string[];rationale:string;sources:string[];
};
```

Blueprint weights are relative numbers and need not sum to one. `order` MUST be a subset of the field names that includes every categorical, numeric, and derived field; text fields MAY be omitted from it while still appearing in `fields` and in persona field maps. Inapplicable distributions are explicit `null`, and a sampled field MAY carry `categorical:null` and `numeric:null` at top level with its distribution only inside `conditionals`. `conditionals[].when` keys are a subset of `parents`; a numeric parent's `when` value is a range string such as `"23-35"`. On input (validation), only `persona_id` is required: missing persona members default to `fields:{}`, `system_prompt:""`, `markdown:""`. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Social Learning

### `POST /v1/social-learning/actions/extract`

Request `{transcript:Transcript}`. Missing transcript returns 422 at `loc:["transcript"]` (`missing`); empty messages returns 422 at `["transcript","messages"]` (`too_short`); a message without `id` returns 422 at `["transcript","messages",0,"id"]`. Unknown fields are ignored. Success is exactly `{profile,prompt_block}` where `prompt_block` is non-empty and: [Intelligence evidence](../research/tested-intelligence-personas.md)

```ts
type LearningProfile={
  meta:{source:string;channels:string[];message_count:number};
  register:{formality:string;warmth:string;casing:string;notes:string;confidence:number};
  style:{length:string;formatting:string;emoji:string};
  lexicon:{term:string;meaning:string;usage:string}[];
  banned_phrases:unknown[];
  address:{default:string;deference:unknown[]};
  taboos:{rule:string;scope:string;evidence:string[]}[];
  humor:{style:string;rules:string[]};
  roles:unknown[];
  norms:{rule:string;type:string;evidence:{breach:string;sanction:string}[];confidence:number}[];
  in_jokes:unknown[];
  summary:string;
};
```

`meta.source` MUST echo the request `source` and `meta.message_count` MUST equal the input length. `meta.channels` is model-authored: a transcript with explicit channels on some messages yields those channels plus `"unlabelled"`; a channel-less transcript is not stable (`[]` and `["general"]` observed). Every `confidence` lies in `[0,1]`; `summary` MAY be empty; observed `norms[].type` is `inferred_from_behavior` and `taboos[].scope` is `all`. The engine SHOULD infer style and norms from bounded attributed context and SHOULD keep learned style separate from durable factual memory, matching the reference client’s cadence and storage separation. [Intelligence evidence](../research/tested-intelligence-personas.md) [Plugin analysis](../research/plugin-analysis.md)

## Theory of Mind

### `POST /v1/foresee/actions/foresee`

```ts
type ForeseeRequest={
  transcript:{speaker:string;text:string}[];
  candidate_reply:string;agent_name?:string;system_prompt?:string;subject_name?:string;
};
type ForeseeResponse={
  mental_state:{name:string;beliefs:string[];goals:string[];emotions:{type:string;intensity:number}[]}[];
  predicted_reaction:{name:string;summary:string;predicted_message:string;risk:"low"|"medium"|"high"}[];
  refined_reply:string;refinement_rationale:string;
};
```

`conversation`/`draft` are not aliases; their use returns 422 naming `transcript` and `candidate_reply` as `missing`. Empty transcript returns 422. Unknown fields are ignored. With `subject_name`, both arrays MUST contain exactly one entry whose `name` equals the subject; emotion intensity lies in `[0,1]`. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Social Observability

### `POST /v1/social-observability/actions/analyze`

Request `{agent_name:string,transcript:Transcript,focus?:string}`. Success returns exactly the report below—no `id` key, no `Location`, no `x-report-id`. [Intelligence evidence](../research/tested-intelligence-personas.md)

```ts
type InteractionType="transactional"|"bonding"|"venting"|"banter"|"friction"|"hostile";
type Report={
  health_score:number;summary:string;
  interactions:{
    type:InteractionType;topic:string;
    participants:{name:string;stance:string;user_id?:string|null}[];message_ids:string[];
  }[];
  interaction_totals:{type:InteractionType;count:number}[];
  per_user:{
    name:string;user_id?:string|null;reception:"engaged"|"neutral"|"bored"|"annoyed"|"churn_risk";
    frustration:number;trend:"improving"|"stable"|"declining";
    behaviors:string[];evidence:string[];confidence:number;note?:string;
    interaction_count:number;dominant_type:InteractionType;distribution:{type:InteractionType;count:number}[];
    key_moments:{label:string;type:string;message_ids:string[];agent_critique?:string}[];
  }[];
  findings:{
    issue:string;severity:"low"|"medium"|"high";affected_users:string[];evidence:string[];
    recommendation:string;confidence:number;before_message_id?:string;rewritten_reply?:string;
    suggested_component?:string;how_it_helps?:string;
  }[];
};
```

`interaction_totals` and every `per_user[].distribution` MUST list exactly the six interaction types, zero counts included, with totals consistent with `interactions` and each user's `interaction_count` equal to the number of interactions they participate in. Every message id in `interactions`, `key_moments`, `findings.evidence`, and `before_message_id` MUST originate in the input. Supplied `user_id` values MUST be echoed; audit-generated reports carry `user_id:null`. `health_score`, `frustration`, and every `confidence` lie in `[0,1]`. Observed `suggested_component` values are `social-memory`, `theory-of-mind`, and `norms`. [Intelligence evidence](../research/tested-intelligence-personas.md)

### `GET /v1/social-observability/repositories/Report/by-id/{id}`

A random valid UUID returns 200 JSON `null`; a malformed id returns 400 `{error:{code:"VALIDATION_ERROR",message:"invalid id"}}` with no `details` key (the same body as the three persona repositories). A stored read shape is documented, but the tested public analyze flow provides no identifier to reach its new report. Implement the route, keep it owner-scoped, and preserve this as an explicit unresolved linkage—not an actionable promise. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Full audit

### `POST /v1/social-observability/actions/audit_prepare`

Request `{raw_text:string}`. Success is exactly `{run_id:uuid,messages:number,participants:string[],agent_guess:string|null}` with participants in first-appearance order and `agent_guess`, when non-null, one of the participants. The parser MUST accept `[HH:MM] Name: text` and plain `Name: text` lines, including multi-word speakers; timestamps are parsed and discarded; parsed message ids are `m1`…`mN`. Request validation: missing or empty text is 422 (`missing`/`string_too_short`); more than 300,000 characters is 422 `string_too_long`; exactly 300,000 characters pass the request model. Semantic 400s, with exact bodies in the [protocol contract](./02-protocol-auth-errors.md): unparsable text; more than 250 parsed messages (250 is accepted); and input exceeding a **~32,768-token budget**, which is enforced independently of the message cap. [Intelligence evidence](../research/tested-intelligence-personas.md)

### `POST /v1/social-observability/actions/audit_launch`

Request `{run_id:string,agent_name:string}`. First success is exactly `{run_id,agent_name,status:"queued"}`. A malformed `run_id` is 422 `uuid_parsing`; an unknown run is 400 `unknown run`; a nonparticipant is 400 with `{field:"agent_name",message:"'<name>' never speaks"}`. Launch is first-write-wins: an immediate repeat returns `queued`, a repeat after completion returns `status:"completed"`, and a relaunch naming another participant returns 200, keeps the first agent, and leaves the projection unchanged. [Intelligence evidence](../research/tested-intelligence-personas.md)

### `POST /v1/social-observability/projections/audit-run`

Request `{run_id:string}`. The response has exactly the keys below and MUST NOT expose `status` or `stage`: [Intelligence evidence](../research/tested-intelligence-personas.md)

```ts
type AuditProjection={
  run_id:string;agent_name:string;
  transcript:{source:null;messages:{id:string;speaker:string;text:string;user_id:null;channel:null;timestamp:null;reply_to:null}[]};
  report:Report|null;
  read:null|{
    prompt_block:string|null;
    portrait:{role:string;personality:string;register:string}|null;
    mental_state:{name:string;beliefs:string[];goals:string[];emotions:{type:string;intensity:number}[]}[]|null;
    profiles:{name:string;facts:string[]}[]|null;
  };
  verdicts:null|{index:number;risk:"low"|"medium"|"high";summary:string;predicted_message:string}[];
  replies:{index:number;reply:string;messages:string[];risk:"low"|"medium"|"high"}[];
};
```

Before launch the projection is already readable with `agent_name` equal to `agent_guess`, `report`/`read`/`verdicts` `null`, and `replies:[]`. Sections become non-null monotonically in the order report ≤ read ≤ verdicts ≤ replies. `read.mental_state` and `read.profiles` model the non-agent humans. `verdicts[].index` is the 0-based position in `transcript.messages` of each agent turn; `replies` has one entry per verdict at the same indexes, `messages` is the rewritten reply split into 1–3 bubble strings, and its `risk` is the rewrite's own risk. Clients detect completion when `replies.length === verdicts.length` and the projection is stable across two polls. Malformed `run_id` is 422; unknown run is 400 `unknown run`. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Persona generation

### `POST /v1/personas/actions/generate`

Request `{prompt:string,count:number,grounding:"off"|"web"|"research"}`. Empty prompt is 422 `string_too_short`; `count` below 1 is 422 `greater_than_equal`; an unknown grounding is 422 `literal_error`; unknown fields are ignored. Success is exactly `{id:uuid,status:"pending"}`. [Intelligence evidence](../research/tested-intelligence-personas.md)

### `GET /v1/personas/repositories/Population/by-id/{id}`

```ts
type Diversity={max_pairwise_similarity:number;mean_pairwise_similarity:number;duplicate_pairs:number};
type Marginal={attribute:string;cells:{key:string;requested:number;achieved:number}[];total_variation_distance:number};
type PopulationResult={personas:Persona[];blueprint:Blueprint;diversity:Diversity;marginals:Marginal[]};
type PopulationResource={
  id:string;created_at:string;updated_at:string;status:"pending"|"running"|"succeeded"|"failed";
  progress:null|{phase:"designing"|"generating"|"complete";produced:number;total:number};
  prompt:string;count:number;grounding:"off"|"web"|"research";
  result:PopulationResult|null;error:null|string|object;
};
```

`id` equals the action id; request fields are echoed; `result` and `error` are `null` until terminal; `progress` moves `null` → `designing` → (`generating`) → `complete` with `total === count`. On success `personas.length === count`, ids are `p0001`, `p0002`, …, `fields` is a non-empty flat string map whose keys equal all blueprint field names, `markdown` starts with `# Persona`, and `system_prompt` starts with `You are the person described below. Stay in character, speak in their voice, and never break character or mention being an AI.` and differs from `markdown`. Similarities lie in `[0,1]`; marginal `requested`/`achieved` are fractions summing to 1 and `total_variation_distance = ½·Σ|requested−achieved|`. A missing valid UUID returns 200 `null`. A failed job is documented as `status:"failed"` with a stable `error` category such as `"provider_error"`; no failure was observed live. [Intelligence evidence](../research/tested-intelligence-personas.md) [Documented surface](../research/docs-api-surface.md)

## Persona enhancement

### `POST /v1/personas/actions/enhance`

Request `{persona:string,grounding?:"off"|"web"|"research"}`. Empty persona is 422 `string_too_short`; unknown grounding is 422 `literal_error`. Success is exactly `{id,status:"pending"}`. [Intelligence evidence](../research/tested-intelligence-personas.md)

### `GET /v1/personas/repositories/Enhancement/by-id/{id}`

```ts
type EnhancementResource={
  id:string;created_at:string;updated_at:string;status:"pending"|"running"|"succeeded"|"failed";
  source:string;grounding:"off"|"web"|"research";persona:Persona|null;error:null|string|object;
};
```

`source` and `grounding` echo the request; `persona` and `error` are `null` until terminal. The enhanced persona MUST have `persona_id` of the form `enhanced-<12 hex>`, `fields:{}`, and identical `system_prompt` and `markdown` that begin with `CHARACTER PROFILE` (no `#` headings) and embed the seed verbatim under `USER-PROVIDED AGENT INFORMATION` followed by `Use this as high-priority context for identity, preferences, and behavior:`. Distinctive seed facts MUST survive. Missing UUID returns 200 `null`. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Persona validation

### `POST /v1/personas/actions/validate`

Request `{personas:Persona[],blueprint?:Blueprint}` with at least one persona (`persona_id` alone suffices). Success is exactly `{id,status:"pending"}`; empty or missing personas returns 422. [Intelligence evidence](../research/tested-intelligence-personas.md)

### `GET /v1/personas/repositories/Evaluation/by-id/{id}`

```ts
type Gate={name:string;passed:boolean;score:number|null;detail:string};
type EvaluationResult={
  passed:boolean;gates:Gate[];
  scorecards:{persona_id:string;gates:Gate[];soft_scores:Record<string,number>}[];
  diversity:Diversity|null;marginals:Marginal[];notes:string[];
};
type EvaluationResource={
  id:string;created_at:string;updated_at:string;status:"pending"|"running"|"succeeded"|"failed";
  progress:null|{phase:"evaluating"|"complete"};personas:Persona[];blueprint:Blueprint|null;
  result:EvaluationResult|null;error:null|string|object;
};
```

Submitted personas are echoed with the input defaults above. A submitted blueprint is normalized before echo with defaults `language:""`, `label:""`, `formula:""`, `categorical:null`, `ordered_values:null`, `style_axes:{}`, `name_origins:[]`, `rationale:""`, `sources:[]`; an omitted blueprint echoes `null`. Each scorecard has exactly two gates, `schema` then `constraints`: `schema` detail is `N field(s) valid` or `<field>='<value>' is not numeric`; `constraints` aggregates every applicable named constraint with detail `N applicable constraint(s) passed` on success (including `0 applicable constraint(s) passed` when a schema failure makes a constraint non-applicable) or `<name>: <lhs>=<value> <op> <rhs> (<count>)` on failure. Batch `gates` are `max_pairwise_similarity` (score = `diversity.max_pairwise_similarity`) and one `marginal_tvd:<attribute>` per marginal (score = its TVD, detail prefixed `[advisory: n<50]` for small batches); they are `[]` for a single persona. `soft_scores` is sparse with keys ⊆ `{voice_attribution}` and values in `[0,1]`. `passed` is true exactly when every gate passed; job `status` and `passed` remain independent. Single-persona runs return `diversity:null` and `marginals:[]`; validating a population echoes its `diversity` and `marginals`; validating without a blueprint returns exactly `{passed:true,gates:[],scorecards:[],diversity:null,marginals:[],notes:[]}`. A valid missing UUID returns 200 `null`. [Intelligence evidence](../research/tested-intelligence-personas.md)

Terminal polling for audit and all persona repositories MUST be free. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Installer extension

The Hermes plugin contains privileged device authorization routes, but their gateway credential is outside the tested customer API. They MUST remain out of the recreation target unless separately authorized and tested. [Plugin analysis](../research/plugin-analysis.md)