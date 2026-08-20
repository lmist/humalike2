/**
 * Humalike API recreation — JavaScript/TypeScript client.
 *
 * One method per endpoint in spec/03 and spec/04, bearer authentication on
 * every call, and `x-request-id` captured from every response (success and
 * error alike, since production sets it on both). Types come from
 * ./humalike.d.ts; this file is plain ESM so it runs under `node` with no
 * build step, and type-checks under `tsc --checkJs` from the JSDoc below.
 *
 * Phase map: clients/README.md.
 *
 *   import { HumalikeClient } from './client.mjs';
 *   const hum = new HumalikeClient();          // reads HUMALIKE_API_URL/KEY
 *   const { user_id } = await hum.whoami();
 *
 * @typedef {import('./humalike').WhoamiResponse} WhoamiResponse
 * @typedef {import('./humalike').UsageSummary} UsageSummary
 * @typedef {import('./humalike').OpenThreadRequest} OpenThreadRequest
 * @typedef {import('./humalike').OpenThreadResponse} OpenThreadResponse
 * @typedef {import('./humalike').SubmitRequest} SubmitRequest
 * @typedef {import('./humalike').SubmitResponse} SubmitResponse
 * @typedef {import('./humalike').RecordEventRequest} RecordEventRequest
 * @typedef {import('./humalike').RecordEventResponse} RecordEventResponse
 * @typedef {import('./humalike').RespondRequest} RespondRequest
 * @typedef {import('./humalike').RespondResponse} RespondResponse
 * @typedef {import('./humalike').IngestRequest} IngestRequest
 * @typedef {import('./humalike').IngestResponse} IngestResponse
 * @typedef {import('./humalike').RecallRequest} RecallRequest
 * @typedef {import('./humalike').RecallResponse} RecallResponse
 * @typedef {import('./humalike').AskRequest} AskRequest
 * @typedef {import('./humalike').AskResponse} AskResponse
 * @typedef {import('./humalike').ExtractRequest} ExtractRequest
 * @typedef {import('./humalike').ExtractResponse} ExtractResponse
 * @typedef {import('./humalike').ForeseeRequest} ForeseeRequest
 * @typedef {import('./humalike').ForeseeResponse} ForeseeResponse
 * @typedef {import('./humalike').AnalyzeRequest} AnalyzeRequest
 * @typedef {import('./humalike').AnalyzeResponse} AnalyzeResponse
 * @typedef {import('./humalike').ReportByIdResponse} ReportByIdResponse
 * @typedef {import('./humalike').AuditPrepareRequest} AuditPrepareRequest
 * @typedef {import('./humalike').AuditPrepareResponse} AuditPrepareResponse
 * @typedef {import('./humalike').AuditLaunchRequest} AuditLaunchRequest
 * @typedef {import('./humalike').AuditLaunchResponse} AuditLaunchResponse
 * @typedef {import('./humalike').AuditProjection} AuditProjection
 * @typedef {import('./humalike').GenerateRequest} GenerateRequest
 * @typedef {import('./humalike').JobAccepted} JobAccepted
 * @typedef {import('./humalike').PopulationResource} PopulationResource
 * @typedef {import('./humalike').EnhanceRequest} EnhanceRequest
 * @typedef {import('./humalike').EnhancementResource} EnhancementResource
 * @typedef {import('./humalike').ValidateRequest} ValidateRequest
 * @typedef {import('./humalike').EvaluationResource} EvaluationResource
 * @typedef {import('./humalike').HumalikeClientOptions} HumalikeClientOptions
 */

const DEFAULT_ORIGIN = 'https://api.humalike.com';

/** Non-2xx responses raise this; branch on `code`, never on message text. */
export class HumalikeApiError extends Error {
  /**
   * @param {number} status
   * @param {string | null} requestId
   * @param {unknown} body
   */
  constructor(status, requestId, body) {
    const code =
      body && typeof body === 'object' && body.error && typeof body.error === 'object'
        ? body.error.code ?? null
        : null;
    const message =
      body && typeof body === 'object' && body.error && typeof body.error === 'object'
        ? `${status} ${code}: ${body.error.message}`
        : `${status}`;
    super(message);
    this.name = 'HumalikeApiError';
    this.status = status;
    this.requestId = requestId;
    this.body = body;
    this.code = code;
  }
}

export class HumalikeClient {
  /** @param {HumalikeClientOptions} [options] */
  constructor(options = {}) {
    const env = typeof process === 'undefined' ? {} : process.env;
    this.baseUrl = (options.baseUrl ?? env.HUMALIKE_API_URL ?? DEFAULT_ORIGIN).replace(/\/+$/, '');
    this.apiKey = options.apiKey ?? env.HUMALIKE_API_KEY ?? '';
    // Population runs took about 52 s live and enhancement about 37 s, so the
    // default has to be minutes rather than seconds (spec/06 §Asynchronous).
    this.timeoutMs = options.timeoutMs ?? 300_000;
    this._fetch = options.fetch ?? globalThis.fetch;
    /** @type {string | null} `x-request-id` of the most recent response. */
    this.lastRequestId = null;
  }

