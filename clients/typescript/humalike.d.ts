/**
 * Humalike API recreation — TypeScript request/response types.
 *
 * Every type here is transcribed from spec/03 (realtime and memory) and
 * spec/04 (intelligence and personas), which are themselves transcribed from
 * live assertions. Field names, optionality, explicit `null`s, and literal
 * unions are the contract: `user_id?: string | null` means the key may be
 * absent *and* may be present as `null`, and `categorical: null | {...}`
 * means the key is always present and is explicitly `null` when inapplicable.
 *
 * Phase map (spec/07) — see clients/README.md:
 *   phase 1  Identity and usage
 *   phase 2  Threads, grants, events, WSS frames
 *   phase 3  Decisions, respond, pacing
 *   phase 4  Social Memory
 *   phase 5  Social Learning, foresee
 *   phase 6  Social Observability, audit
 *   phase 7  Personas
 */

// ---------------------------------------------------------------------------
// Protocol envelope (spec/02)
// ---------------------------------------------------------------------------

/** Request-model failure. 422. `loc` never carries a leading "body" segment. */
export interface RequestValidationError {
  error: {
    code: 'validation_failed';
    message: 'request validation failed';
    details: Array<{ loc: Array<string | number>; msg: string; type: ValidationErrorType }>;
  };
}

/** Observed `type` vocabulary; the string union is not closed by production. */
export type ValidationErrorType =
  | 'uuid_parsing'
  | 'too_short'
  | 'too_long'
  | 'string_too_long'
  | 'string_too_short'
  | 'literal_error'
  | 'missing'
  | (string & {});

/** Semantic failure. 400. `details` is absent for `invalid id`. */
export interface SemanticValidationError {
  error: {
    code: 'VALIDATION_ERROR';
    message: string;
    details?: Array<{ field: string; message: string }>;
  };
}

/** 401 on every public route, byte-for-byte. */
export interface UnauthorizedError {
  error: { code: 'UNAUTHORIZED'; message: 'missing or invalid credentials' };
}

/** 402/403/502 are documented defaults, not live-proven (spec/02 §Billing). */
export interface PaymentRequiredError {
  error: { code: 'PAYMENT_REQUIRED'; message: 'insufficient credits' };
}
export interface ForbiddenError {
  error: { code: 'forbidden'; message: string };
}
export interface UpstreamError {
  error: { code: 'UPSTREAM_ERROR'; message: string };
}

export type ApiError =
  | RequestValidationError
  | SemanticValidationError
  | UnauthorizedError
  | PaymentRequiredError
  | ForbiddenError
  | UpstreamError;

/**
 * ISO-8601 `YYYY-MM-DDTHH:MM:SS.ffffffZ` (microseconds, literal Z). The sole
 * exception is `AttachedFrame.server_time`, which uses `.ffffff+00:00`.
 */
export type Timestamp = string;

/** RFC-4122 UUID (the suites accept versions 1-5). */
export type Uuid = string;

// ---------------------------------------------------------------------------
// Phase 1 — Identity and usage (spec/03 §Identity and usage)
// ---------------------------------------------------------------------------

export interface WhoamiRequest {}

export interface WhoamiResponse {
  /** Non-empty. */
  user_id: string;
}

export type DayName = 'Mon' | 'Tue' | 'Wed' | 'Thu' | 'Fri' | 'Sat' | 'Sun';

/** The six production component slugs the suites key billing assertions on. */
export type ComponentSlug =
  | 'personas'
  | 'social-learning'
  | 'social-memory'
  | 'social-observability'
  | 'theoryofmind'
  | 'turn-taking';

export interface UsageSummaryRequest {}

export interface UsageSummary {
  total_calls: number;
  total_credits: number;
  per_component: Array<{ component: ComponentSlug; calls: number; credits: number }>;
  /** Exactly seven entries, oldest first, zero-filled, last seven UTC days. */
  daily_series: Array<{ date: DayName; requests: number }>;
}

// ---------------------------------------------------------------------------
// Phase 2 — Threads, integrations, grants (spec/03 §Thread creation)
// ---------------------------------------------------------------------------

export interface SocialSignalsIntegration {
  scope_id?: string;
  channel_id?: string;
}

export interface SocialMemoryIntegration {
  memory_bank_id: string;
}

export interface ThreadIntegrations {
  social_signals?: SocialSignalsIntegration;
  social_memory?: SocialMemoryIntegration;
}

