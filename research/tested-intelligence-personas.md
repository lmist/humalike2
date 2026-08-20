---
title: Live-Tested Intelligence and Personas API
description: Production behavior proven by runnable live tests for intelligence, observability, audits, and personas.
tags:
  - humalike
  - research
  - live-api
  - intelligence
  - personas
status: provisional
---
# Live-tested intelligence and personas API

All observations below come from production calls to `https://api.humalike.com` made by the self-contained live suite. The suite loads `HUMALIKE_API_KEY` from the environment, stores no recorded responses, and checks generated text by type and invariant rather than wording. [Live intelligence suite](../tests/intelligence/run.mjs)

## Test method and credit accounting

The runner takes usage snapshots before and after the complete run and around a terminal-job re-poll burst. It reports total and `per_component` deltas because a concurrent suite can change unrelated components. The final passing-run delta is recorded after verification below. [Live intelligence suite](../tests/intelligence/run.mjs)

Every sampled success and error response carried a non-empty `x-request-id`. No sampled response carried `x-ratelimit-*`, `ratelimit-*`, or `retry-after`; this proves only header absence in the sample, not the absence of server-side throttling. [Live intelligence suite](../tests/intelligence/run.mjs)

## Social Learning

`POST /v1/social-learning/actions/extract` accepts `{transcript:{messages:[{id:string,speaker:string,text:string,channel?:string,timestamp?:string,reply_to?:string}],source?:string}}`. Missing `transcript` and an empty `messages` array both return HTTP 422 with `{error:{code:"validation_failed",message:"request validation failed",details:[{loc:string[],msg:string,type:string}]}}`. [Live intelligence suite](../tests/intelligence/run.mjs)

A successful response has exactly `{profile,prompt_block}`. `prompt_block` is a non-empty string. The observed `profile` has exactly:

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

The richer six-message transcript produced populated `lexicon`, `taboos`, and `norms`; a one-message transcript also succeeded, and its `prompt_block` differed. The observed `meta.channels` included the explicit channel plus `"unlabelled"` for messages without one. [Live intelligence suite](../tests/intelligence/run.mjs)

## Theory of Mind

`POST /v1/foresee/actions/foresee` accepts `{transcript:{speaker:string,text:string}[],candidate_reply:string,agent_name?:string,system_prompt?:string,subject_name?:string}`. Sending the plausible but wrong names `conversation` and `draft` returns HTTP 422 with lowercase `validation_failed`; the details identify missing `transcript` and `candidate_reply`. An empty transcript is also 422. [Live intelligence suite](../tests/intelligence/run.mjs)

The successful response has exactly:

```ts
{
  mental_state:{
    name:string;
    beliefs:string[];
    goals:string[];
    emotions:{type:string,intensity:number}[];
  }[];
  predicted_reaction:{
    name:string;
    summary:string;
    predicted_message:string;
    risk:"low"|"medium"|"high";
  }[];
  refined_reply:string;
  refinement_rationale:string;
}
```

With `subject_name:"customer"`, both arrays contained exactly one entry for that subject; emotion intensity was within `[0,1]`. [Live intelligence suite](../tests/intelligence/run.mjs)

## Social Observability

`POST /v1/social-observability/actions/analyze` accepts the documented `{agent_name,transcript,focus?}` body and returned exactly `{interactions,interaction_totals,per_user,findings,health_score,summary}`. It did **not** return `id`, a `Location` header, or `x-report-id`. Looking up the response's `x-request-id` as a report UUID returned HTTP 200 `null`, so the persisted report cannot be retrieved from a fresh analyze response through the public contract. This contradicts the current specification's actionable persistence claim; retrieval of the newly created report is genuinely untestable until the action exposes its repository id or a list route exists. [Live intelligence suite](../tests/intelligence/run.mjs)

The observed report schema is:

