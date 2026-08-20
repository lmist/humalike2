import crypto from "node:crypto";

export const BASE_URL = process.env.HUMALIKE_API_URL || "https://api.humalike.com";
export const API_KEY = process.env.HUMALIKE_API_KEY;

export function requireKey() {
  if (!API_KEY) throw new Error("HUMALIKE_API_KEY is required");
}

export function unique(prefix) {
  return `${prefix}-${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
}

// A connect timeout means the TCP connection was never established, so the
// request was never sent and retrying cannot double-bill or double-ingest.
// Anything else (reset mid-flight, HTTP errors) is surfaced unchanged.
export function isConnectTimeout(error) {
  let cause = error;
  for (let depth = 0; cause && depth < 4; depth += 1) {
    if (cause.code === "UND_ERR_CONNECT_TIMEOUT") return true;
    cause = cause.cause;
  }
  return false;
}

export async function fetchWithConnectRetry(url, init, attempts = 3) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await fetch(url, init);
    } catch (error) {
      if (!isConnectTimeout(error) || attempt >= attempts) throw error;
      console.error(`RETRY connect timeout on ${new URL(url).pathname} (attempt ${attempt}/${attempts})`);
      await new Promise((resolve) => setTimeout(resolve, 1000 * attempt));
    }
  }
}

export async function post(path, body = {}, options = {}) {
  const headers = {"content-type": "application/json", ...(options.headers || {})};
  if (options.auth !== false) headers.authorization = `Bearer ${API_KEY}`;
  if (options.authorization !== undefined) {
    if (options.authorization === null) delete headers.authorization;
    else headers.authorization = options.authorization;
  }
  const startedAt = new Date();
  const response = await fetchWithConnectRetry(`${BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(options.timeoutMs || 120_000),
  });
  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  return {
    status: response.status,
    headers: Object.fromEntries(response.headers.entries()),
    data,
    startedAt,
    endedAt: new Date(),
  };
}

export function componentMap(summary) {
  return Object.fromEntries(
    (summary?.per_component || []).map((row) => [
      row.component,
      {calls: row.calls, credits: row.credits},
    ]),
  );
}

export function usageDelta(before, after) {
  const left = componentMap(before);
  const right = componentMap(after);
  const names = new Set([...Object.keys(left), ...Object.keys(right)]);
  const per_component = [...names].sort().map((component) => ({
    component,
    calls: (right[component]?.calls || 0) - (left[component]?.calls || 0),
    credits: (right[component]?.credits || 0) - (left[component]?.credits || 0),
  })).filter((row) => row.calls || row.credits);
  return {
    total_calls: after.total_calls - before.total_calls,
    total_credits: after.total_credits - before.total_credits,
    per_component,
  };
}

export const paths = {
  usage: "/v1/credits/projections/usage-summary",
  whoami: "/v1/turn-taking/actions/whoami",
  open: "/v1/turn-taking/actions/open_thread",
  submit: "/v1/turn-taking/actions/submit_messages",
  respond: "/v1/turn-taking/actions/respond",
  event: "/v1/turn-taking/actions/record_event",
  ingest: "/v1/social-memory/actions/ingest",
  recall: "/v1/social-memory/actions/recall",
  ask: "/v1/social-memory/actions/ask",
};
