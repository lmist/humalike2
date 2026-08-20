"""Humalike API recreation — Python client (standard library only).

One method per endpoint in spec/03 and spec/04, bearer authentication on every
call, and ``x-request-id`` captured from every response, success or error.
Response shapes are ``TypedDict``s transcribed from the same spec sections as
``clients/typescript/humalike.d.ts``: keys, optionality, explicit ``None``s,
and ``Literal`` unions are the contract.

Only ``urllib`` is used, so this file can be vendored into an operator script,
a migration check, or a runbook step without adding a dependency.

    from humalike_client import HumalikeClient

    hum = HumalikeClient()                 # reads HUMALIKE_API_URL/KEY
    print(hum.whoami()["user_id"])

Phase map: clients/README.md.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, TypedDict

__all__ = ["HumalikeClient", "HumalikeApiError", "DEFAULT_ORIGIN"]

DEFAULT_ORIGIN = "https://api.humalike.com"

# ---------------------------------------------------------------------------
# Protocol envelope (spec/02)
# ---------------------------------------------------------------------------

#: ISO-8601 ``YYYY-MM-DDTHH:MM:SS.ffffffZ``. The WSS ``attached.server_time``
#: is the sole ``.ffffff+00:00`` exception.
Timestamp = str
Uuid = str

ValidationErrorType = Literal[
    "uuid_parsing", "too_short", "too_long",
    "string_too_long", "string_too_short", "literal_error", "missing",
]


class ValidationDetail(TypedDict):
    loc: list[str | int]
    msg: str
    type: str


class SemanticDetail(TypedDict):
    field: str
    message: str


class HumalikeApiError(Exception):
    """Raised for any non-2xx response.

    Branch on :attr:`code` (``error.code``), never on message text (spec/02).
    A stale-epoch respond and a missing repository id are *not* errors: they
    are 200 responses with ``superseded: true`` and JSON ``null``.
    """

    def __init__(self, status: int, request_id: str | None, body: Any) -> None:
        self.status = status
        self.request_id = request_id
        self.body = body
        self.code: str | None = None
        message = str(status)
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            self.code = body["error"].get("code")
            message = f"{status} {self.code}: {body['error'].get('message')}"
        super().__init__(message)


# ---------------------------------------------------------------------------
# Phase 1 — Identity and usage (spec/03 §Identity and usage)
# ---------------------------------------------------------------------------

ComponentSlug = Literal[
    "personas", "social-learning", "social-memory",
    "social-observability", "theoryofmind", "turn-taking",
]
DayName = Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class WhoamiResponse(TypedDict):
    user_id: str


class ComponentUsage(TypedDict):
    component: ComponentSlug
    calls: int
    credits: int


class DailyUsage(TypedDict):
    date: DayName
    requests: int


class UsageSummary(TypedDict):
    total_calls: int
    total_credits: int
    per_component: list[ComponentUsage]
    #: Exactly seven entries, oldest first, zero-filled.
    daily_series: list[DailyUsage]


# ---------------------------------------------------------------------------
# Phase 2 — Threads, integrations, grants (spec/03 §Thread creation)
# ---------------------------------------------------------------------------


class SocialSignalsIntegration(TypedDict, total=False):
    scope_id: str
    channel_id: str


class SocialMemoryIntegration(TypedDict):
    memory_bank_id: str


class ThreadIntegrations(TypedDict, total=False):
    social_signals: SocialSignalsIntegration
    social_memory: SocialMemoryIntegration


class ThreadResource(TypedDict):
    id: Uuid
    user_id: str
    created_at: Timestamp
    updated_at: Timestamp


class RealtimeGrant(TypedDict):
    #: ``wss://<origin-host>/v1/ws/turn-taking-thread?token=<payload>.<sig>``
    connect_url: str
    #: 30.0 s after issuance (the suites accept 25-35 s).
    expires_at: Timestamp


class OpenThreadResponse(TypedDict):
    thread: ThreadResource
    #: Exactly ``turn-taking-thread/{thread.id}``.
    channel: str
    realtime: RealtimeGrant


# ---------------------------------------------------------------------------
# Phase 3 — Decisions, events, respond (spec/03 §Decisions and events)
# ---------------------------------------------------------------------------


class InboundMessage(TypedDict, total=False):
    sender: str      # required, 1-255 characters
    content: str     # required, 1-4000 characters
    client_ts: str
    has_media: bool


class SubmitResponse(TypedDict):
    decision: Literal["speak", "stay_silent"]
    turn_epoch: int
    #: Always ``[]`` under every documented trigger (spec/08 open question 2).
    tags: list[str]
    recalled_context: str


RecordEventType = Literal["typing_start", "typing_stop", "message_edited"]


class RecordEventResponse(TypedDict):
    tags: list[str]


class Pacing(TypedDict, total=False):
    reading_delay_ms: float   # default 0
    typing_wpm: float         # default 150
    max_typing_ms: float      # default 8000, excludes the 200 ms bubble gap


class ScheduledMessage(TypedDict):
    id: Uuid
    thread_id: Uuid
    content: str
    position: int             # zero-based
    deliver_at: Timestamp
    status: Literal["scheduled"]
    created_at: Timestamp
    updated_at: Timestamp     # equal to created_at


class RespondResponse(TypedDict):
    #: 1-5 entries with strictly increasing ``deliver_at``; ``[]`` when superseded.
    scheduled: list[ScheduledMessage]
    superseded: bool


# ---------------------------------------------------------------------------
# Phase 2 — WSS frames (spec/03 §WebSocket frames)
# ---------------------------------------------------------------------------


class AttachedFrame(TypedDict):
    type: Literal["attached"]
    channel: str
    #: ``.ffffff+00:00`` offset form, unlike every HTTP timestamp.
    server_time: str


class TypingData(TypedDict):
    thread_id: Uuid
    typing: bool


class MessageData(TypedDict):
    #: Generated for delivery; differs from the HTTP scheduled ``id``.
    message_id: Uuid
    thread_id: Uuid
    content: str
    position: int
    sent_at: Timestamp
    metadata: dict[str, Any] | None


class EventFrame(TypedDict):
    id: str  # "evt_" + 32 lowercase hex
    type: str
    channel: str
    ts: Timestamp
    data: Any


#: Expired or garbage grants complete the upgrade, then close with this code.
GRANT_CLOSE_CODE = 4000


# ---------------------------------------------------------------------------
# Phase 4 — Social Memory (spec/03 §Social Memory)
# ---------------------------------------------------------------------------


class MemoryMessage(TypedDict):
    speaker: str
    text: str


class IngestResponse(TypedDict):
    #: Equals the transcript length.
    ingested: int


class RecallResponse(TypedDict):
    context: str


class AskResponse(TypedDict):
    answer: str


# ---------------------------------------------------------------------------
# Phase 5-7 — Shared intelligence types (spec/04 §Shared types)
# ---------------------------------------------------------------------------


class TranscriptMessage(TypedDict, total=False):
    id: str        # required
    speaker: str   # required
    text: str      # required
    user_id: str
    channel: str
    timestamp: str
    reply_to: str


class Transcript(TypedDict, total=False):
    messages: list[TranscriptMessage]  # required
    source: str


class Persona(TypedDict):
    persona_id: str
    fields: dict[str, str]
    system_prompt: str
    markdown: str


class PersonaInput(TypedDict, total=False):
    persona_id: str  # required; the other members default to {} / "" / ""
    fields: dict[str, str]
    system_prompt: str
    markdown: str


class NumericDistribution(TypedDict):
    min: float
    max: float
    mean: float
    sd: float
    integer: bool


class CategoricalDistribution(TypedDict):
    #: Relative weights; they need not sum to one.
    weights: dict[str, float]


class FieldConditional(TypedDict):
    #: Keys are a subset of ``parents``; a numeric parent's value is e.g. "23-35".
    when: dict[str, str]
    categorical: CategoricalDistribution | None
    numeric: NumericDistribution | None


class FieldSpec(TypedDict):
    name: str
    label: str
    kind: Literal["categorical", "numeric", "text", "derived"]
    description: str
    formula: str
    parents: list[str]
    #: Explicit ``None`` when inapplicable, including conditional-only fields.
    categorical: CategoricalDistribution | None
    numeric: NumericDistribution | None
    conditionals: list[FieldConditional]
    ordered_values: list[str] | None


class BlueprintConstraint(TypedDict):
    name: str
    lhs: str
    op: str
    rhs: str


class Blueprint(TypedDict):
    domain: str
    language: str
    #: Subset of field names including every categorical, numeric, derived field.
    order: list[str]
    fields: list[FieldSpec]
    constraints: list[BlueprintConstraint]
    style_axes: dict[str, list[str]]
    name_origins: list[str]
    rationale: str
    sources: list[str]


Grounding = Literal["off", "web", "research"]
JobStatus = Literal["pending", "running", "succeeded", "failed"]
Risk = Literal["low", "medium", "high"]


class JobAccepted(TypedDict):
    id: Uuid
    status: Literal["pending"]


# ---------------------------------------------------------------------------
# Phase 5 — Social Learning (spec/04 §Social Learning)
# ---------------------------------------------------------------------------


class LearningMeta(TypedDict):
    #: Echoes the request ``transcript.source``.
    source: str
    #: Model-authored; not stable for a channel-less transcript.
    channels: list[str]
    #: Equals the input message count.
    message_count: int


class LearningRegister(TypedDict):
    formality: str
    warmth: str
    casing: str
    notes: str
    confidence: float  # [0,1]


class LearningStyle(TypedDict):
    length: str
    formatting: str
    emoji: str


class LexiconEntry(TypedDict):
    term: str
    meaning: str
    usage: str


class Address(TypedDict):
    default: str
    deference: list[Any]


class Taboo(TypedDict):
    rule: str
    scope: str
    evidence: list[str]


class Humor(TypedDict):
    style: str
    rules: list[str]


class NormEvidence(TypedDict):
    breach: str
    sanction: str


class Norm(TypedDict):
    rule: str
    type: str
    evidence: list[NormEvidence]
    confidence: float  # [0,1]


class LearningProfile(TypedDict):
    meta: LearningMeta
    register: LearningRegister
    style: LearningStyle
    lexicon: list[LexiconEntry]
    banned_phrases: list[Any]
    address: Address
    taboos: list[Taboo]
    humor: Humor
    roles: list[Any]
    norms: list[Norm]
    in_jokes: list[Any]
    summary: str  # MAY be empty


class ExtractResponse(TypedDict):
    profile: LearningProfile
    prompt_block: str  # non-empty


# ---------------------------------------------------------------------------
# Phase 5 — Theory of Mind (spec/04 §Theory of Mind)
# ---------------------------------------------------------------------------


class Emotion(TypedDict):
    type: str
    intensity: float  # [0,1]


class MentalState(TypedDict):
    name: str
    beliefs: list[str]
    goals: list[str]
    emotions: list[Emotion]


class PredictedReaction(TypedDict):
    name: str
    summary: str
    predicted_message: str
    risk: Risk


class ForeseeResponse(TypedDict):
    mental_state: list[MentalState]
    predicted_reaction: list[PredictedReaction]
    refined_reply: str
    refinement_rationale: str


# ---------------------------------------------------------------------------
# Phase 6 — Social Observability (spec/04 §Social Observability)
# ---------------------------------------------------------------------------

InteractionType = Literal[
    "transactional", "bonding", "venting", "banter", "friction", "hostile",
]
Reception = Literal["engaged", "neutral", "bored", "annoyed", "churn_risk"]
Trend = Literal["improving", "stable", "declining"]
Severity = Literal["low", "medium", "high"]


class Participant(TypedDict, total=False):
    name: str    # required
    stance: str  # required
    #: Supplied ids are echoed; audit-generated reports carry ``None``.
    user_id: str | None


class Interaction(TypedDict):
    type: InteractionType
    topic: str
    participants: list[Participant]
    #: Every id originates in the input.
    message_ids: list[str]


class TypeCount(TypedDict):
    type: InteractionType
    count: int


class KeyMoment(TypedDict, total=False):
    label: str            # required
    type: str             # required
    message_ids: list[str]  # required
    agent_critique: str


class PerUser(TypedDict, total=False):
    name: str                       # required
    user_id: str | None
    reception: Reception            # required
    frustration: float              # required, [0,1]
    trend: Trend                    # required
    behaviors: list[str]            # required
    evidence: list[str]             # required
    confidence: float               # required, [0,1]
    note: str
    interaction_count: int          # required
    dominant_type: InteractionType  # required
    #: Exactly the six interaction types, zero counts included.
    distribution: list[TypeCount]   # required
    key_moments: list[KeyMoment]    # required


class Finding(TypedDict, total=False):
    issue: str                # required
    severity: Severity        # required
    affected_users: list[str]  # required
    evidence: list[str]       # required
    recommendation: str       # required
    confidence: float         # required, [0,1]
    before_message_id: str
    rewritten_reply: str
    #: Observed: ``social-memory``, ``theory-of-mind``, ``norms``.
    suggested_component: str
    how_it_helps: str


class Report(TypedDict):
    health_score: float  # [0,1]
    summary: str
    interactions: list[Interaction]
    #: Exactly the six interaction types, zero counts included.
    interaction_totals: list[TypeCount]
    per_user: list[PerUser]
    findings: list[Finding]


# ---------------------------------------------------------------------------
# Phase 6 — Full audit (spec/04 §Full audit)
# ---------------------------------------------------------------------------


class AuditPrepareResponse(TypedDict):
    run_id: Uuid
    messages: int
    #: First-appearance order.
    participants: list[str]
    #: When non-null, one of ``participants``.
    agent_guess: str | None


class AuditLaunchResponse(TypedDict):
    run_id: Uuid
    agent_name: str
    status: Literal["queued", "completed"]


class AuditTranscriptMessage(TypedDict):
    id: str
    speaker: str
    text: str
    user_id: None
    channel: None
    timestamp: None
    reply_to: None


class AuditTranscript(TypedDict):
    source: None
    messages: list[AuditTranscriptMessage]


class Portrait(TypedDict):
    role: str
    personality: str
    register: str


class ProfileEntry(TypedDict):
    name: str
    facts: list[str]


class AuditRead(TypedDict):
    prompt_block: str | None
    portrait: Portrait | None
    #: Models the non-agent humans.
    mental_state: list[MentalState] | None
    profiles: list[ProfileEntry] | None


class AuditVerdict(TypedDict):
    #: 0-based position in ``transcript.messages`` of an agent turn.
    index: int
    risk: Risk
    summary: str
    predicted_message: str


class AuditReply(TypedDict):
    index: int
    reply: str
    #: The rewritten reply split into 1-3 bubble strings.
    messages: list[str]
    #: The rewrite's own risk.
    risk: Risk


class AuditProjection(TypedDict):
    """Exactly these keys; ``status`` and ``stage`` MUST NOT appear.

    Sections become non-null monotonically: report <= read <= verdicts <=
    replies. ``replies`` is ``[]`` from the start, never ``None``.
    """

    run_id: Uuid
    #: Equals ``agent_guess`` before launch.
    agent_name: str
    transcript: AuditTranscript
    report: Report | None
    read: AuditRead | None
    verdicts: list[AuditVerdict] | None
    replies: list[AuditReply]


# ---------------------------------------------------------------------------
# Phase 7 — Personas (spec/04 §Persona generation, enhancement, validation)
# ---------------------------------------------------------------------------


class Diversity(TypedDict):
    max_pairwise_similarity: float
    mean_pairwise_similarity: float
    duplicate_pairs: int


class MarginalCell(TypedDict):
    key: str
    #: Fractions summing to 1.
    requested: float
    achieved: float


class Marginal(TypedDict):
    attribute: str
    cells: list[MarginalCell]
    #: ½·Σ|requested−achieved|.
    total_variation_distance: float


class PopulationProgress(TypedDict):
    phase: Literal["designing", "generating", "complete"]
    produced: int
    total: int  # equals the requested count


class PopulationResult(TypedDict):
    #: ``len(personas) == count``; ids are ``p0001``, ``p0002``, …
    personas: list[Persona]
    blueprint: Blueprint
    diversity: Diversity
    marginals: list[Marginal]


class PopulationResource(TypedDict):
    id: Uuid  # equals the action id
    created_at: Timestamp
    updated_at: Timestamp
    status: JobStatus
    progress: PopulationProgress | None
    prompt: str
    count: int
    grounding: Grounding
    result: PopulationResult | None
    #: Documented ``"provider_error"`` category only; no failure observed live.
    error: str | dict[str, Any] | None


class EnhancementResource(TypedDict):
    id: Uuid
    created_at: Timestamp
    updated_at: Timestamp
    status: JobStatus
    #: Echoes the request ``persona``.
    source: str
    grounding: Grounding
    #: ``persona_id`` is ``enhanced-<12 hex>`` and ``fields`` is ``{}`` by design.
    persona: Persona | None
    error: str | dict[str, Any] | None


class Gate(TypedDict):
    name: str
    passed: bool
    score: float | None
    detail: str


class Scorecard(TypedDict):
    persona_id: str
    #: Exactly two, ``schema`` then ``constraints``.
    gates: list[Gate]
    #: Sparse; keys ⊆ {voice_attribution}, values in [0,1].
    soft_scores: dict[str, float]


class EvaluationResult(TypedDict):
    #: True exactly when every gate passed; independent of job ``status``.
    passed: bool
    #: ``max_pairwise_similarity`` and one ``marginal_tvd:<attr>`` per marginal.
    gates: list[Gate]
    scorecards: list[Scorecard]
    diversity: Diversity | None
    marginals: list[Marginal]
    notes: list[str]


class EvaluationProgress(TypedDict):
    phase: Literal["evaluating", "complete"]


class EvaluationResource(TypedDict):
    id: Uuid
    created_at: Timestamp
    updated_at: Timestamp
    status: JobStatus
    progress: EvaluationProgress | None
    #: Submitted personas echoed with input defaults applied.
    personas: list[Persona]
    #: Normalized before echo; ``None`` when omitted.
    blueprint: Blueprint | None
    result: EvaluationResult | None
    error: str | dict[str, Any] | None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


@dataclass
class HumalikeClient:
    """Bearer-authenticated client over ``urllib``.

    ``base_url`` and ``api_key`` default to ``HUMALIKE_API_URL`` and
    ``HUMALIKE_API_KEY`` so scripts and runbook steps share one configuration
    with the conformance suites.
    """

    base_url: str = field(default_factory=lambda: os.environ.get("HUMALIKE_API_URL", DEFAULT_ORIGIN))
    api_key: str = field(default_factory=lambda: os.environ.get("HUMALIKE_API_KEY", ""))
    #: Population ran ~52 s and enhancement ~37 s live (spec/06), so seconds
    #: is the wrong unit for a default here.
    timeout: float = 300.0
    #: ``x-request-id`` of the most recent response, success or error.
    last_request_id: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    # -- transport ---------------------------------------------------------

    def request(self, method: str, path: str, body: Any = None,
                headers: dict[str, str] | None = None) -> Any:
        data = None
        request_headers = {"authorization": f"Bearer {self.api_key}"}
        if method == "POST":
            data = json.dumps(body if body is not None else {}).encode("utf-8")
            request_headers["content-type"] = "application/json"
        request_headers.update(headers or {})
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method,
            headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self.last_request_id = response.headers.get("x-request-id")
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            self.last_request_id = exc.headers.get("x-request-id") if exc.headers else None
            raw = exc.read().decode("utf-8")
            parsed = json.loads(raw) if raw else None
            raise HumalikeApiError(exc.code, self.last_request_id, parsed) from None
        return json.loads(raw) if raw else None

    # -- phase 1: identity and usage ---------------------------------------

    def whoami(self) -> WhoamiResponse:
        return self.request("POST", "/v1/turn-taking/actions/whoami", {})

    def usage_summary(self) -> UsageSummary:
        return self.request("POST", "/v1/credits/projections/usage-summary", {})

    # -- phase 2: threads and grants ---------------------------------------

    def open_thread(self, thread_id: str | None = None,
                    integrations: ThreadIntegrations | None = None) -> OpenThreadResponse:
        body: dict[str, Any] = {}
        if thread_id is not None:
            body["thread_id"] = thread_id
        if integrations is not None:
            body["integrations"] = integrations
        return self.request("POST", "/v1/turn-taking/actions/open_thread", body)

    # -- phase 3: decisions, events, respond -------------------------------

    def submit_messages(self, thread_id: str, messages: list[InboundMessage],
                        system_prompt: str | None = None,
                        skip_decide: bool | None = None) -> SubmitResponse:
        body: dict[str, Any] = {"thread_id": thread_id, "messages": messages}
        if system_prompt is not None:
            body["system_prompt"] = system_prompt
        if skip_decide is not None:
            body["skip_decide"] = skip_decide
        return self.request("POST", "/v1/turn-taking/actions/submit_messages", body)

    def record_event(self, thread_id: str, type: RecordEventType, sender: str,
                     client_ts: str | None = None) -> RecordEventResponse:
        body: dict[str, Any] = {"thread_id": thread_id, "type": type, "sender": sender}
        if client_ts is not None:
            body["client_ts"] = client_ts
        return self.request("POST", "/v1/turn-taking/actions/record_event", body)

    def respond(self, thread_id: str, content: str, turn_epoch: int,
                system_prompt: str | None = None, agent_name: str | None = None,
                pacing: Pacing | None = None,
                metadata: dict[str, Any] | None = None) -> RespondResponse:
        """A stale ``turn_epoch`` returns ``{"scheduled": [], "superseded": True}``
        as a normal 200 and is not billed — it is not an error path."""
        body: dict[str, Any] = {
            "thread_id": thread_id, "content": content, "turn_epoch": turn_epoch}
        if system_prompt is not None:
            body["system_prompt"] = system_prompt
        if agent_name is not None:
            body["agent_name"] = agent_name
        if pacing is not None:
            body["pacing"] = pacing
        if metadata is not None:
            body["metadata"] = metadata
        return self.request("POST", "/v1/turn-taking/actions/respond", body)

    # -- phase 4: Social Memory --------------------------------------------

    def ingest(self, scope_id: str, transcript: list[MemoryMessage],
               idempotency_key: str | None = None) -> IngestResponse:
        """``idempotency_key`` is owner-wide and first-write-wins: the same key
        with a changed body or a different ``scope_id`` replays the first
        response and stores nothing new (spec/02 §Idempotency)."""
        headers = {"idempotency-key": idempotency_key} if idempotency_key else None
        return self.request(
            "POST", "/v1/social-memory/actions/ingest",
            {"scope_id": scope_id, "transcript": transcript}, headers)

    def recall(self, scope_id: str, message: MemoryMessage) -> RecallResponse:
        return self.request("POST", "/v1/social-memory/actions/recall",
                            {"scope_id": scope_id, "message": message})

    def ask(self, scope_id: str, question: str) -> AskResponse:
        return self.request("POST", "/v1/social-memory/actions/ask",
                            {"scope_id": scope_id, "question": question})

    # -- phase 5: Social Learning and foresee -------------------------------

    def extract(self, transcript: Transcript) -> ExtractResponse:
        return self.request("POST", "/v1/social-learning/actions/extract",
                            {"transcript": transcript})

    def foresee(self, transcript: list[dict[str, str]], candidate_reply: str,
                agent_name: str | None = None, system_prompt: str | None = None,
                subject_name: str | None = None) -> ForeseeResponse:
        """``conversation``/``draft`` are not aliases for ``transcript``/
        ``candidate_reply``; sending them returns 422 ``missing``."""
        body: dict[str, Any] = {
            "transcript": transcript, "candidate_reply": candidate_reply}
        if agent_name is not None:
            body["agent_name"] = agent_name
        if system_prompt is not None:
            body["system_prompt"] = system_prompt
        if subject_name is not None:
            body["subject_name"] = subject_name
        return self.request("POST", "/v1/foresee/actions/foresee", body)

    # -- phase 6: observability and audit -----------------------------------

    def analyze(self, agent_name: str, transcript: Transcript,
                focus: str | None = None) -> Report:
        """Returns the report itself: no id, no ``Location``, no
        ``x-report-id``. There is no public route back to the stored copy
        (spec/08 open question 1)."""
        body: dict[str, Any] = {"agent_name": agent_name, "transcript": transcript}
        if focus is not None:
            body["focus"] = focus
        return self.request("POST", "/v1/social-observability/actions/analyze", body)

    def report_by_id(self, report_id: str) -> Report | None:
        """``None`` for a valid unknown UUID; a malformed id raises 400."""
        return self.request(
            "GET", f"/v1/social-observability/repositories/Report/by-id/{report_id}")

    def audit_prepare(self, raw_text: str) -> AuditPrepareResponse:
        return self.request("POST", "/v1/social-observability/actions/audit_prepare",
                            {"raw_text": raw_text})

    def audit_launch(self, run_id: str, agent_name: str) -> AuditLaunchResponse:
        """First-write-wins: a repeat returns 200 and keeps the first agent."""
        return self.request("POST", "/v1/social-observability/actions/audit_launch",
                            {"run_id": run_id, "agent_name": agent_name})

    def audit_run(self, run_id: str) -> AuditProjection:
        return self.request("POST", "/v1/social-observability/projections/audit-run",
                            {"run_id": run_id})

    def wait_for_audit(self, run_id: str, interval: float = 2.0,
                       timeout: float | None = None) -> AuditProjection:
        """Poll until ``len(replies) == len(verdicts)`` and the projection is
        stable across two polls — the tested completion signal, since the
        projection never exposes ``status`` or ``stage``. Polling is free."""
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        previous: AuditProjection | None = None
        while time.monotonic() < deadline:
            projection = self.audit_run(run_id)
            done = (projection["verdicts"] is not None
                    and len(projection["replies"]) == len(projection["verdicts"]))
            if done and previous == projection:
                return projection
            previous = projection if done else None
            time.sleep(interval)
        raise TimeoutError(f"audit {run_id} did not complete within the timeout")

    # -- phase 7: personas ---------------------------------------------------

    def generate_personas(self, prompt: str, count: int,
                          grounding: Grounding = "off") -> JobAccepted:
        return self.request("POST", "/v1/personas/actions/generate",
                            {"prompt": prompt, "count": count, "grounding": grounding})

    def population(self, population_id: str) -> PopulationResource | None:
        return self.request(
            "GET", f"/v1/personas/repositories/Population/by-id/{population_id}")

    def enhance_persona(self, persona: str,
                        grounding: Grounding | None = None) -> JobAccepted:
        body: dict[str, Any] = {"persona": persona}
        if grounding is not None:
            body["grounding"] = grounding
        return self.request("POST", "/v1/personas/actions/enhance", body)

    def enhancement(self, enhancement_id: str) -> EnhancementResource | None:
        return self.request(
            "GET", f"/v1/personas/repositories/Enhancement/by-id/{enhancement_id}")

    def validate_personas(self, personas: list[PersonaInput],
                          blueprint: Blueprint | dict[str, Any] | None = None) -> JobAccepted:
        body: dict[str, Any] = {"personas": personas}
        if blueprint is not None:
            body["blueprint"] = blueprint
        return self.request("POST", "/v1/personas/actions/validate", body)

    def evaluation(self, evaluation_id: str) -> EvaluationResource | None:
        return self.request(
            "GET", f"/v1/personas/repositories/Evaluation/by-id/{evaluation_id}")

    def wait_for_job(self, fetch: Callable[[str], Any], resource_id: str,
                     interval: float = 2.0, timeout: float | None = None) -> Any:
        """Poll a persona repository until ``status`` is terminal. Terminal
        re-polling is free, so the confirming read costs nothing (spec/04)."""
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while time.monotonic() < deadline:
            resource = fetch(resource_id)
            if resource and resource.get("status") in ("succeeded", "failed"):
                return resource
            time.sleep(interval)
        raise TimeoutError(f"job {resource_id} did not reach a terminal status in time")


def grant_url_parts(opened: OpenThreadResponse) -> tuple[str, str]:
    """Split ``realtime.connect_url`` into its two base64url token segments.

    Raises ``ValueError`` unless the grant has exactly one ``token`` query
    parameter whose value is ``<payload>.<43-character signature>`` — the
    tested shape (spec/02 §WebSocket protocol).
    """
    from urllib.parse import parse_qs, urlsplit

    parts = urlsplit(opened["realtime"]["connect_url"])
    query = parse_qs(parts.query)
    if list(query) != ["token"] or len(query["token"]) != 1:
        raise ValueError(f"unexpected grant query parameters: {sorted(query)}")
    segments = query["token"][0].split(".")
    if len(segments) != 2 or len(segments[1]) != 43:
        raise ValueError("grant token is not <payload>.<43-char signature>")
    return segments[0], segments[1]
