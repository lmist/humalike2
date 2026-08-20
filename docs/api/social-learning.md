# Social Learning

Social Learning extracts communication style from an attributed transcript.
It produces a durable profile record and a ready-to-inject prompt block;
learned style is separate from Social Memory's durable facts.

## `POST /v1/social-learning/actions/extract`

```ts
type TranscriptMessage = {
  id: string;
  speaker: string;
  text: string;
  user_id?: string;
  channel?: string;
  timestamp?: string;
  reply_to?: string;
};

type Transcript = {
  messages: TranscriptMessage[];
  source?: string;
};

type ExtractRequest = {transcript: Transcript};

type LearningProfile = {
  meta: {
    source: string;
    channels: string[];
    message_count: number;
  };
  register: {
    formality: string;
    warmth: string;
    casing: string;
    notes: string;
    confidence: number;
  };
  style: {
    length: string;
    formatting: string;
    emoji: string;
  };
  lexicon: {term: string; meaning: string; usage: string}[];
  banned_phrases: unknown[];
  address: {default: string; deference: unknown[]};
  taboos: {rule: string; scope: string; evidence: string[]}[];
  humor: {style: string; rules: string[]};
  roles: unknown[];
  norms: {
    rule: string;
    type: string;
    evidence: {breach: string; sanction: string}[];
    confidence: number;
  }[];
  in_jokes: unknown[];
  summary: string;
};

type ExtractResponse = {
  profile: LearningProfile;
  prompt_block: string;
};
```

`transcript.messages` must contain at least one message. A missing transcript,
empty messages list, or message without `id` produces the 422
`validation_failed` envelope; details are rooted at `transcript`,
`transcript.messages`, or `transcript.messages[0].id` respectively.
Unknown fields are ignored.

`meta.source` echoes `transcript.source` (the omitted value is represented by
the service's normal string default), and `meta.message_count` equals the
input message count. `meta.channels` is model-authored, not a closed enum:

| Input | Observed meaning |
| --- | --- |
| Explicit channels on messages | The named channels plus `"unlabelled"` when some messages lack a channel |
| No channel labels | Not stable; `[]` and `["general"]` have both been observed |

Confidence values are in `[0,1]`. `summary` may be empty. Model-authored
collections may be empty.

```sh
curl -sS "$HUMALIKE_API_URL/v1/social-learning/actions/extract" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "transcript":{
      "source":"recent-chat",
      "messages":[
        {"id":"m1","speaker":"Mira","text":"tea at 3?","channel":"lounge"},
        {"id":"m2","speaker":"Sol","text":"yep, jasmine please","reply_to":"m1"}
      ]
    }
  }'
```

## Using `prompt_block`

Use the returned `prompt_block` as the style-context portion of a later agent
system prompt. Refresh it on a bounded recent window when style has changed;
do not call extraction for every message. Keep the block separate from
Social Memory context:

```text
system prompt =
  agent identity and policy
  + learned-style prompt_block
  + current conversation context
  + recalled durable facts
```

The profile captures how a participant communicates. Social Memory captures
what happened and what facts can be recalled. Do not replace durable memory
with a newly extracted profile or assume that `prompt_block` is a fact store.
Extraction is billable.
