# Personas

Persona operations are asynchronous. Action responses return a job id and
`status:"pending"`; poll the owner-scoped repository resource until a terminal
status. Terminal polling is free.

## Shared types

```ts
type Persona = {
  persona_id: string;
  fields: Record<string, string>;
  system_prompt: string;
  markdown: string;
};

type NumericDistribution = {
  min: number;
  max: number;
  mean: number;
  sd: number;
  integer: boolean;
};

type FieldSpec = {
  name: string;
  label: string;
  kind: "categorical" | "numeric" | "text" | "derived";
  description: string;
  formula: string;
  parents: string[];
  categorical: null | {weights: Record<string, number>};
  numeric: null | NumericDistribution;
  conditionals: {
    when: Record<string, string>;
    categorical: null | {weights: Record<string, number>};
    numeric: null | NumericDistribution;
  }[];
  ordered_values: null | string[];
};

type Blueprint = {
  domain: string;
  language: string;
  order: string[];
  fields: FieldSpec[];
  constraints: {name: string; lhs: string; op: string; rhs: string}[];
  style_axes: Record<string, string[]>;
  name_origins: string[];
  rationale: string;
  sources: string[];
};

type Diversity = {
  max_pairwise_similarity: number;
  mean_pairwise_similarity: number;
  duplicate_pairs: number;
};

type Marginal = {
  attribute: string;
  cells: {key: string; requested: number; achieved: number}[];
  total_variation_distance: number;
};
```

Blueprint weights are relative and need not sum to one. `order` is a field
name ordering and includes every categorical, numeric, and derived field;
text fields may be omitted. `fields` still contains omitted text fields.
Inapplicable top-level `categorical` and `numeric` values are explicit `null`.
A conditional-only distribution may be `null` at top level and supplied under
`conditionals`. Conditional `when` keys are parent names; numeric parent
values may be range strings such as `"23-35"`.

## `POST /v1/personas/actions/generate`

```ts
type GenerateRequest = {
  prompt: string;
  count: number;
  grounding: "off" | "web" | "research";
};

type GenerateResponse = {id: string; status: "pending"};
```

`prompt` must be non-empty and `count >= 1`. The action returns a UUID and
starts a Population resource:

```sh
curl -sS "$HUMALIKE_API_URL/v1/personas/actions/generate" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Two fictional community librarians","count":2,"grounding":"off"}'
```

## `GET /v1/personas/repositories/Population/by-id/{id}`

```ts
type PopulationResource = {
  id: string;
  created_at: string;
  updated_at: string;
  status: "pending" | "running" | "succeeded" | "failed";
  progress: null | {
    phase: "designing" | "generating" | "complete";
    produced: number;
    total: number;
  };
  prompt: string;
  count: number;
  grounding: "off" | "web" | "research";
  result: {
    personas: Persona[];
    blueprint: Blueprint;
    diversity: Diversity;
    marginals: Marginal[];
  } | null;
  error: null | string | object;
};
```

The action request is echoed. `progress` transitions through `designing`,
`generating`, and `complete`; on success `total === count` and
`personas.length === count`. `result` and `error` are null before terminal.
A failed-job `error` category such as `"provider_error"` is a documented
default, not live-proven.

Generated persona ids are sequential within the result: `p0001`, `p0002`, …
Their `fields` map is flat, non-empty, all-string, and has exactly the
blueprint field names. `markdown` starts with:

```text
# Persona
```

`system_prompt` starts with:

```text
You are the person described below. Stay in character, speak in their voice, and never break character or mention being an AI.
```

It differs from `markdown`.

`max_pairwise_similarity` and `mean_pairwise_similarity` are in `[0,1]`;
`duplicate_pairs` is a non-negative integer. Marginal cells contain fractions:
`requested` and `achieved` sum approximately to 1. The exact TVD formula is:

```text
total_variation_distance =
  0.5 * sum(abs(requested - achieved) for each cell)
```

A valid but absent population UUID returns HTTP 200 with JSON `null`.

```sh
curl -sS "$HUMALIKE_API_URL/v1/personas/repositories/Population/by-id/POPULATION_UUID" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY"
```

## `POST /v1/personas/actions/enhance`

```ts
type EnhanceRequest = {
  persona: string;
  grounding?: "off" | "web" | "research";
};
type EnhanceResponse = {id: string; status: "pending"};
```

```sh
curl -sS "$HUMALIKE_API_URL/v1/personas/actions/enhance" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"persona":"Iris Vale repairs antique clocks.","grounding":"off"}'
```

