---
title: Intelligence and Personas API Reference
description: Normative live-tested schemas for learning, foresee, observability, audits, and personas.
tags: [humalike, specification, api-reference, personas, observability]
status: complete
---
# Intelligence and personas API reference

All routes inherit the [protocol contract](./02-protocol-auth-errors.md). Exact shapes below are live-tested; model-authored strings remain semantic outputs. [Intelligence evidence](../research/tested-intelligence-personas.md)

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

Blueprint weights are relative numbers and need not sum to one. `order` may omit text/derived fields that still appear in `fields` and persona field maps. Inapplicable distributions are explicit `null`. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Social Learning

### `POST /v1/social-learning/actions/extract`

Request `{transcript:Transcript}`. Missing transcript or empty messages returns 422 lowercase request validation. Success is exactly `{profile,prompt_block}` where `prompt_block` is non-empty and: [Intelligence evidence](../research/tested-intelligence-personas.md)

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

The engine SHOULD infer style and norms from bounded attributed context and SHOULD keep learned style separate from durable factual memory, matching the reference client’s cadence and storage separation. [Plugin analysis](../research/plugin-analysis.md)

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

`conversation`/`draft` are not aliases. Empty transcript and missing required fields return 422 lowercase request validation. With `subject_name`, the tested response contained one modeled subject and emotion intensity in `[0,1]`. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Social Observability

### `POST /v1/social-observability/actions/analyze`

Request `{agent_name:string,transcript:Transcript,focus?:string}`. Success returns exactly the report below—no id. [Intelligence evidence](../research/tested-intelligence-personas.md)

```ts
type Report={
  health_score:number;summary:string;
  interactions:{
    type:"transactional"|"bonding"|"venting"|"banter"|"friction"|"hostile";
    topic:string;participants:{name:string;stance:string;user_id?:string}[];message_ids:string[];
  }[];
  interaction_totals:{type:string;count:number}[];
  per_user:{
    name:string;user_id?:string;reception:"engaged"|"neutral"|"bored"|"annoyed"|"churn_risk";
    frustration:number;trend:"improving"|"stable"|"declining";
    behaviors:string[];evidence:string[];confidence:number;note?:string;
    interaction_count:number;dominant_type:string;distribution:{type:string;count:number}[];
    key_moments:{label:string;type:string;message_ids:string[];agent_critique?:string}[];
  }[];
  findings:{
    issue:string;severity:"low"|"medium"|"high";affected_users:string[];evidence:string[];
    recommendation:string;confidence:number;before_message_id?:string;rewritten_reply?:string;
    suggested_component?:string;how_it_helps?:string;
  }[];
};
```

Totals/distributions include all six interaction types, including zero counts. Supplied user and message ids are preserved in evidence. The action exposed no `id`, `Location`, or `x-report-id`; its `x-request-id` is not a report id. [Intelligence evidence](../research/tested-intelligence-personas.md)

### `GET /v1/social-observability/repositories/Report/by-id/{id}`

A random valid UUID returns 200 JSON `null`; malformed id returns 400 uppercase `VALIDATION_ERROR` with message `invalid id`. A stored read shape is documented, but the tested public analyze flow provides no identifier to reach its new report. Implement the route, keep it owner-scoped, and preserve this as an explicit unresolved linkage—not an actionable promise. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Full audit

### `POST /v1/social-observability/actions/audit_prepare`

Request `{raw_text:string}`. Success is exactly `{run_id:string,messages:number,participants:string[],agent_guess:string|null}` with participants in first-appearance order. Missing or over-300,000-character text returns 422 lowercase request validation. Unparseable text or more than 250 parsed messages returns 400 uppercase semantic validation. [Intelligence evidence](../research/tested-intelligence-personas.md)

### `POST /v1/social-observability/actions/audit_launch`

Request `{run_id:string,agent_name:string}`. First success is exactly `{run_id,agent_name,status:"queued"}`. A nonparticipant returns 400 uppercase semantic validation with `{field,message}` detail. Repeated launch returns 200, preserves the first agent, and does not restart. [Intelligence evidence](../research/tested-intelligence-personas.md)

### `POST /v1/social-observability/projections/audit-run`

