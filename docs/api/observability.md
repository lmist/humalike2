# Social Observability

Observability has two surfaces: synchronous interaction analysis and a
prepare/launch/poll audit workflow.

## `POST /v1/social-observability/actions/analyze`

```ts
type AnalyzeRequest = {
  agent_name: string;
  transcript: {
    messages: {
      id: string;
      speaker: string;
      text: string;
      user_id?: string;
      channel?: string;
      timestamp?: string;
      reply_to?: string;
    }[];
    source?: string;
  };
  focus?: string;
};

type InteractionType =
  | "transactional"
  | "bonding"
  | "venting"
  | "banter"
  | "friction"
  | "hostile";

type Report = {
  health_score: number;
  summary: string;
  interactions: {
    type: InteractionType;
    topic: string;
    participants: {
      name: string;
      stance: string;
      user_id?: string | null;
    }[];
    message_ids: string[];
  }[];
  interaction_totals: {type: InteractionType; count: number}[];
  per_user: {
    name: string;
    user_id?: string | null;
    reception: "engaged" | "neutral" | "bored" | "annoyed" | "churn_risk";
    frustration: number;
    trend: "improving" | "stable" | "declining";
    behaviors: string[];
    evidence: string[];
    confidence: number;
    note?: string;
    interaction_count: number;
    dominant_type: InteractionType;
    distribution: {type: InteractionType; count: number}[];
    key_moments: {
      label: string;
      type: string;
      message_ids: string[];
      agent_critique?: string;
    }[];
  }[];
  findings: {
    issue: string;
    severity: "low" | "medium" | "high";
    affected_users: string[];
    evidence: string[];
    recommendation: string;
    confidence: number;
    before_message_id?: string;
    rewritten_reply?: string;
    suggested_component?: string;
    how_it_helps?: string;
  }[];
};
```

`health_score`, `frustration`, and `confidence` are in `[0,1]`. Every message
id in interactions, key moments, findings evidence, and
`before_message_id` comes from the input. Supplied `user_id` values are
echoed in matching report entries. Reports made from audit transcripts use
`user_id:null`.

`interaction_totals` lists all six interaction types, including zero counts.
Its counts sum to `interactions.length` and match the actual interaction type
counts. Every `per_user[].distribution` also lists all six types, sums to
`interaction_count`, and `interaction_count` equals the number of
interactions in which that user participates.

The response is exactly a `Report`. It has no `id` field, and the service does
not emit `Location` or `x-report-id`. This is intentional and unresolved in
the production contract; do not infer a report identifier from
`x-request-id`.

```sh
curl -sS "$HUMALIKE_API_URL/v1/social-observability/actions/analyze" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name":"support_bot",
    "transcript":{"messages":[
      {"id":"a1","speaker":"Casey","user_id":"usr_casey","text":"The export broke."},
      {"id":"a2","speaker":"support_bot","text":"Try clearing your cache."},
      {"id":"a3","speaker":"Casey","user_id":"usr_casey","text":"I already did."}
    ]},
    "focus":"Are repetitive replies increasing frustration?"
  }'
```

## `GET /v1/social-observability/repositories/Report/by-id/{id}`

A valid but absent UUID returns HTTP 200 with JSON `null`. A malformed id
returns HTTP 400 exactly:

```json
{"error":{"code":"VALIDATION_ERROR","message":"invalid id"}}
```

There is no `details` key in that response. The route is owner-scoped. Because
`analyze` returns no report id or location, the tested public flow cannot use
this route to read back the report it just created.

```sh
curl -sS "$HUMALIKE_API_URL/v1/social-observability/repositories/Report/by-id/REPORT_UUID" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY"
```

## `POST /v1/social-observability/actions/audit_prepare`

```ts
type AuditPrepareRequest = {raw_text: string};
type AuditPrepareResponse = {
  run_id: string;
  messages: number;
  participants: string[];
  agent_guess: string | null;
};
```

The parser accepts both formats:

```text
[HH:MM] Name: text
Name: text
```

Speaker names may contain spaces. Timestamps are parsed and discarded.
Participants are returned in first-appearance order, parsed message ids are
`m1` through `mN`, and `agent_guess` is either `null` or one of the
participants.