```ts
{
  health_score:number;
  summary:string;
  interactions:{
    type:"transactional"|"bonding"|"venting"|"banter"|"friction"|"hostile";
    topic:string;
    participants:{name:string,stance:string,user_id?:string}[];
    message_ids:string[];
  }[];
  interaction_totals:{type:string,count:number}[];
  per_user:{
    name:string; user_id?:string;
    reception:"engaged"|"neutral"|"bored"|"annoyed"|"churn_risk";
    frustration:number;
    trend:"improving"|"stable"|"declining";
    behaviors:string[]; evidence:string[]; confidence:number; note?:string;
    key_moments:{label:string,type:string,message_ids:string[],agent_critique?:string}[];
    interaction_count:number; dominant_type:string;
    distribution:{type:string,count:number}[];
  }[];
  findings:{
    issue:string; severity:"low"|"medium"|"high";
    affected_users:string[]; evidence:string[]; recommendation:string;
    before_message_id?:string; rewritten_reply?:string;
    suggested_component?:string; how_it_helps?:string;
    confidence:number;
  }[];
}
```

`interaction_totals` and each `distribution` contained all six canonical types, including zero counts. Supplied `user_id` values were echoed. Evidence referred to supplied message ids. [Live intelligence suite](../tests/intelligence/run.mjs)

`GET /v1/social-observability/repositories/Report/by-id/{random UUID}` returns HTTP 200 with JSON `null`. A malformed id returns HTTP 400 with `{error:{code:"VALIDATION_ERROR",message:"invalid id"}}`, contradicting the documented 422/Pydantic-style behavior for this path. [Live intelligence suite](../tests/intelligence/run.mjs)

## Audit pipeline

`audit_prepare` accepts `{raw_text:string}`. Its success body is exactly `{run_id:string,messages:integer,participants:string[],agent_guess:string|null}`; participant order matched first appearance. Missing and 300,001-character `raw_text` values return HTTP 422 lowercase `validation_failed`. Unparseable text returns HTTP 400 uppercase `VALIDATION_ERROR`. A 251-message transcript returns HTTP 400 uppercase `VALIDATION_ERROR`, and its message names both 251 received and the 250-message maximum. [Live intelligence suite](../tests/intelligence/run.mjs)

`audit_launch` accepts `{run_id,agent_name}`. A nonparticipant returns HTTP 400 `{error:{code:"VALIDATION_ERROR",message:string,details:[{field:"agent_name",message:string}]}}`. First launch returns exactly `{run_id,agent_name,status:"queued"}`. Repeating launch with a different valid participant returns 200, preserves the first agent, and reports current status rather than changing the review target. [Live intelligence suite](../tests/intelligence/run.mjs)

`POST /v1/social-observability/projections/audit-run` returns exactly `{run_id,agent_name,transcript,read,verdicts,report,replies}`; no `status` or `stage` field appeared. Progress is represented by sections becoming non-null. The observed sequence was: all three main sections null; `report` appears; `read` appears; `verdicts` appears; then `replies` fills. [Live intelligence suite](../tests/intelligence/run.mjs)

The parsed transcript is `{messages,source:null}`. Every parsed message has `{speaker,text,id,user_id:null,channel:null,timestamp:null,reply_to:null}`. `report` has the analyze schema above. `read` has independently populated fields:

```ts
{
  prompt_block?:string|null;
  portrait?:{role:string,personality:string,register:string}|null;
  mental_state?:{
    name:string; beliefs:string[]; goals:string[];
    emotions:{type:string,intensity:number}[];
  }[]|null;
  profiles?:{name:string,facts:string[]}[]|null;
}
```

`verdicts` is `{index:integer,risk:string,summary:string,predicted_message:string}[]`. `replies` is `{index:integer,reply:string,messages:string[],risk:string}[]`. The run with three agent turns returned three verdicts and three low-risk rewrites. A random run UUID returns HTTP 400 uppercase `VALIDATION_ERROR`. [Live intelligence suite](../tests/intelligence/run.mjs)

## Persona generation