Request `{run_id:string}`. The response uses nullable sections for progress and MUST NOT require `status` or `stage`: [Intelligence evidence](../research/tested-intelligence-personas.md)

```ts
type AuditProjection={
  run_id:string;agent_name:string;
  transcript:{source:null;messages:{id:string;speaker:string;text:string;user_id:null;channel:null;timestamp:null;reply_to:null}[]};
  report:Report|null;
  read:null|{
    prompt_block?:string|null;
    portrait?:{role:string;personality:string;register:string}|null;
    mental_state?:{name:string;beliefs:string[];goals:string[];emotions:{type:string;intensity:number}[]}[]|null;
    profiles?:{name:string;facts:string[]}[]|null;
  };
  verdicts:null|{index:number;risk:string;summary:string;predicted_message:string}[];
  replies:{index:number;reply:string;messages:string[];risk:string}[];
};
```

Observed progress was null sections → report → read → verdicts → replies. Missing run returns 400 uppercase semantic validation. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Persona generation

### `POST /v1/personas/actions/generate`

Request `{prompt:string,count:number,grounding:"off"|"web"|"research"}`. Empty prompt returns 422. Initial success is exactly `{id:string,status:"pending"}`. [Intelligence evidence](../research/tested-intelligence-personas.md)

### `GET /v1/personas/repositories/Population/by-id/{id}`

```ts
type Diversity={max_pairwise_similarity:number;mean_pairwise_similarity:number;duplicate_pairs:number};
type Marginal={attribute:string;cells:{key:string;requested:number;achieved:number}[];total_variation_distance:number};
type PopulationResult={personas:Persona[];blueprint:Blueprint;diversity:Diversity;marginals:Marginal[]};
type PopulationResource={
  id:string;created_at:string;updated_at:string;status:"pending"|"running"|"succeeded"|"failed";
  progress:null|{phase:string;produced:number;total:number};
  prompt:string;count:number;grounding:"off"|"web"|"research";
  result:PopulationResult|null;error:null|string|object;
};
```

Generated persona fields are non-empty flat string maps whose keys equal all blueprint field names. Missing valid UUID returns 200 `null`. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Persona enhancement

### `POST /v1/personas/actions/enhance`

Request `{persona:string,grounding?:"off"|"web"|"research"}`. Empty persona returns 422. Initial success is exactly `{id,status}`. [Intelligence evidence](../research/tested-intelligence-personas.md)

### `GET /v1/personas/repositories/Enhancement/by-id/{id}`

```ts
type EnhancementResource={
  id:string;created_at:string;updated_at:string;status:"pending"|"running"|"succeeded"|"failed";
  source:string;grounding:"off"|"web"|"research";persona:Persona|null;error:null|string|object;
};
```

Success MUST preserve distinctive seed facts. The tested enhanced persona had `fields:{}` and identical large `system_prompt`/`markdown` strings; enhancement MUST NOT invent generated-population fields as a transport requirement. Missing UUID returns 200 `null`. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Persona validation

### `POST /v1/personas/actions/validate`

Request `{personas:Persona[],blueprint?:Blueprint}` with at least one persona. Success is exactly `{id,status:"pending"}`; empty personas returns 422. [Intelligence evidence](../research/tested-intelligence-personas.md)

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
  progress:null|{phase:string};personas:Persona[];blueprint:Blueprint|null;
  result:EvaluationResult|null;error:null|string|object;
};
```

Submitted blueprints are normalized to the full schema before echo. Constraint checks are aggregated into one `constraints` gate per scorecard, not one gate per constraint. Nonnumeric numeric data fails `schema`; a dependent constraint then passes as non-applicable with detail equivalent to `0 applicable constraint(s) passed`; overall `passed` remains false. One-person runs return `diversity:null` and `marginals:[]`. A valid missing UUID returns 200 `null`. [Intelligence evidence](../research/tested-intelligence-personas.md)

Terminal polling for audit and all persona repositories MUST be free. [Intelligence evidence](../research/tested-intelligence-personas.md)

## Installer extension

The Hermes plugin contains privileged device authorization routes, but their gateway credential is outside the tested customer API. They MUST remain out of the recreation target unless separately authorized and tested. [Plugin analysis](../research/plugin-analysis.md)