export interface OpenThreadRequest {
  /** Omitted creates a UUID; an unused UUID creates a thread with that id. */
  thread_id?: Uuid;
  integrations?: ThreadIntegrations;
}

export interface OpenThreadResponse {
  thread: { id: Uuid; user_id: string; created_at: Timestamp; updated_at: Timestamp };
  /** Exactly `turn-taking-thread/{thread.id}`. */
  channel: string;
  realtime: {
    /** `wss://<origin-host>/v1/ws/turn-taking-thread?token=<payload>.<signature>` */
    connect_url: string;
    /** 30.0 s after issuance (the suites accept 25-35 s). */
    expires_at: Timestamp;
  };
}

// ---------------------------------------------------------------------------
// Phase 3 — Decisions, events, respond (spec/03 §Decisions and events)
// ---------------------------------------------------------------------------

export interface InboundMessage {
  /** 1-255 characters. */
  sender: string;
  /** 1-4000 characters. */
  content: string;
  client_ts?: string;
  has_media?: boolean;
}

export interface SubmitRequest {
  thread_id: Uuid;
  /** 1-20 entries. */
  messages: InboundMessage[];
  system_prompt?: string;
  skip_decide?: boolean;
}

export interface SubmitResponse {
  decision: 'speak' | 'stay_silent';
  /** First accepted batch on a fresh thread is 1; every batch adds exactly 1. */
  turn_epoch: number;
  /** Always `[]` under every documented trigger (spec/08 open question 2). */
  tags: string[];
  /** Populated from the configured bank even when the decision short-circuits. */
  recalled_context: string;
}

export type RecordEventType = 'typing_start' | 'typing_stop' | 'message_edited';

export interface RecordEventRequest {
  thread_id: Uuid;
  type: RecordEventType;
  sender: string;
  client_ts?: string;
}

/** Exactly `{tags: []}`. Free; does not touch the epoch. */
export interface RecordEventResponse {
  tags: string[];
}

export interface Pacing {
  /** Default 0. */
  reading_delay_ms?: number;
  /** Default 150. */
  typing_wpm?: number;
  /** Default 8000. Caps typing only; the 200 ms inter-bubble gap sits outside. */
  max_typing_ms?: number;
}

export interface RespondRequest {
  thread_id: Uuid;
  content: string;
  turn_epoch: number;
  system_prompt?: string;
  agent_name?: string;
  pacing?: Pacing;
  /** Opaque; deeply echoed on every delivered bubble, `null` when omitted. */
  metadata?: Record<string, unknown>;
}

export interface ScheduledMessage {
  id: Uuid;
  thread_id: Uuid;
  content: string;
  /** Zero-based. */
  position: number;
  deliver_at: Timestamp;
  status: 'scheduled';
  created_at: Timestamp;
  /** Equal to `created_at` at scheduling time. */
  updated_at: Timestamp;
}

/** A stale epoch returns exactly `{scheduled: [], superseded: true}`, unbilled. */
export interface RespondResponse {
  /** 1-5 entries, strictly increasing `deliver_at`. */
  scheduled: ScheduledMessage[];
  superseded: boolean;
}

// ---------------------------------------------------------------------------
// Phase 2 — WSS frames (spec/03 §WebSocket frames)
// ---------------------------------------------------------------------------

/** First frame. NOT wrapped in the event envelope; `.ffffff+00:00` offset form. */
export interface AttachedFrame {
  type: 'attached';
  channel: string;
  server_time: string;
}

export interface EventFrame<T> {
  /** `evt_` + 32 lowercase hex. */
  id: string;
  type: string;
  channel: string;
  ts: Timestamp;
  data: T;
}

export interface TypingData {
  thread_id: Uuid;
  typing: boolean;
}

export interface MessageData {
  /** A UUID generated for delivery; differs from the HTTP scheduled `id`. */
  message_id: Uuid;
  thread_id: Uuid;
  content: string;
  position: number;
  sent_at: Timestamp;
  metadata: Record<string, unknown> | null;
}

export type TypingFrame = EventFrame<TypingData> & { type: 'turn_taking.typing' };
export type MessageFrame = EventFrame<MessageData> & { type: 'turn_taking.message' };

/** Per reply: attached -> typing true -> N messages -> typing false (N+3). */
export type RealtimeFrame = AttachedFrame | TypingFrame | MessageFrame;

/** Expired or garbage grants complete the upgrade, then close 4000, empty reason. */
export type GrantCloseCode = 4000;

