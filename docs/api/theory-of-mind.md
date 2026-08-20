# Theory of Mind

Theory of Mind evaluates a candidate reply against a conversation, predicts
the modeled subject's reaction, and returns a refined reply.

## `POST /v1/foresee/actions/foresee`

```ts
type ForeseeTurn = {speaker: string; text: string};

type ForeseeRequest = {
  transcript: ForeseeTurn[];
  candidate_reply: string;
  agent_name?: string;
  system_prompt?: string;
  subject_name?: string;
};

type MentalState = {
  name: string;
  beliefs: string[];
  goals: string[];
  emotions: {type: string; intensity: number}[];
};

type PredictedReaction = {
  name: string;
  summary: string;
  predicted_message: string;
  risk: "low" | "medium" | "high";
};

type ForeseeResponse = {
  mental_state: MentalState[];
  predicted_reaction: PredictedReaction[];
  refined_reply: string;
  refinement_rationale: string;
};
```

`transcript` is non-empty. The request field names are literal:
`conversation` is not an alias for `transcript`, and `draft` is not an alias
for `candidate_reply`; using those names produces missing-field validation for
the required fields. Unknown fields are ignored.

When `subject_name` is supplied, `mental_state` and `predicted_reaction`
contain exactly one entry, and both entries use that name. Emotion intensities
are numbers in `[0,1]`. Risk uses only `low`, `medium`, or `high`.

```sh
curl -sS "$HUMALIKE_API_URL/v1/foresee/actions/foresee" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "transcript":[
      {"speaker":"customer","text":"The export failed twice."},
      {"speaker":"agent","text":"Try clearing your cache."},
      {"speaker":"customer","text":"I already did."}
    ],
    "candidate_reply":"Okay, reach out if you need anything else.",
    "agent_name":"agent",
    "subject_name":"customer"
  }'
```

The operation is billable. `respond` already performs a refinement pass for
turn-taking replies; call `foresee` directly when an application needs the
standalone prediction/refinement surface.