`POST /v1/personas/actions/generate` accepts exactly the documented `{prompt,count,grounding}` controls. The suite uses `count:2` and `grounding:"off"`, the minimum population that exposes diversity and marginals. The action response is exactly `{id,status}`. Empty `prompt` returns HTTP 422 lowercase `validation_failed`. [Live intelligence suite](../tests/intelligence/run.mjs)

Every repository poll, including pending/running/succeeded, has exactly:

```ts
{
  id:string; created_at:string; updated_at:string;
  status:"pending"|"running"|"succeeded"|"failed";
  progress:null|{phase:string,produced:integer,total:integer};
  prompt:string; count:integer; grounding:"off"|"web"|"research";
  result:null|PopulationResult; error:null|string|object;
}
```

Observed progress moved from `null` to `{phase:"designing",produced:0,total:2}` and then `{phase:"complete",produced:2,total:2}`. A random repository UUID returns HTTP 200 `null`. [Live intelligence suite](../tests/intelligence/run.mjs)

The success result is exactly `{personas,blueprint,diversity,marginals}`. Each persona is exactly `{persona_id,fields,system_prompt,markdown}`; `fields` is a non-empty flat string map whose keys equal the declared field names. [Live intelligence suite](../tests/intelligence/run.mjs)

The observed blueprint is richer than the current spec:

```ts
type NumericDistribution={min:number,max:number,mean:number,sd:number,integer:boolean};
type FieldSpec={
  name:string; label:string;
  kind:"categorical"|"numeric"|"text"|"derived";
  description:string; formula:string; parents:string[];
  categorical:null|{weights:Record<string,number>};
  numeric:null|NumericDistribution;
  conditionals:{
    when:Record<string,string>;
    categorical:null|{weights:Record<string,number>};
    numeric:null|NumericDistribution;
  }[];
  ordered_values:null|string[];
};
type Blueprint={
  domain:string; language:string; order:string[]; fields:FieldSpec[];
  constraints:{name:string,lhs:string,op:string,rhs:string}[];
  style_axes:Record<string,string[]>;
  name_origins:string[];
  rationale:string;
  sources:string[];
};
```

Important differences are `language`, `label`, `formula`, `style_axes`, `name_origins`, explicit nulls for inapplicable distributions, and the fourth field kind `derived`. `categorical.weights` are relative numeric weights and need not sum to 1; the observed blueprint used percentages summing to 100. `blueprint.order` lists sampled causal fields and can omit text and derived fields even though `blueprint.fields` and persona `fields` include them. [Live intelligence suite](../tests/intelligence/run.mjs)

`diversity` is exactly `{max_pairwise_similarity:number,mean_pairwise_similarity:number,duplicate_pairs:integer}`. Each marginal is exactly `{attribute:string,cells:{key:string,requested:number,achieved:number}[],total_variation_distance:number}`. [Live intelligence suite](../tests/intelligence/run.mjs)

## Persona enhancement

`POST /v1/personas/actions/enhance` accepts `{persona:string,grounding?:"off"|"web"|"research"}` and returns exactly `{id,status}`. Empty persona returns HTTP 422 lowercase `validation_failed`. Repository absence is HTTP 200 `null`. [Live intelligence suite](../tests/intelligence/run.mjs)

Every enhancement repository resource has exactly `{id,created_at,updated_at,status,source,grounding,persona,error}`. `source` and `grounding` echo the request; pending/running use `persona:null,error:null`, and success uses a persona with exactly `{persona_id,fields,system_prompt,markdown}` plus `error:null`. Distinctive source facts and a per-run UUID marker were all retained in the rendered prompt/markdown. [Live intelligence suite](../tests/intelligence/run.mjs)

Contrary to the docs and current spec, the observed successful enhanced persona had `fields:{}` rather than inferred flat fields. Its large `system_prompt` and `markdown` were identical strings and embedded the source under a user-provided information section. [Live intelligence suite](../tests/intelligence/run.mjs)

## Persona validation