// ---------------------------------------------------------------------------
// Phase 4 — Social Memory (spec/03 §Social Memory)
// ---------------------------------------------------------------------------

export interface MemoryMessage {
  speaker: string;
  text: string;
}

export interface IngestRequest {
  scope_id: string;
  /** Ordered and non-empty. */
  transcript: MemoryMessage[];
}

export interface IngestResponse {
  /** Equals the transcript length. */
  ingested: number;
}

export interface RecallRequest {
  scope_id: string;
  message: MemoryMessage;
}

/** Exactly `{context}`; a fresh scope returns `{context: ""}`. */
export interface RecallResponse {
  context: string;
}

export interface AskRequest {
  scope_id: string;
  question: string;
}

/** Exactly `{answer}`. */
export interface AskResponse {
  answer: string;
}

// ---------------------------------------------------------------------------
// Phase 5-7 — Shared intelligence types (spec/04 §Shared types)
// ---------------------------------------------------------------------------

export interface TranscriptMessage {
  id: string;
  speaker: string;
  text: string;
  user_id?: string;
  channel?: string;
  timestamp?: string;
  reply_to?: string;
}

export interface Transcript {
  messages: TranscriptMessage[];
  source?: string;
}

export interface Persona {
  persona_id: string;
  fields: Record<string, string>;
  system_prompt: string;
  markdown: string;
}

/** Only `persona_id` is required on input; members default to `{}`/`""`/`""`. */
export interface PersonaInput {
  persona_id: string;
  fields?: Record<string, string>;
  system_prompt?: string;
  markdown?: string;
}

export interface NumericDistribution {
  min: number;
  max: number;
  mean: number;
  sd: number;
  integer: boolean;
}

export interface CategoricalDistribution {
  /** Relative weights; they need not sum to one. */
  weights: Record<string, number>;
}

export interface FieldSpecConditional {
  /** Keys are a subset of `parents`; a numeric parent's value is e.g. "23-35". */
  when: Record<string, string>;
  categorical: null | CategoricalDistribution;
  numeric: null | NumericDistribution;
}

export interface FieldSpec {
  name: string;
  label: string;
  kind: 'categorical' | 'numeric' | 'text' | 'derived';
  description: string;
  formula: string;
  parents: string[];
  /** Explicit `null` when inapplicable, including conditional-only fields. */
  categorical: null | CategoricalDistribution;
  numeric: null | NumericDistribution;
  conditionals: FieldSpecConditional[];
  ordered_values: null | string[];
}

export interface BlueprintConstraint {
  name: string;
  lhs: string;
  op: string;
  rhs: string;
}

export interface Blueprint {
  domain: string;
  language: string;
  /** Subset of field names including every categorical, numeric, derived field. */
  order: string[];
  fields: FieldSpec[];
  constraints: BlueprintConstraint[];
  style_axes: Record<string, string[]>;
  name_origins: string[];
  rationale: string;
  sources: string[];
}

/** Normalization defaults applied to a submitted blueprint before echo. */
export interface BlueprintInput {
  domain: string;
  language?: string;
  order?: string[];
  fields?: Array<Partial<FieldSpec> & { name: string; kind: FieldSpec['kind'] }>;
  constraints?: BlueprintConstraint[];
  style_axes?: Record<string, string[]>;
  name_origins?: string[];
  rationale?: string;
  sources?: string[];
}

export type Grounding = 'off' | 'web' | 'research';

/** Every action that starts asynchronous work returns exactly this. */
export interface JobAccepted {
  id: Uuid;
  status: 'pending';
}

export type JobStatus = 'pending' | 'running' | 'succeeded' | 'failed';

/**
 * A failed job is documented as a stable category such as `"provider_error"`;
 * no failure was observed live (spec/08 open question 9).
 */
export type JobError = null | string | Record<string, unknown>;

// ---------------------------------------------------------------------------
// Phase 5 — Social Learning (spec/04 §Social Learning)
// ---------------------------------------------------------------------------

export interface LearningProfile {
  meta: {
    /** Echoes the request `transcript.source`. */
    source: string;
    /** Model-authored; not stable for a channel-less transcript. */
    channels: string[];
    /** Equals the input message count. */
    message_count: number;
  };
  register: {
    formality: string;
    warmth: string;
    casing: string;
    notes: string;
    /** In [0,1]. */
    confidence: number;
  };
  style: { length: string; formatting: string; emoji: string };
  lexicon: Array<{ term: string; meaning: string; usage: string }>;
  banned_phrases: unknown[];
  address: { default: string; deference: unknown[] };
  taboos: Array<{ rule: string; scope: string; evidence: string[] }>;
  humor: { style: string; rules: string[] };
  roles: unknown[];
  norms: Array<{
    rule: string;
    type: string;
    evidence: Array<{ breach: string; sanction: string }>;
    confidence: number;
  }>;
  in_jokes: unknown[];
  /** MAY be empty. */
  summary: string;
}