  /**
   * @param {'GET'|'POST'} method
   * @param {string} path
   * @param {unknown} [body]
   * @param {Record<string,string>} [headers]
   * @returns {Promise<any>}
   */
  async request(method, path, body, headers = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let response;
    try {
      response = await this._fetch(`${this.baseUrl}${path}`, {
        method,
        headers: {
          // Every public route requires bearer auth (spec/02).
          authorization: `Bearer ${this.apiKey}`,
          ...(method === 'POST' ? { 'content-type': 'application/json' } : {}),
          ...headers,
        },
        body: method === 'POST' ? JSON.stringify(body ?? {}) : undefined,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
    this.lastRequestId = response.headers.get('x-request-id');
    const text = await response.text();
    let parsed = null;
    if (text.length > 0) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }
    if (!response.ok) {
      throw new HumalikeApiError(response.status, this.lastRequestId, parsed);
    }
    return parsed;
  }

  // ---- phase 1: identity and usage ---------------------------------------

  /** @returns {Promise<WhoamiResponse>} */
  whoami() {
    return this.request('POST', '/v1/turn-taking/actions/whoami', {});
  }

  /** @returns {Promise<UsageSummary>} */
  usageSummary() {
    return this.request('POST', '/v1/credits/projections/usage-summary', {});
  }

  // ---- phase 2: threads, grants ------------------------------------------

  /**
   * @param {OpenThreadRequest} [body]
   * @returns {Promise<OpenThreadResponse>}
   */
  openThread(body = {}) {
    return this.request('POST', '/v1/turn-taking/actions/open_thread', body);
  }

  // ---- phase 3: decisions, events, respond --------------------------------

  /**
   * @param {SubmitRequest} body
   * @returns {Promise<SubmitResponse>}
   */
  submitMessages(body) {
    return this.request('POST', '/v1/turn-taking/actions/submit_messages', body);
  }

  /**
   * @param {RecordEventRequest} body
   * @returns {Promise<RecordEventResponse>}
   */
  recordEvent(body) {
    return this.request('POST', '/v1/turn-taking/actions/record_event', body);
  }

  /**
   * A stale `turn_epoch` returns `{scheduled: [], superseded: true}` and is
   * not billed; it is a normal 200, not an error.
   * @param {RespondRequest} body
   * @returns {Promise<RespondResponse>}
   */
  respond(body) {
    return this.request('POST', '/v1/turn-taking/actions/respond', body);
  }

  // ---- phase 4: Social Memory --------------------------------------------

  /**
   * `Idempotency-Key` is owner-wide and first-write-wins: the same key sent
   * with a changed body or a different `scope_id` replays the first response
   * and stores nothing new (spec/02 §Idempotency).
   * @param {IngestRequest} body
   * @param {string} [idempotencyKey]
   * @returns {Promise<IngestResponse>}
   */
  ingest(body, idempotencyKey) {
    return this.request(
      'POST',
      '/v1/social-memory/actions/ingest',
      body,
      idempotencyKey ? { 'idempotency-key': idempotencyKey } : {},
    );
  }

  /**
   * @param {RecallRequest} body
   * @returns {Promise<RecallResponse>}
   */
  recall(body) {
    return this.request('POST', '/v1/social-memory/actions/recall', body);
  }

  /**
   * @param {AskRequest} body
   * @returns {Promise<AskResponse>}
   */
  ask(body) {
    return this.request('POST', '/v1/social-memory/actions/ask', body);
  }

  // ---- phase 5: Social Learning and foresee -------------------------------

  /**
   * @param {ExtractRequest} body
   * @returns {Promise<ExtractResponse>}
   */
  extract(body) {
    return this.request('POST', '/v1/social-learning/actions/extract', body);
  }

  /**
   * @param {ForeseeRequest} body
   * @returns {Promise<ForeseeResponse>}
   */
  foresee(body) {
    return this.request('POST', '/v1/foresee/actions/foresee', body);
  }

  // ---- phase 6: observability and audit -----------------------------------

  /**
   * Returns the report itself: no id, no Location, no x-report-id. There is no
   * public way back to the stored copy (spec/08 open question 1).
   * @param {AnalyzeRequest} body
   * @returns {Promise<AnalyzeResponse>}
   */
  analyze(body) {
    return this.request('POST', '/v1/social-observability/actions/analyze', body);
  }

  /**
   * @param {string} id
   * @returns {Promise<ReportByIdResponse>} `null` for a valid unknown UUID.
   */
  reportById(id) {
    return this.request(
      'GET', `/v1/social-observability/repositories/Report/by-id/${encodeURIComponent(id)}`);
  }

  /**
   * @param {AuditPrepareRequest} body
   * @returns {Promise<AuditPrepareResponse>}
   */
  auditPrepare(body) {
    return this.request('POST', '/v1/social-observability/actions/audit_prepare', body);
  }

  /**
   * First-write-wins: a repeat returns 200 and keeps the first `agent_name`.
   * @param {AuditLaunchRequest} body
   * @returns {Promise<AuditLaunchResponse>}
   */
  auditLaunch(body) {
    return this.request('POST', '/v1/social-observability/actions/audit_launch', body);
  }

  /**
   * @param {{run_id: string}} body
   * @returns {Promise<AuditProjection>}
   */
  auditRun(body) {
    return this.request('POST', '/v1/social-observability/projections/audit-run', body);
  }

  /**
   * Poll until `replies.length === verdicts.length` and the projection is
   * stable across two polls — the tested completion signal, since the
   * projection never exposes `status` or `stage`. Polling is free.
   * @param {string} runId
   * @param {{intervalMs?: number, timeoutMs?: number}} [options]
   * @returns {Promise<AuditProjection>}
   */
  async waitForAudit(runId, options = {}) {
    const intervalMs = options.intervalMs ?? 2_000;
    const deadline = Date.now() + (options.timeoutMs ?? this.timeoutMs);
    let previous = null;
    while (Date.now() < deadline) {
      const projection = await this.auditRun({ run_id: runId });
      const done =
        projection.verdicts !== null &&
        projection.replies.length === projection.verdicts.length;
      if (done && previous && JSON.stringify(previous) === JSON.stringify(projection)) {
        return projection;
      }
      previous = done ? projection : null;
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    throw new Error(`audit ${runId} did not complete within the timeout`);
  }

  // ---- phase 7: personas --------------------------------------------------

  /**
   * @param {GenerateRequest} body
   * @returns {Promise<JobAccepted>}
   */
  generatePersonas(body) {
    return this.request('POST', '/v1/personas/actions/generate', body);
  }

  /**
   * @param {string} id
   * @returns {Promise<PopulationResource | null>} `null` for a valid unknown UUID.
   */
  population(id) {
    return this.request(
      'GET', `/v1/personas/repositories/Population/by-id/${encodeURIComponent(id)}`);
  }

  /**
   * @param {EnhanceRequest} body
   * @returns {Promise<JobAccepted>}
   */
  enhancePersona(body) {
    return this.request('POST', '/v1/personas/actions/enhance', body);
  }

  /**
   * @param {string} id
   * @returns {Promise<EnhancementResource | null>}
   */
  enhancement(id) {
    return this.request(
      'GET', `/v1/personas/repositories/Enhancement/by-id/${encodeURIComponent(id)}`);
  }

  /**
   * @param {ValidateRequest} body
   * @returns {Promise<JobAccepted>}
   */
  validatePersonas(body) {
    return this.request('POST', '/v1/personas/actions/validate', body);
  }

  /**
   * @param {string} id
   * @returns {Promise<EvaluationResource | null>}
   */
  evaluation(id) {
    return this.request(
      'GET', `/v1/personas/repositories/Evaluation/by-id/${encodeURIComponent(id)}`);
  }

  /**
   * Poll a persona repository until `status` is terminal. Terminal re-polling
   * is free, so the extra confirming read costs nothing (spec/04).
   * @template {{status: string}} T
   * @param {(id: string) => Promise<T | null>} fetchResource
   * @param {string} id
   * @param {{intervalMs?: number, timeoutMs?: number}} [options]
   * @returns {Promise<T>}
   */
  async waitForJob(fetchResource, id, options = {}) {
    const intervalMs = options.intervalMs ?? 2_000;
    const deadline = Date.now() + (options.timeoutMs ?? this.timeoutMs);
    while (Date.now() < deadline) {
      const resource = await fetchResource.call(this, id);
      if (resource && (resource.status === 'succeeded' || resource.status === 'failed')) {
        return resource;
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    throw new Error(`job ${id} did not reach a terminal status within the timeout`);
  }
}

/**
 * Build the WSS URL for a thread grant. `open_thread` already returns a
 * complete `realtime.connect_url`; this only exists so callers can assert the
 * tested shape (exactly one `token` query parameter, two base64url segments)
 * before connecting.
 * @param {OpenThreadResponse} opened
 * @returns {URL}
 */
export function grantUrl(opened) {
  const url = new URL(opened.realtime.connect_url);
  const params = [...url.searchParams.keys()];
  if (params.length !== 1 || params[0] !== 'token') {
    throw new Error(`unexpected grant query parameters: ${params.join(',')}`);
  }
  const segments = (url.searchParams.get('token') ?? '').split('.');
  if (segments.length !== 2 || segments[1].length !== 43) {
    throw new Error('grant token is not <payload>.<43-char signature>');
  }
  return url;
}

export default HumalikeClient;