`POST /v1/personas/actions/validate` accepts `{personas,blueprint?}` and returns exactly `{id,status}`. Empty personas returns HTTP 422 lowercase `validation_failed`. Repository absence is HTTP 200 `null`. [Live intelligence suite](../tests/intelligence/run.mjs)

Every evaluation repository resource has exactly:

```ts
{
  id:string; created_at:string; updated_at:string;
  status:"pending"|"running"|"succeeded"|"failed";
  progress:null|{phase:string};
  personas:Persona[]; blueprint:Blueprint|null;
  result:EvaluationResult|null; error:null|string|object;
}
```

The service normalizes submitted blueprints into the full blueprint and FieldSpec shape described above before echoing them. Observed lifecycle was pending then succeeded with `{phase:"complete"}`. [Live intelligence suite](../tests/intelligence/run.mjs)

The exact success result is:

```ts
type Gate={name:string,passed:boolean,score:number|null,detail:string};
type EvaluationResult={
  passed:boolean;
  gates:Gate[];
  scorecards:{
    persona_id:string;
    gates:Gate[];
    soft_scores:Record<string,number>;
  }[];
  diversity:null|{
    max_pairwise_similarity:number;
    mean_pairwise_similarity:number;
    duplicate_pairs:integer;
  };
  marginals:{
    attribute:string;
    cells:{key:string,requested:number,achieved:number}[];
    total_variation_distance:number;
  }[];
  notes:string[];
};
```

A generated population completed with `status:"succeeded"` and `result.passed:true`. A deliberate negative numeric value plus a nonnumeric numeric field completed with `status:"succeeded"` and `result.passed:false`. Contrary to the current spec, constraints are not emitted one gate per named constraint: each scorecard has one `schema` gate and one aggregate `constraints` gate. The failing aggregate detail names the violated constraint. [Live intelligence suite](../tests/intelligence/run.mjs)

A separate non-applicable probe supplied `hours:"unknown"` against a numeric field and `hours >= 0`. The schema gate failed, while the aggregate constraints gate passed with detail `"0 applicable constraint(s) passed"`; the overall result remained false because schema failed. This is the exact representation of non-applicability. Single-person evaluations returned `diversity:null` and `marginals:[]`. [Live intelligence suite](../tests/intelligence/run.mjs)

## Cross-cutting error behavior

Error casing is endpoint-path dependent. Request-model validation consistently used HTTP 422 and lowercase `validation_failed`. Semantic/repository validation used HTTP 400 and uppercase `VALIDATION_ERROR`. Field details are also inconsistent: request-model errors use `{loc,msg,type}`, while audit semantic errors use `{field,message}` and some repository errors omit `details` entirely. [Live intelligence suite](../tests/intelligence/run.mjs)

## Timings and remaining unknowns

The final live run made 83 HTTP calls and completed with 592 passing assertions, zero failures, one explicit skip, and no 402 response. Observed terminal timings were: audit 19.765 seconds, population generation 52.451 seconds, enhancement 36.743 seconds, generated-population validation 3.612 seconds, failing validation 3.525 seconds, and non-applicable validation 3.590 seconds. [Live intelligence suite](../tests/intelligence/run.mjs)

The run-window usage delta was 29 billed component calls and 759 credits, but a sibling suite was active. The unshared assigned buckets were Personas +5 calls/+576 credits, Social Learning +2/+35, and Social Observability +10/+109. The Theory of Mind bucket was +8/+32 and contains this suite's direct foresee/audit work mixed with sibling `respond` refinements, so it cannot be partitioned exactly; Social Memory +1/+1 and turn-taking +3/+6 were sibling activity outside this suite. A bracketed burst that re-polled all six completed audit/persona resources changed usage by exactly zero calls and zero credits, proving terminal polling is free for these resources. [Live intelligence suite](../tests/intelligence/run.mjs)

The only unresolved behavior is read-back of the exact report created by `analyze`: the action exposes no identifier, `Location`, or list mechanism. Random and request-id probes establish repository absence semantics but cannot bridge that missing identifier. [Live intelligence suite](../tests/intelligence/run.mjs)