export interface ExtractRequest {
  transcript: Transcript;
}

export interface ExtractResponse {
  profile: LearningProfile;
  /** Non-empty. */
  prompt_block: string;
}

// ---------------------------------------------------------------------------
// Phase 5 — Theory of Mind (spec/04 §Theory of Mind)
// ---------------------------------------------------------------------------

export interface ForeseeRequest {
  /** `conversation` is NOT an alias; using it returns 422 `missing`. */
  transcript: Array<{ speaker: string; text: string }>;
  /** `draft` is NOT an alias. */
  candidate_reply: string;
  agent_name?: string;
  system_prompt?: string;
  /** With a subject, both arrays contain exactly one entry named for it. */
  subject_name?: string;
}

export type Risk = 'low' | 'medium' | 'high';

export interface MentalState {
  name: string;
  beliefs: string[];
  goals: string[];
  /** `intensity` in [0,1]. */
  emotions: Array<{ type: string; intensity: number }>;
}

export interface PredictedReaction {
  name: string;
  summary: string;
  predicted_message: string;
  risk: Risk;
}

export interface ForeseeResponse {
  mental_state: MentalState[];
  predicted_reaction: PredictedReaction[];
  refined_reply: string;
  refinement_rationale: string;
}

// ---------------------------------------------------------------------------
// Phase 6 — Social Observability (spec/04 §Social Observability)
// ---------------------------------------------------------------------------

export type InteractionType =
  | 'transactional'
  | 'bonding'
  | 'venting'
  | 'banter'
  | 'friction'
  | 'hostile';

export type Reception = 'engaged' | 'neutral' | 'bored' | 'annoyed' | 'churn_risk';
export type Trend = 'improving' | 'stable' | 'declining';
export type Severity = 'low' | 'medium' | 'high';

export interface Interaction {
  type: InteractionType;
  topic: string;
  /** Supplied `user_id`s are echoed; audit-generated reports carry `null`. */
  participants: Array<{ name: string; stance: string; user_id?: string | null }>;
  /** Every id originates in the input. */
  message_ids: string[];
}

export interface KeyMoment {
  label: string;
  type: string;
  message_ids: string[];
  agent_critique?: string;
}

export interface PerUser {
  name: string;
  user_id?: string | null;
  reception: Reception;
  /** In [0,1]. */
  frustration: number;
  trend: Trend;
  behaviors: string[];
  evidence: string[];
  /** In [0,1]. */
  confidence: number;
  note?: string;
  /** Number of interactions this user participates in. */
  interaction_count: number;
  dominant_type: InteractionType;
  /** Exactly the six interaction types, zero counts included. */
  distribution: Array<{ type: InteractionType; count: number }>;
  key_moments: KeyMoment[];
}

export interface Finding {
  issue: string;
  severity: Severity;
  affected_users: string[];
  evidence: string[];
  recommendation: string;
  /** In [0,1]. */
  confidence: number;
  before_message_id?: string;
  rewritten_reply?: string;
  /** Observed: `social-memory`, `theory-of-mind`, `norms`. */
  suggested_component?: string;
  how_it_helps?: string;
}

export interface Report {
  /** In [0,1]. */
  health_score: number;
  summary: string;
  interactions: Interaction[];
  /** Exactly the six interaction types, zero counts included. */
  interaction_totals: Array<{ type: InteractionType; count: number }>;
  per_user: PerUser[];
  findings: Finding[];
}

export interface AnalyzeRequest {
  agent_name: string;
  transcript: Transcript;
  focus?: string;
}

/**
 * Exactly the report — no `id` key, no `Location`, no `x-report-id`. The stored
 * report is unreachable from this flow on purpose (spec/08 open question 1).
 */
export type AnalyzeResponse = Report;

/** A random valid UUID returns 200 JSON `null`; a malformed id returns 400. */
export type ReportByIdResponse = Report | null;

// ---------------------------------------------------------------------------
// Phase 6 — Full audit (spec/04 §Full audit)
// ---------------------------------------------------------------------------

