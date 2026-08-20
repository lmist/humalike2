# Errors and billing

## Error envelopes

Errors are JSON and use route-specific semantics. The outer response contains
only `error`.

Request-model validation uses HTTP 422:

```ts
type RequestValidationError = {
  error: {
    code: "validation_failed";
    message: "request validation failed";
    details: {loc: (string | number)[]; msg: string; type: string}[];
  };
};
```

`details[].loc` is rooted at the request field. It never starts with
`"body"`. Observed `type` values include `uuid_parsing`, `too_short`,
`too_long`, `string_too_long`, `string_too_short`, `literal_error`, `missing`,
and `greater_than_equal`.

Semantic validation uses HTTP 400:

```ts
type SemanticValidationError = {
  error: {
    code: "VALIDATION_ERROR";
    message: string;
    details?: {field: string; message: string}[];
  };
};
```

### Exact route-specific 400 responses

| Condition | Exact response body |
| --- | --- |
| Malformed id on `Report`, `Population`, `Enhancement`, or `Evaluation` `by-id` | `{"error":{"code":"VALIDATION_ERROR","message":"invalid id"}}` |
| Unknown audit `run_id` on launch or projection | `{"error":{"code":"VALIDATION_ERROR","message":"unknown run","details":[{"field":"run_id","message":"no such run"}]}}` |
| Audit text has no readable messages | `{"error":{"code":"VALIDATION_ERROR","message":"no messages could be read from this text","details":[{"field":"raw_text","message":"no messages detected"}]}}` |
| Audit parses more than 250 messages | `{"error":{"code":"VALIDATION_ERROR","message":"This transcript has <n> messages; the audit accepts at most 250.","details":[{"field":"raw_text","message":"over the 250-message cap"}]}}` |
| Audit exceeds the token budget | `{"error":{"code":"VALIDATION_ERROR","message":"This paste is too large to read: about <n> tokens, and the audit accepts about 32,768. Send at most 250 messages.","details":[{"field":"raw_text","message":"at most ~32768 tokens allowed"}]}}` |
| Audit launch names a nonparticipant | `{"error":{"code":"VALIDATION_ERROR","message":"agent_name must be one of the transcript's speakers","details":[{"field":"agent_name","message":"'<name>' never speaks"}]}}` |

Replace only the angle-bracket values in parameterized literals. A malformed
UUID is request validation (422, `uuid_parsing`), not the 400 `invalid id`
case. A valid but absent repository UUID returns HTTP 200 with JSON `null`.

The following are **documented defaults, not live-proven** because the
reference suites did not exercise the corresponding conditions:

| Status | Documented default |
| --- | --- |
| 402 | `{"error":{"code":"PAYMENT_REQUIRED","message":"insufficient credits"}}` |
| 403 | Error envelope with `error.code:"forbidden"`; the exact message is route-specific and not pinned |
| 502 | Error envelope with `error.code:"UPSTREAM_ERROR"`; the exact message is not pinned |

The exact 403 and 502 bodies beyond those codes are not established by the
normative spec, so this documentation does not invent message literals.
Branch on `error.code`, not message text. Exact 429 quotas, headers, and body
are unresolved.

## Component billing

Usage is reported using these component slugs:

| Slug | Capability |
| --- | --- |
| `personas` | Population generation, enhancement, and evaluation |
| `social-learning` | Learning profile extraction |
| `social-memory` | Recall and grounded ask |
| `social-observability` | Analyze and audit model work |
| `theoryofmind` | Pre-send forecasting/refinement |
| `turn-taking` | Modeled turn decisions and reply work |

Prices in the recreation are configuration values, not stable public pricing.
Insufficient-credit checks happen before billable model work. Superseded
responses, short-circuited submissions, and terminal polling do not capture
credits.

### Free paths

The following paths are free in tested accounting:

- `POST /v1/turn-taking/actions/whoami`;
- `POST /v1/credits/projections/usage-summary`;
- `POST /v1/turn-taking/actions/open_thread`;
- `POST /v1/turn-taking/actions/record_event`;
- `POST /v1/social-memory/actions/ingest`;
- `submit_messages` with `skip_decide:true` or a message with `has_media:true`;
- stale `respond` calls that return `{scheduled:[],superseded:true}`; and
- terminal `GET` polls for Population, Enhancement, and Evaluation resources,
  plus audit projection polls.

### Billable paths

Model-backed work is billable when it runs: modeled `submit_messages`,
non-stale `respond`, Social Memory `recall` and `ask`, Social Learning
`extract`, Theory of Mind `foresee`, Social Observability `analyze` and audit
work, and Personas `generate`, `enhance`, and `validate`.

The same route can therefore be free or billable depending on whether it
short-circuits or performs model work. A 402 stops the reference suites'
billable blocks; it is an environment/budget condition, not evidence that a
route's contract changed.

## Usage summary

`POST /v1/credits/projections/usage-summary` returns:

```ts
type UsageSummary = {
  total_calls: number;
  total_credits: number;
  per_component: {
    component:
      | "personas"
      | "social-learning"
      | "social-memory"
      | "social-observability"
      | "theoryofmind"
      | "turn-taking";
    calls: number;
    credits: number;
  }[];
  daily_series: {
    date: "Mon" | "Tue" | "Wed" | "Thu" | "Fri" | "Sat" | "Sun";
    requests: number;
  }[];
};
```

Counts are non-negative integers. `daily_series` has exactly seven entries,
oldest first, for the last seven UTC days; zero-request days are included.
`per_component` may contain rows with zero values, but every component name
uses one of the six slugs above.