| Input condition | Result |
| --- | --- |
| Missing `raw_text` | 422, `loc:["raw_text"]`, `type:"missing"` |
| Empty `raw_text` | 422, `loc:["raw_text"]`, `type:"string_too_short"` |
| More than 300,000 characters | 422, `type:"string_too_long"` |
| Exactly 300,000 characters | Accepted by the request model, then semantic checks apply |
| More than 250 parsed messages | 400 with the exact cap literal below |
| Input over the approximately 32,768-token budget | 400 with the exact token literal below |

The exact 400 bodies are:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "no messages could be read from this text",
    "details": [{"field": "raw_text", "message": "no messages detected"}]
  }
}
```

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "This transcript has <n> messages; the audit accepts at most 250.",
    "details": [{"field": "raw_text", "message": "over the 250-message cap"}]
  }
}
```

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "This paste is too large to read: about <n> tokens, and the audit accepts about 32,768. Send at most 250 messages.",
    "details": [{"field": "raw_text", "message": "at most ~32768 tokens allowed"}]
  }
}
```

Replace `<n>` with the service's count. The message cap and token budget are
independent.

```sh
curl -sS "$HUMALIKE_API_URL/v1/social-observability/actions/audit_prepare" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"raw_text":"[10:01] Casey: the export broke\n[10:02] support_bot: Try again"}'
```

## `POST /v1/social-observability/actions/audit_launch`

```ts
type AuditLaunchRequest = {run_id: string; agent_name: string};
type AuditLaunchResponse = {
  run_id: string;
  agent_name: string;
  status: string;
};
```

The first successful launch is exactly:

```json
{"run_id":"RUN_UUID","agent_name":"support_bot","status":"queued"}
```

Launch is first-write-wins. An immediate repeat remains `queued`; a repeat
after completion returns `status:"completed"`. A relaunch naming another
participant returns 200, retains the first `agent_name`, and does not restart
the run. A malformed `run_id` is 422 `uuid_parsing`; an unknown run is the
400 `unknown run` response; a nonparticipant is:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "agent_name must be one of the transcript's speakers",
    "details": [{"field": "agent_name", "message": "'<name>' never speaks"}]
  }
}
```

```sh
curl -sS "$HUMALIKE_API_URL/v1/social-observability/actions/audit_launch" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"run_id":"RUN_UUID","agent_name":"support_bot"}'
```

## `POST /v1/social-observability/projections/audit-run`

```ts
type AuditProjection = {
  run_id: string;
  agent_name: string;
  transcript: {
    source: null;
    messages: {
      id: string;
      speaker: string;
      text: string;
      user_id: null;
      channel: null;
      timestamp: null;
      reply_to: null;
    }[];
  };
  report: Report | null;
  read: null | {
    prompt_block: string | null;
    portrait: {role: string; personality: string; register: string} | null;
    mental_state: {
      name: string;
      beliefs: string[];
      goals: string[];
      emotions: {type: string; intensity: number}[];
    }[] | null;
    profiles: {name: string; facts: string[]}[] | null;
  };
  verdicts: {
    index: number;
    risk: "low" | "medium" | "high";
    summary: string;
    predicted_message: string;
  }[] | null;
  replies: {
    index: number;
    reply: string;
    messages: string[];
    risk: "low" | "medium" | "high";
  }[];
};
```

Before launch, `report`, `read`, and `verdicts` are `null` and `replies` is
`[]`. Sections become non-null monotonically in this order:

```text
report -> read -> verdicts -> replies
```

The projection never exposes `status` or `stage`. Verdict indexes are
zero-based positions of the audit agent's turns in `transcript.messages`.
There is one reply per verdict at the same index. `replies[].messages` splits
the rewritten reply into 1–3 bubble strings.

Poll until `replies.length === verdicts.length` and that projection is
unchanged across two consecutive polls. Terminal polling is free.

```sh
curl -sS "$HUMALIKE_API_URL/v1/social-observability/projections/audit-run" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"run_id":"RUN_UUID"}'
```