export interface AuditPrepareRequest {
  /** 1-300,000 characters; also bounded by a ~32,768-token budget. */
  raw_text: string;
}

export interface AuditPrepareResponse {
  run_id: Uuid;
  messages: number;
  /** First-appearance order. */
  participants: string[];
  /** When non-null, one of `participants`. */
  agent_guess: string | null;
}

export interface AuditLaunchRequest {
  run_id: Uuid;
  /** MUST be one of the transcript's speakers. */
  agent_name: string;
}

/** First-write-wins: a repeat keeps the first agent and never restarts work. */
export interface AuditLaunchResponse {
  run_id: Uuid;
  agent_name: string;
  status: 'queued' | 'completed';
}

export interface AuditRunProjectionRequest {
  run_id: Uuid;
}

export interface AuditTranscriptMessage {
  id: string;
  speaker: string;
  text: string;
  user_id: null;
  channel: null;
  timestamp: null;
  reply_to: null;
}

export interface AuditRead {
  prompt_block: string | null;
  portrait: { role: string; personality: string; register: string } | null;
  /** Models the non-agent humans. */
  mental_state: MentalState[] | null;
  profiles: Array<{ name: string; facts: string[] }> | null;
}

export interface AuditVerdict {
  /** 0-based position in `transcript.messages` of an agent turn. */
  index: number;
  risk: Risk;
  summary: string;
  predicted_message: string;
}

export interface AuditReply {
  /** Same index as the matching verdict. */
  index: number;
  reply: string;
  /** The rewritten reply split into 1-3 bubble strings. */
  messages: string[];
  /** The rewrite's own risk. */
  risk: Risk;
}

/**
 * Exactly these keys; `status` and `stage` MUST NOT appear. Sections become
 * non-null monotonically: report <= read <= verdicts <= replies. Completion is
 * `replies.length === verdicts.length` stable across two polls.
 */
export interface AuditProjection {
  run_id: Uuid;
  /** Equals `agent_guess` before launch. */
  agent_name: string;
  transcript: { source: null; messages: AuditTranscriptMessage[] };
  report: Report | null;
  read: null | AuditRead;
  verdicts: null | AuditVerdict[];
  /** `[]` from the start, never `null`. */
  replies: AuditReply[];
}

// ---------------------------------------------------------------------------
// Phase 7 — Personas (spec/04 §Persona generation, enhancement, validation)
// ---------------------------------------------------------------------------

export interface Diversity {
  max_pairwise_similarity: number;
  mean_pairwise_similarity: number;
  duplicate_pairs: number;
}

export interface Marginal {
  attribute: string;
  /** `requested`/`achieved` are fractions summing to 1. */
  cells: Array<{ key: string; requested: number; achieved: number }>;
  /** ½·Σ|requested−achieved|. */
  total_variation_distance: number;
}

export interface GenerateRequest {
  prompt: string;
  /** >= 1. */
  count: number;
  grounding: Grounding;
}

export type GenerateResponse = JobAccepted;

export interface PopulationResult {
  /** `personas.length === count`; ids are `p0001`, `p0002`, … */
  personas: Persona[];
  blueprint: Blueprint;
  diversity: Diversity;
  marginals: Marginal[];
}

export interface PopulationResource {
  /** Equals the action id. */
  id: Uuid;
  created_at: Timestamp;
  updated_at: Timestamp;
  status: JobStatus;
  /** `null` -> `designing` -> (`generating`) -> `complete`; `total === count`. */
  progress: null | {
    phase: 'designing' | 'generating' | 'complete';
    produced: number;
    total: number;
  };
  prompt: string;
  count: number;
  grounding: Grounding;
  result: PopulationResult | null;
  error: JobError;
}

export interface EnhanceRequest {
  persona: string;
  grounding?: Grounding;
}

export type EnhanceResponse = JobAccepted;

/**
 * The enhanced persona has `persona_id` of the form `enhanced-<12 hex>`,
 * `fields: {}` (tested on purpose — do not "improve" it), and identical
 * `system_prompt` and `markdown` beginning `CHARACTER PROFILE`.
 */
export interface EnhancementResource {
  id: Uuid;
  created_at: Timestamp;
  updated_at: Timestamp;
  status: JobStatus;
  /** Echoes the request `persona`. */
  source: string;
  grounding: Grounding;
  persona: Persona | null;
  error: JobError;
}

export interface ValidateRequest {
  /** At least one; `persona_id` alone suffices. */
  personas: PersonaInput[];
  blueprint?: BlueprintInput;
}

