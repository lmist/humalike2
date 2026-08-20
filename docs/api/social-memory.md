# Social Memory

Social Memory is an owner-scoped, append-only store of ordered transcript
messages and subject-attributed facts. A `scope_id` is a caller-selected
conversation partition. There is no public list, clear, or delete route.
Choose a new scope to reset a conversation.

## `POST /v1/social-memory/actions/ingest`

```ts
type MemoryMessage = {speaker: string; text: string};
type IngestRequest = {scope_id: string; transcript: MemoryMessage[]};
type IngestResponse = {ingested: number};
```

`transcript` is ordered and non-empty. The response's `ingested` is exactly
the number of submitted messages. An empty transcript is HTTP 422 with a
`too_short` detail at `loc:["transcript"]`.

```sh
curl -sS "$HUMALIKE_API_URL/v1/social-memory/actions/ingest" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: memory-import-001" \
  -d '{
    "scope_id":"customer-42",
    "transcript":[
      {"speaker":"Yara","text":"Xena chose the blue card."},
      {"speaker":"Xena","text":"The green card comes second."}
    ]
  }'
```

### Idempotency

`Idempotency-Key` is optional. Without it, each request appends its ordered
batch. When supplied, the key is first-write-wins across the entire
authenticated owner:

1. The first completed `(owner, key)` request stores its response and side
   effects.
2. A later request with the same key returns HTTP 200 with the first response.
3. The later body is ignored, even if its transcript differs.
4. The later `scope_id` is ignored too; reusing a key in another scope does not
   write to that scope.
5. Replaying the same body does not duplicate facts.

There is no required replay-indicator header. Do not treat an idempotency key
as scope-local.

## `POST /v1/social-memory/actions/recall`

```ts
type RecallRequest = {
  scope_id: string;
  message: {speaker: string; text: string};
};
type RecallResponse = {context: string};
```

The returned context is a string suitable for supplying to a turn decision.
A fresh scope returns exactly `{context:""}`. Retrieval preserves subject
attribution: a fact stated by one speaker can be recalled as belonging to the
subject named in the content.

```sh
curl -sS "$HUMALIKE_API_URL/v1/social-memory/actions/recall" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "scope_id":"customer-42",
    "message":{"speaker":"Xena","text":"Remind me which card comes first."}
  }'
```

## `POST /v1/social-memory/actions/ask`

```ts
type AskRequest = {scope_id: string; question: string};
type AskResponse = {answer: string};
```

Answers are grounded in content ingested into the same scope. Tested ordering
facts remain ordered in the answer. An empty question is HTTP 422 with a
`string_too_short` detail at `loc:["question"]`.

```sh
curl -sS "$HUMALIKE_API_URL/v1/social-memory/actions/ask" \
  -H "Authorization: Bearer $HUMALIKE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"scope_id":"customer-42","question":"Which card comes first?"}'
```

Ingest is free. `recall` and `ask` are billable model-backed reads. All three
routes remain owner-scoped and require bearer authentication.