## `GET /v1/personas/repositories/Enhancement/by-id/{id}`

```ts
type EnhancementResource = {
  id: string;
  created_at: string;
  updated_at: string;
  status: "pending" | "running" | "succeeded" | "failed";
  source: string;
  grounding: "off" | "web" | "research";
  persona: Persona | null;
  error: null | string | object;
};
```

`source` and `grounding` echo the request. A successful enhanced persona has:

| Field | Required value |
| --- | --- |
| `persona_id` | `enhanced-<12hex>` |
| `fields` | `{}` |
| `system_prompt` | Exactly equal to `markdown` |
| `markdown` | Starts with `CHARACTER PROFILE` |

The markdown embeds the seed verbatim under this exact section:

```text
USER-PROVIDED AGENT INFORMATION
Use this as high-priority context for identity, preferences, and behavior:
```

Distinctive seed facts must survive. A valid but absent UUID returns 200 JSON
`null`.

```sh
curl -sS "$HUMALIKE_API_URL/v1/personas/repositories/Enhancement/by-id/ENHANCEMENT_UUID" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY"
```

## `POST /v1/personas/actions/validate`

```ts
type ValidateRequest = {
  personas: Persona[];
  blueprint?: Blueprint;
};
type ValidateResponse = {id: string; status: "pending"};
```

At least one persona is required. On input, only `persona_id` is required;
missing members default to:

```ts
{
  fields: {};
  system_prompt: "";
  markdown: "";
}
```

A supplied blueprint is normalized before it is echoed:

| Missing member | Normalized default |
| --- | --- |
| `language`, field `label`, field `formula` | `""` |
| field `categorical`, field `ordered_values` | `null` |
| `style_axes` | `{}` |
| `name_origins`, `sources` | `[]` |
| `rationale` | `""` |
| field `parents`, field `conditionals` | `[]` |
| field `numeric` | `null` |
| `constraints` | `[]` |

An omitted blueprint echoes as `null`.

```sh
curl -sS "$HUMALIKE_API_URL/v1/personas/actions/validate" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"personas":[{"persona_id":"solo_1"}]}'
```

## `GET /v1/personas/repositories/Evaluation/by-id/{id}`

```ts
type Gate = {
  name: string;
  passed: boolean;
  score: number | null;
  detail: string;
};

type EvaluationResult = {
  passed: boolean;
  gates: Gate[];
  scorecards: {
    persona_id: string;
    gates: Gate[];
    soft_scores: Record<string, number>;
  }[];
  diversity: Diversity | null;
  marginals: Marginal[];
  notes: string[];
};

type EvaluationResource = {
  id: string;
  created_at: string;
  updated_at: string;
  status: "pending" | "running" | "succeeded" | "failed";
  progress: null | {phase: "evaluating" | "complete"};
  personas: Persona[];
  blueprint: Blueprint | null;
  result: EvaluationResult | null;
  error: null | string | object;
};
```

Each scorecard has exactly two gates, in this order:

| Gate | Detail and score |
| --- | --- |
| `schema` | `N field(s) valid`, or `<field>='<value>' is not numeric` |
| `constraints` | `N applicable constraint(s) passed`, or `<name>: <lhs>=<value> <op> <rhs> (<count>)` |

If schema failure makes a constraint non-applicable, the successful aggregate
detail is exactly `0 applicable constraint(s) passed`. `soft_scores` is sparse;
its keys are a subset of `{voice_attribution}` and its values are in `[0,1]`.

For multi-persona validation, batch `gates` contain:

| Gate name | Score |
| --- | --- |
| `max_pairwise_similarity` | `diversity.max_pairwise_similarity` |
| `marginal_tvd:<attribute>` | The marginal's `total_variation_distance` |

The marginal gate detail is prefixed `[advisory: n<50]` for a small batch.
Single-persona results have `diversity:null`, `marginals:[]`, and no batch
gates. Without a blueprint, the exact successful result is:

```json
{"passed":true,"gates":[],"scorecards":[],"diversity":null,"marginals":[],"notes":[]}
```

`result.passed` is the conjunction of every batch and scorecard gate. It is
independent of job `status`: a succeeded evaluation can have
`result.passed:false`. A valid but absent UUID returns 200 JSON `null`.

```sh
curl -sS "$HUMALIKE_API_URL/v1/personas/repositories/Evaluation/by-id/EVALUATION_UUID" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY"
```

Generation, enhancement, and validation actions are billable. Repository
polls, including terminal polls, are free.