export type ValidateResponse = JobAccepted;

export interface Gate {
  name: string;
  passed: boolean;
  score: number | null;
  detail: string;
}

export interface Scorecard {
  persona_id: string;
  /** Exactly two, `schema` then `constraints`. */
  gates: Gate[];
  /** Sparse; keys ⊆ {voice_attribution}, values in [0,1]. */
  soft_scores: Record<string, number>;
}

export interface EvaluationResult {
  /** True exactly when every gate passed; independent of job `status`. */
  passed: boolean;
  /** `max_pairwise_similarity` and one `marginal_tvd:<attribute>` per marginal; `[]` for a single persona. */
  gates: Gate[];
  scorecards: Scorecard[];
  diversity: Diversity | null;
  marginals: Marginal[];
  notes: string[];
}

export interface EvaluationResource {
  id: Uuid;
  created_at: Timestamp;
  updated_at: Timestamp;
  status: JobStatus;
  progress: null | { phase: 'evaluating' | 'complete' };
  /** Submitted personas echoed with input defaults applied. */
  personas: Persona[];
  /** Normalized before echo; `null` when omitted. */
  blueprint: Blueprint | null;
  result: EvaluationResult | null;
  error: JobError;
}

// ---------------------------------------------------------------------------
// Client surface (clients/typescript/client.mjs)
// ---------------------------------------------------------------------------

export interface HumalikeClientOptions {
  /** Defaults to `HUMALIKE_API_URL` or `https://api.humalike.com`. */
  baseUrl?: string;
  /** Defaults to `HUMALIKE_API_KEY`. */
  apiKey?: string;
  /** Milliseconds; defaults to 300000 to cover asynchronous persona work. */
  timeoutMs?: number;
  fetch?: typeof fetch;
}

/** Thrown for any non-2xx response; carries the parsed error envelope. */
export declare class HumalikeApiError extends Error {
  status: number;
  /** Non-empty on every captured production response. */
  requestId: string | null;
  body: ApiError | unknown;
  /** `error.code`; branch on this, never on message text (spec/02). */
  code: string | null;
  constructor(status: number, requestId: string | null, body: unknown);
}

export declare class HumalikeClient {
  constructor(options?: HumalikeClientOptions);

  /** `x-request-id` of the most recent response, success or error. */
  readonly lastRequestId: string | null;

  // phase 1
  whoami(): Promise<WhoamiResponse>;
  usageSummary(): Promise<UsageSummary>;

  // phase 2-3
  openThread(body?: OpenThreadRequest): Promise<OpenThreadResponse>;
  submitMessages(body: SubmitRequest): Promise<SubmitResponse>;
  recordEvent(body: RecordEventRequest): Promise<RecordEventResponse>;
  respond(body: RespondRequest): Promise<RespondResponse>;

  // phase 4
  ingest(body: IngestRequest, idempotencyKey?: string): Promise<IngestResponse>;
  recall(body: RecallRequest): Promise<RecallResponse>;
  ask(body: AskRequest): Promise<AskResponse>;

  // phase 5
  extract(body: ExtractRequest): Promise<ExtractResponse>;
  foresee(body: ForeseeRequest): Promise<ForeseeResponse>;

  // phase 6
  analyze(body: AnalyzeRequest): Promise<AnalyzeResponse>;
  reportById(id: string): Promise<ReportByIdResponse>;
  auditPrepare(body: AuditPrepareRequest): Promise<AuditPrepareResponse>;
  auditLaunch(body: AuditLaunchRequest): Promise<AuditLaunchResponse>;
  auditRun(body: AuditRunProjectionRequest): Promise<AuditProjection>;
  waitForAudit(runId: string, options?: { intervalMs?: number; timeoutMs?: number }): Promise<AuditProjection>;

  // phase 7
  generatePersonas(body: GenerateRequest): Promise<GenerateResponse>;
  population(id: string): Promise<PopulationResource | null>;
  enhancePersona(body: EnhanceRequest): Promise<EnhanceResponse>;
  enhancement(id: string): Promise<EnhancementResource | null>;
  validatePersonas(body: ValidateRequest): Promise<ValidateResponse>;
  evaluation(id: string): Promise<EvaluationResource | null>;
  waitForJob<T extends PopulationResource | EnhancementResource | EvaluationResource>(
    fetchResource: (id: string) => Promise<T | null>,
    id: string,
    options?: { intervalMs?: number; timeoutMs?: number },
  ): Promise<T>;
}
