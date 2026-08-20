import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import crypto from "node:crypto";
import {fileURLToPath} from "node:url";
import {WebSocket} from "ws";
import {
  BASE_URL,
  componentMap,
  paths,
  post,
  requireKey,
  unique,
  usageDelta,
} from "./client.mjs";

requireKey();

const ORIGIN = new URL(BASE_URL);
const WS_PROTOCOL = ORIGIN.protocol === "https:" ? "wss:" : "ws:";
const WS_PATH = "/v1/ws/turn-taking-thread";
// Production pacing model, pinned live: typing_i = min(max_typing_ms, max(TYPING_FLOOR_MS, words_i / typing_wpm * 60000)).
// First delivery = created_at + reading_delay_ms + typing_0; each later delivery = previous + 200 + typing_i.
const TYPING_FLOOR_MS = 500;
const DEFAULT_PACING = {readingDelayMs: 0, typingWpm: 150, maxTypingMs: 8000};

const results = [];
const responses = [];
const observations = {
  run_id: unique("realtime"),
  origin: ORIGIN.origin,
  headers: {},
  auth: {},
  validation: [],
  unknown_fields: {},
  limits: {},
  open_thread: {},
  decisions: [],
  events: [],
  respond: {},
  websocket: {frames: []},
  pacing_defaults: {},
  memory: {},
  billing: {},
};
let creditsDepleted = false;

function check(name, fn) {
  try {
    fn();
    results.push({name, pass: true});
    console.log(`PASS ${name}`);
    return true;
  } catch (error) {
    results.push({name, pass: false, error: error.message});
    console.error(`FAIL ${name}: ${error.message}`);
    return false;
  }
}

async function billable(label, fn) {
  if (creditsDepleted) {
    results.push({name: label, skip: true});
    console.log(`SKIP ${label}: billable block suppressed after HTTP 402`);
    return;
  }
  await fn();
}

function exactKeys(value, keys) {
  assert(value && typeof value === "object" && !Array.isArray(value), `expected object, got ${JSON.stringify(value)}`);
  assert.deepEqual(Object.keys(value).sort(), [...keys].sort());
}

// Production serializes every HTTP/event timestamp as UTC with microsecond precision and a literal Z.
function iso(value) {
  assert.equal(typeof value, "string");
  assert(!Number.isNaN(Date.parse(value)), `${value} is not ISO-like`);
  assert.match(value, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/, `${value} is not microsecond UTC Z`);
}

// The attached handshake alone serializes its clock with a +00:00 offset.
function isoOffset(value) {
  assert.equal(typeof value, "string");
  assert(!Number.isNaN(Date.parse(value)), `${value} is not ISO-like`);
  assert.match(value, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$/, `${value} is not microsecond +00:00`);
}

function uuid(value) {
  assert.match(value, /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
}

function wordCount(text) {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function assertWithinMs(actual, expected, tolerance = 10) {
  assert(
    Math.abs(actual - expected) <= tolerance,
    `expected ${actual}ms to be within ±${tolerance}ms of ${expected}ms`,
  );
}

function validationShape(response, expectedLoc, expectedType) {
  assert.equal(response.status, 422, JSON.stringify(response.data));
  exactKeys(response.data, ["error"]);
  exactKeys(response.data.error, ["code", "message", "details"]);
  assert.equal(response.data.error.code, "validation_failed");
  assert.equal(response.data.error.message, "request validation failed");
  assert(Array.isArray(response.data.error.details));
  assert(response.data.error.details.length >= 1);
  for (const item of response.data.error.details) {
    assert.notEqual(item.loc[0], "body", `loc must not be prefixed with "body": ${JSON.stringify(item.loc)}`);
  }
  const detail = response.data.error.details.find((item) =>
    JSON.stringify(item.loc) === JSON.stringify(expectedLoc),
  );
  assert(detail, `missing detail at ${JSON.stringify(expectedLoc)} in ${JSON.stringify(response.data.error.details)}`);
  exactKeys(detail, ["loc", "msg", "type"]);
  assert.equal(typeof detail.msg, "string");
  assert(detail.msg.length > 0);
  assert.equal(typeof detail.type, "string");
  if (expectedType) assert.equal(detail.type, expectedType);
  return detail;
}

function unauthorizedShape(response) {
  assert.equal(response.status, 401);
  assert.deepEqual(response.data, {
    error: {code: "UNAUTHORIZED", message: "missing or invalid credentials"},
  });
}

async function api(path, body, options = {}, label = path) {
  const response = await post(path, body, options);
  if (response.status === 402) creditsDepleted = true;
  responses.push({label, path, status: response.status, headers: response.headers});
  return response;
}

async function usage() {
  const response = await api(paths.usage, {}, {}, "usage-summary");
  assert.equal(response.status, 200, JSON.stringify(response.data));
  return response;
}

function usageSchema(body) {
  exactKeys(body, ["total_calls", "total_credits", "per_component", "daily_series"]);
  assert(Number.isInteger(body.total_calls) && body.total_calls >= 0);
  assert(Number.isInteger(body.total_credits) && body.total_credits >= 0);
  assert(Array.isArray(body.per_component));
  for (const row of body.per_component) {
    exactKeys(row, ["component", "calls", "credits"]);
    assert.equal(typeof row.component, "string");
    assert(Number.isInteger(row.calls) && row.calls >= 0);
    assert(Number.isInteger(row.credits) && row.credits >= 0);
  }
  assert.equal(body.daily_series.length, 7);
  for (const row of body.daily_series) {
    exactKeys(row, ["date", "requests"]);
    assert.match(row.date, /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)$/);
    assert(Number.isInteger(row.requests) && row.requests >= 0);
  }
}

function errorSnapshot(response) {
  return {status: response.status, body: response.data, headers: response.headers};
}

function grantQueryKey(connectUrl) {
  return [...new URL(connectUrl).searchParams.keys()][0];
}

function openSchema(body) {
  exactKeys(body, ["thread", "channel", "realtime"]);
  exactKeys(body.thread, ["id", "user_id", "created_at", "updated_at"]);
  uuid(body.thread.id);
  assert.equal(typeof body.thread.user_id, "string");
  assert(body.thread.user_id.length > 0);
  iso(body.thread.created_at);
  iso(body.thread.updated_at);
  assert.equal(body.channel, `turn-taking-thread/${body.thread.id}`);
  exactKeys(body.realtime, ["connect_url", "expires_at"]);
  const url = new URL(body.realtime.connect_url);
  assert.equal(url.protocol, WS_PROTOCOL);
  assert.equal(url.host, ORIGIN.host);
  assert.equal(url.pathname, WS_PATH);
  const keys = [...url.searchParams.keys()];
  assert.deepEqual(keys, ["token"], `grant query keys ${JSON.stringify(keys)}`);
  assert(url.searchParams.get("token").length > 0);
  iso(body.realtime.expires_at);
}

function submitSchema(body) {
  exactKeys(body, ["decision", "turn_epoch", "tags", "recalled_context"]);
  assert(["speak", "stay_silent"].includes(body.decision));
  assert(Number.isInteger(body.turn_epoch) && body.turn_epoch >= 1);
  assert(Array.isArray(body.tags) && body.tags.every((tag) => typeof tag === "string"));
  assert.equal(typeof body.recalled_context, "string");
}

function eventSchema(body) {
  assert.deepEqual(body, {tags: []});
}

function scheduledSchema(body, threadId) {
  exactKeys(body, ["scheduled", "superseded"]);
  assert.equal(body.superseded, false);
  assert(body.scheduled.length >= 1 && body.scheduled.length <= 5, `scheduled length ${body.scheduled.length}`);
  body.scheduled.forEach((item, position) => {
    exactKeys(item, [
      "id", "thread_id", "content", "position", "deliver_at", "status",
      "created_at", "updated_at",
    ]);
    uuid(item.id);
    assert.equal(item.thread_id, threadId);
    assert.equal(typeof item.content, "string");
    assert(item.content.length > 0);
    assert.equal(item.position, position);
    iso(item.deliver_at);
    iso(item.created_at);
    iso(item.updated_at);
    assert.equal(item.status, "scheduled");
  });
  const createdTimes = body.scheduled.map((item) => item.created_at);
  for (let i = 1; i < createdTimes.length; i++) {
    assert(createdTimes[i] >= createdTimes[i - 1], `created_at not monotone: ${createdTimes}`);
  }
  const createdSpread = Date.parse(createdTimes[createdTimes.length - 1]) - Date.parse(createdTimes[0]);
  assert(createdSpread <= 5, `created_at spread ${createdSpread}ms across entries`);
  body.scheduled.forEach((item) => assert.equal(item.updated_at, item.created_at));
  const deliverTimes = body.scheduled.map((item) => Date.parse(item.deliver_at));
  for (let i = 1; i < deliverTimes.length; i++) assert(deliverTimes[i] > deliverTimes[i - 1]);
}

function typingMs(words, {typingWpm, maxTypingMs, floorMs = TYPING_FLOOR_MS}) {
  return Math.min(maxTypingMs, Math.max(floorMs, words / typingWpm * 60_000));
}

function pacingFit(scheduled, {readingDelayMs, typingWpm, maxTypingMs, floorMs = TYPING_FLOOR_MS}, tolerance = 10) {
  const deliverTimes = scheduled.map((item) => Date.parse(item.deliver_at));
  const created = Date.parse(scheduled[0].created_at);
  const typing = scheduled.map((item) => typingMs(wordCount(item.content), {typingWpm, maxTypingMs, floorMs}));
  assertWithinMs(deliverTimes[0] - created, readingDelayMs + typing[0], tolerance);
  for (let i = 1; i < deliverTimes.length; i++) {
    assertWithinMs(deliverTimes[i] - deliverTimes[i - 1], 200 + typing[i], tolerance);
  }
}

function redactWsUrl(value) {
  const url = new URL(value);
  const key = grantQueryKey(value) || "token";
  return `${url.origin}${url.pathname}?${key}=[REDACTED]`;
}

function connectAndCapture(url) {
  const frames = [];
  const arrivals = [];
  const socket = new WebSocket(url);
  socket.on("message", (raw) => {
    try {
      const frame = JSON.parse(raw.toString());
      frames.push(frame);
      arrivals.push({frame, received_at: new Date().toISOString()});
    } catch {
      frames.push({non_json: raw.toString()});
    }
  });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("WebSocket open timed out")), 10_000);
    socket.once("open", () => {
      clearTimeout(timer);
      resolve({socket, frames, arrivals});
    });
    socket.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
}

async function waitFor(predicate, timeoutMs, label) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(`timed out waiting for ${label}`);
}

function frameSequence(frames, threadId, channel, expectedMessages) {
  assert.equal(frames.length, expectedMessages + 3, `frame types: ${frames.map((frame) => frame.type).join(",")}`);
  const [attached, typingOn] = frames;
  exactKeys(attached, ["type", "channel", "server_time"]);
  assert.equal(attached.type, "attached");
  assert.equal(attached.channel, channel);
  isoOffset(attached.server_time);
  for (const frame of frames.slice(1)) {
    exactKeys(frame, ["id", "type", "channel", "ts", "data"]);
    assert.match(frame.id, /^evt_[0-9a-f]{32}$/, `event id ${frame.id}`);
    assert.equal(frame.channel, channel);
    iso(frame.ts);
  }
  assert.equal(typingOn.type, "turn_taking.typing");
  assert.deepEqual(typingOn.data, {thread_id: threadId, typing: true});
  const typingOff = frames[frames.length - 1];
  assert.equal(typingOff.type, "turn_taking.typing");
  assert.deepEqual(typingOff.data, {thread_id: threadId, typing: false});
  const messages = frames.slice(2, -1);
  messages.forEach((frame, position) => {
    assert.equal(frame.type, "turn_taking.message");
    exactKeys(frame.data, ["message_id", "thread_id", "content", "position", "sent_at", "metadata"]);
    assert.equal(frame.data.thread_id, threadId);
    assert.equal(frame.data.position, position);
    assert.equal(typeof frame.data.content, "string");
    iso(frame.data.sent_at);
    uuid(frame.data.message_id);
  });
  return messages;
}

function deliveryDeltas(frames, arrivals, scheduled) {
  const messageFrames = frames.filter((frame) => frame.type === "turn_taking.message");
  const messageArrivals = arrivals.filter(({frame}) => frame.type === "turn_taking.message");
  return scheduled.map((item, position) => {
    const deliverAt = Date.parse(item.deliver_at);
    return {
      position,
      sent_at_minus_deliver_at_ms: Date.parse(messageFrames[position].data.sent_at) - deliverAt,
      ts_minus_deliver_at_ms: Date.parse(messageFrames[position].ts) - deliverAt,
      received_minus_deliver_at_ms: Date.parse(messageArrivals[position].received_at) - deliverAt,
    };
  });
}

function runDriver(threadId) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [fileURLToPath(new URL("./ws-driver.mjs", import.meta.url))], {
      env: {
        ...process.env,
        HUMALIKE_TEST_THREAD_ID: threadId,
        HUMALIKE_TEST_RUN_ID: observations.run_id,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) return reject(new Error(`driver exited ${code}: ${stderr}`));
      try {
        resolve(JSON.parse(stdout.trim()));
      } catch (error) {
        reject(new Error(`driver returned invalid JSON: ${error.message}; ${stdout}; ${stderr}`));
      }
    });
  });
}

async function lateConnect(url) {
  return new Promise((resolve) => {
    const socket = new WebSocket(url);
    const outcome = {opened: false, status: null, body: null, error: null, close: null};
    const timer = setTimeout(() => {
      socket.terminate();
      outcome.error = "timeout";
      resolve(outcome);
    }, 10_000);
    socket.once("open", () => {
      outcome.opened = true;
    });
    socket.once("unexpected-response", (_request, response) => {
      outcome.status = response.statusCode;
      let body = "";
      response.on("data", (chunk) => { body += chunk; });
      response.on("end", () => {
        outcome.body = body;
        clearTimeout(timer);
        resolve(outcome);
      });
    });
    socket.once("error", (error) => { outcome.error = error.message; });
    socket.once("close", (code, reason) => {
      outcome.close = {code, reason: reason.toString()};
      clearTimeout(timer);
      resolve(outcome);
    });
  });
}

// Opens a thread, attaches N sockets, submits one free batch, responds, and waits for delivery.
async function respondOverSockets({label, openBody = {}, inbound, respond, socketCount = 1, deliveryTimeoutMs = 120_000}) {
  const open = await api(paths.open, openBody, {}, `${label} open`);
  assert.equal(open.status, 200, JSON.stringify(open.data));
  const threadId = open.data.thread.id;
  const grants = [open];
  for (let i = 1; i < socketCount; i++) {
    const reopened = await api(paths.open, {thread_id: threadId}, {}, `${label} reopen`);
    assert.equal(reopened.status, 200, JSON.stringify(reopened.data));
    grants.push(reopened);
  }
  const connections = [];
  for (const grant of grants) {
    const connection = await connectAndCapture(grant.data.realtime.connect_url);
    await waitFor(() => connection.frames.some((frame) => frame.type === "attached"), 5_000, `${label} attached`);
    connections.push(connection);
  }
  const submitted = await api(paths.submit, {
    thread_id: threadId,
    messages: [inbound],
    skip_decide: true,
  }, {}, `${label} submit`);
  assert.equal(submitted.status, 200, JSON.stringify(submitted.data));
  const responded = await api(paths.respond, {
    thread_id: threadId,
    turn_epoch: submitted.data.turn_epoch,
    ...respond,
  }, {}, `${label} respond`);
  let delivered = false;
  if (responded.status === 200 && responded.data.scheduled?.length) {
    const expected = responded.data.scheduled.length;
    try {
      await waitFor(
        () => connections.every((connection) =>
          connection.frames.filter((frame) => frame.type === "turn_taking.message").length >= expected &&
          connection.frames.some((frame) => frame.type === "turn_taking.typing" && frame.data?.typing === false)),
        deliveryTimeoutMs,
        `${label} delivery`,
      );
      delivered = true;
    } catch (error) {
      console.error(`WARN ${label}: ${error.message}`);
    }
  }
  await new Promise((resolve) => setTimeout(resolve, 300));
  for (const connection of connections) connection.socket.close();
  return {open, grants, connections, submitted, responded, threadId, delivered};
}

console.log(`Live Humalike realtime test run ${observations.run_id} against ${ORIGIN.origin}`);

// The first authenticated call is deliberately the baseline usage projection.
const usageStartResponse = await usage();
const usageStart = usageStartResponse.data;
observations.billing.start = usageStart;
observations.headers.sample = usageStartResponse.headers;
observations.headers.server = {
  server: usageStartResponse.headers.server ?? null,
  via: usageStartResponse.headers.via ?? null,
};
check("usage-summary: exact schema", () => usageSchema(usageStart));

const whoami = await api(paths.whoami, {}, {}, "whoami");
check("whoami: 200 exact schema", () => {
  assert.equal(whoami.status, 200);
  exactKeys(whoami.data, ["user_id"]);
  assert.equal(typeof whoami.data.user_id, "string");
  assert(whoami.data.user_id.length > 0);
});

for (const [label, options] of [
  ["missing bearer", {auth: false}],
  ["malformed bearer", {authorization: "Basic nope"}],
  ["empty bearer", {authorization: "Bearer"}],
  ["invalid bearer", {authorization: "Bearer ak_live_test_invalid"}],
]) {
  const response = await api(paths.whoami, {}, options, `401 ${label}`);
  observations.auth[label] = errorSnapshot(response);
  check(`auth: ${label} exact 401`, () => unauthorizedShape(response));
}

for (const [name, path] of Object.entries(paths)) {
  const response = await api(path, {}, {auth: false}, `401 missing bearer ${name}`);
  check(`auth: ${name} without bearer is exact 401`, () => unauthorizedShape(response));
}

const invalidUuid = await api(paths.open, {thread_id: "not-a-uuid"}, {}, "validation invalid uuid");
observations.validation.push({case: "invalid UUID", ...errorSnapshot(invalidUuid)});
check("validation: lowercase envelope and uuid_parsing detail", () => validationShape(invalidUuid, ["thread_id"], "uuid_parsing"));

const bankA = unique("bank-a");
const bankB = unique("bank-b");
const opened = await api(paths.open, {
  integrations: {
    social_signals: {channel_id: unique("signals")},
    social_memory: {memory_bank_id: bankA},
  },
}, {}, "open create");
check("open_thread: create schema and grant anatomy", () => {
  assert.equal(opened.status, 200);
  openSchema(opened.data);
});
const threadId = opened.data.thread.id;
observations.open_thread.create = {
  ...opened.data,
  realtime: {...opened.data.realtime, connect_url: redactWsUrl(opened.data.realtime.connect_url)},
};
const grantToken = new URL(opened.data.realtime.connect_url).searchParams.get("token") || "";
observations.open_thread.grant = {
  query_key: grantQueryKey(opened.data.realtime.connect_url),
  token_length: grantToken.length,
  token_segments: grantToken.split(".").length,
  token_segment_lengths: grantToken.split(".").map((segment) => segment.length),
  token_charset: [
    /[A-Z]/.test(grantToken) && "upper", /[a-z]/.test(grantToken) && "lower", /[0-9]/.test(grantToken) && "digit",
    /-/.test(grantToken) && "dash", /_/.test(grantToken) && "underscore", /\./.test(grantToken) && "dot",
    /=/.test(grantToken) && "equals", /%/.test(grantToken) && "percent", /[^A-Za-z0-9._=%-]/.test(grantToken) && "other",
  ].filter(Boolean),
  token_shape: /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(grantToken)
    ? "jwt-like"
    : /^[A-Za-z0-9_-]+$/.test(grantToken) ? "opaque-urlsafe" : "other",
  expires_at_has_fraction: /\.\d+/.test(opened.data.realtime.expires_at),
  expires_at_format: opened.data.realtime.expires_at.replace(/\d/g, "9"),
  create_ttl_ms: Date.parse(opened.data.realtime.expires_at) - opened.endedAt.getTime(),
};
check("open_thread: grant token is <payload>.<signature> base64url with a 43-char signature", () => {
  const segments = grantToken.split(".");
  assert.equal(segments.length, 2, `segments ${segments.length}`);
  for (const segment of segments) assert.match(segment, /^[A-Za-z0-9_-]+$/);
  assert.equal(segments[1].length, 43);
  assert(segments[0].length > 43);
});
check("open_thread: grant lifetime is about 30 seconds", () => {
  const ttl = observations.open_thread.grant.create_ttl_ms;
  assert(ttl >= 25_000 && ttl <= 35_000, `ttl ${ttl}ms`);
});

await new Promise((resolve) => setTimeout(resolve, 30));
const reopenedSet = await api(paths.open, {
  thread_id: threadId,
  integrations: {social_memory: {memory_bank_id: bankB}},
}, {}, "open reopen set");
check("open_thread: reopen same id, rotate grant, advance updated_at", () => {
  assert.equal(reopenedSet.status, 200);
  openSchema(reopenedSet.data);
  assert.equal(reopenedSet.data.thread.id, threadId);
  assert.equal(reopenedSet.data.thread.created_at, opened.data.thread.created_at);
  assert.notEqual(reopenedSet.data.realtime.connect_url, opened.data.realtime.connect_url);
  assert(Date.parse(reopenedSet.data.realtime.expires_at) > Date.parse(opened.data.realtime.expires_at));
  assert(
    Date.parse(reopenedSet.data.thread.updated_at) > Date.parse(opened.data.thread.updated_at),
    `updated_at ${opened.data.thread.updated_at} -> ${reopenedSet.data.thread.updated_at}`,
  );
});
const reopenedPreserve = await api(paths.open, {thread_id: threadId}, {}, "open reopen preserve");
check("open_thread: omission preserves callable thread", () => {
  assert.equal(reopenedPreserve.status, 200);
  openSchema(reopenedPreserve.data);
  assert.equal(reopenedPreserve.data.thread.id, threadId);
  assert.notEqual(reopenedPreserve.data.realtime.connect_url, reopenedSet.data.realtime.connect_url);
});
observations.open_thread.reopen = {
  id_same: reopenedSet.data.thread.id === threadId,
  grant_rotated: reopenedSet.data.realtime.connect_url !== opened.data.realtime.connect_url,
  updated_at: [opened.data.thread.updated_at, reopenedSet.data.thread.updated_at, reopenedPreserve.data.thread.updated_at],
  path: new URL(opened.data.realtime.connect_url).pathname,
  query_keys: [...new URL(opened.data.realtime.connect_url).searchParams.keys()],
};

const emptyMessages = await api(paths.submit, {thread_id: threadId, messages: []}, {}, "validation empty messages");
const tooManyMessages = await api(paths.submit, {
  thread_id: threadId,
  messages: Array.from({length: 21}, (_, i) => ({sender: `u${i}`, content: "x"})),
}, {}, "validation 21 messages");
const tooLongContent = await api(paths.submit, {
  thread_id: threadId,
  messages: [{sender: "u", content: "x".repeat(4001)}],
}, {}, "validation content 4001");
const tooLongSender = await api(paths.submit, {
  thread_id: threadId,
  messages: [{sender: "s".repeat(256), content: "x"}],
}, {}, "validation sender 256");
for (const [label, response, loc, type] of [
  ["empty messages", emptyMessages, ["messages"], "too_short"],
  ["21 messages", tooManyMessages, ["messages"], "too_long"],
  ["content >4000", tooLongContent, ["messages", 0, "content"], "string_too_long"],
  ["sender >255", tooLongSender, ["messages", 0, "sender"], "string_too_long"],
]) {
  observations.validation.push({case: label, ...errorSnapshot(response)});
  check(`validation: ${label} (${type})`, () => validationShape(response, loc, type));
}

// Fresh thread: events do not advance the epoch; accept-side limits are honored; unknown fields.
const limitsOpen = await api(paths.open, {}, {}, "limits open");
const limitsThread = limitsOpen.data.thread.id;
for (const type of ["typing_start", "typing_stop", "message_edited"]) {
  await api(paths.event, {thread_id: limitsThread, type, sender: "Limits Human"}, {}, `limits event ${type}`);
}
const firstSubmit = await api(paths.submit, {
  thread_id: limitsThread,
  messages: [{sender: "Limits Human", content: "first batch after three events"}],
  skip_decide: true,
}, {}, "limits first submit");
check("submit: fresh thread starts at epoch 1 and record_event does not advance it", () => {
  assert.equal(firstSubmit.status, 200);
  submitSchema(firstSubmit.data);
  assert.equal(firstSubmit.data.turn_epoch, 1);
});
const twentyMessages = await api(paths.submit, {
  thread_id: limitsThread,
  messages: Array.from({length: 20}, (_, i) => ({sender: `u${i}`, content: `message ${i}`})),
  skip_decide: true,
}, {}, "limits 20 messages");
const sender255 = await api(paths.submit, {
  thread_id: limitsThread,
  messages: [{sender: "s".repeat(255), content: "x"}],
  skip_decide: true,
}, {}, "limits sender 255");
const content4000 = await api(paths.submit, {
  thread_id: limitsThread,
  messages: [{sender: "u", content: "x".repeat(4000)}],
  skip_decide: true,
}, {}, "limits content 4000");
check("submit: 20 messages, 255-char sender, and 4000-char content are accepted", () => {
  for (const [response, epoch] of [[twentyMessages, 2], [sender255, 3], [content4000, 4]]) {
    assert.equal(response.status, 200, JSON.stringify(response.data));
    submitSchema(response.data);
    assert.equal(response.data.decision, "speak");
    assert.equal(response.data.turn_epoch, epoch);
  }
});
observations.limits = {
  first_epoch: firstSubmit.data?.turn_epoch,
  twenty: {status: twentyMessages.status, epoch: twentyMessages.data?.turn_epoch},
  sender_255: {status: sender255.status, epoch: sender255.data?.turn_epoch},
  content_4000: {status: content4000.status, epoch: content4000.data?.turn_epoch},
};

const unknownOpen = await api(paths.open, {thread_id: limitsThread, bogus: 1}, {}, "unknown field open");
const unknownSubmit = await api(paths.submit, {
  thread_id: limitsThread,
  messages: [{sender: "Limits Human", content: "unknown field probe", extra_field: true}],
  skip_decide: true,
  bogus: 1,
}, {}, "unknown field submit");
const unknownEventField = await api(paths.event, {
  thread_id: limitsThread,
  type: "typing_start",
  sender: "Limits Human",
  bogus: 1,
}, {}, "unknown field event");
const unknownScope = unique("unknown-field");
const unknownIngest = await api(paths.ingest, {
  scope_id: unknownScope,
  transcript: [{speaker: "Probe", text: "unknown field probe"}],
  bogus: 1,
}, {}, "unknown field ingest");
observations.unknown_fields = {
  open_thread: errorSnapshot(unknownOpen),
  submit_messages: errorSnapshot(unknownSubmit),
  record_event: errorSnapshot(unknownEventField),
  ingest: errorSnapshot(unknownIngest),
};
check("unknown fields: top-level and nested extras are silently ignored on every probed route", () => {
  assert.equal(unknownOpen.status, 200, JSON.stringify(unknownOpen.data));
  openSchema(unknownOpen.data);
  assert.equal(unknownOpen.data.thread.id, limitsThread);
  assert.equal(unknownSubmit.status, 200, JSON.stringify(unknownSubmit.data));
  submitSchema(unknownSubmit.data);
  assert.equal(unknownSubmit.data.turn_epoch, 5);
  assert.equal(unknownEventField.status, 200, JSON.stringify(unknownEventField.data));
  eventSchema(unknownEventField.data);
  assert.equal(unknownIngest.status, 200, JSON.stringify(unknownIngest.data));
  assert.deepEqual(unknownIngest.data, {ingested: 1});
});

const noIntegrationOpen = await api(paths.open, {}, {}, "no-integration open");
const noIntegrationSubmit = await api(paths.submit, {
  thread_id: noIntegrationOpen.data.thread.id,
  messages: [{sender: "Human", content: "short circuit without integrations"}],
  skip_decide: true,
}, {}, "no-integration submit");
check("submit: skip_decide short-circuits and no integrations are empty", () => {
  assert.equal(noIntegrationSubmit.status, 200);
  submitSchema(noIntegrationSubmit.data);
  assert.equal(noIntegrationSubmit.data.decision, "speak");
  assert.deepEqual(noIntegrationSubmit.data.tags, []);
  assert.equal(noIntegrationSubmit.data.recalled_context, "");
  assert.equal(noIntegrationSubmit.data.turn_epoch, 1);
});

const skip = await api(paths.submit, {
  thread_id: threadId,
  messages: [{sender: "Human", content: "first short-circuit batch"}],
  skip_decide: true,
}, {}, "submit skip_decide");
const media = await api(paths.submit, {
  thread_id: threadId,
  messages: [{sender: "Human", content: "[image]", has_media: true}],
}, {}, "submit has_media");
check("submit: skip_decide and media each advance exactly one epoch", () => {
  submitSchema(skip.data);
  submitSchema(media.data);
  assert.equal(skip.data.decision, "speak");
  assert.equal(media.data.decision, "speak");
  assert.equal(skip.data.turn_epoch, 1);
  assert.equal(media.data.turn_epoch, 2);
});
observations.decisions.push({kind: "skip_decide", ...skip.data}, {kind: "has_media", ...media.data});

await billable("submit: modeled decisions (direct address + five silence trials)", async () => {
  const modeledSpeak = await api(paths.submit, {
    thread_id: threadId,
    messages: [{
      sender: "Human",
      content: "Live Test Agent, please answer me directly: are you available?",
    }],
    system_prompt: "You are Live Test Agent. Speak when directly addressed. Stay silent during unrelated side chatter.",
  }, {}, "submit modeled speak");
  check("submit: modeled direct-address decision schema", () => {
    assert.equal(modeledSpeak.status, 200);
    submitSchema(modeledSpeak.data);
    assert.equal(modeledSpeak.data.decision, "speak");
    assert.equal(modeledSpeak.data.turn_epoch, media.data.turn_epoch + 1);
  });
  observations.decisions.push({kind: "modeled_direct_address", ...modeledSpeak.data});

  const silenceAttempts = [
    {sender: "Alice", content: "Bob, are you still joining lunch at noon?"},
    {sender: "Bob", content: "Alice, yes—I'll meet you by the front desk."},
    {sender: "Carol", content: "@someone-else can you answer the deployment question?"},
    {sender: "Dave", content: "ok thanks"},
    {sender: "Eve", content: "Frank, this is between us; please reply when you see it."},
  ];
  const silenceResults = [];
  for (const [index, message] of silenceAttempts.entries()) {
    const response = await api(paths.submit, {
      thread_id: threadId,
      messages: [message],
      system_prompt: "You are a lurker in a multi-human group chat. Only speak when the message explicitly addresses Live Test Agent. Stay silent for acknowledgments and messages addressed to any other named human.",
    }, {}, `submit silence ${index + 1}`);
    silenceResults.push(response);
    observations.decisions.push({
      kind: `modeled_silence_attempt_${index + 1}`,
      request: message,
      ...response.data,
    });
  }
  check("submit: five engineered silence decisions have valid schemas and consecutive epochs", () => {
    assert.equal(silenceResults.length, 5);
    silenceResults.forEach((response, index) => {
      assert.equal(response.status, 200);
      submitSchema(response.data);
      assert.equal(response.data.turn_epoch, modeledSpeak.data.turn_epoch + index + 1);
      assert.deepEqual(response.data.tags, []);
    });
  });
  observations.decisions.push({
    kind: "stay_silent_induction_result",
    induced: silenceResults.some((response) => response.data.decision === "stay_silent"),
    attempts: silenceResults.length,
    outcomes: silenceResults.map((response) => response.data.decision),
  });
});

for (const type of ["typing_start", "typing_stop", "message_edited"]) {
  const response = await api(paths.event, {
    thread_id: threadId,
    type,
    sender: "Human",
    client_ts: new Date().toISOString(),
  }, {}, `event ${type}`);
  observations.events.push({type, status: response.status, body: response.data});
  check(`record_event: ${type} returns exactly {tags:[]}`, () => {
    assert.equal(response.status, 200);
    eventSchema(response.data);
  });
}
const unknownEvent = await api(paths.event, {
  thread_id: threadId,
  type: "unknown_event",
  sender: "Human",
}, {}, "validation unknown event");
observations.validation.push({case: "unknown event", ...errorSnapshot(unknownEvent)});
check("record_event: unknown type is literal_error", () => validationShape(unknownEvent, ["type"], "literal_error"));

// Seed both banks, proving reopen-with-integrations changes the bank and omission keeps it.
const seedA = `ALPHA-${crypto.randomInt(100000, 999999)}`;
const seedB = `BRAVO-${crypto.randomInt(100000, 999999)}`;
const seedIngestA = await api(paths.ingest, {
  scope_id: bankA,
  transcript: [{speaker: "Priya", text: `Priya's verification code is ${seedA}.`}],
}, {headers: {"idempotency-key": crypto.randomUUID()}}, "ingest bank A");
const seedIngestB = await api(paths.ingest, {
  scope_id: bankB,
  transcript: [{speaker: "Priya", text: `Priya's verification code is ${seedB}.`}],
}, {}, "ingest bank B (no idempotency key)");
check("social-memory ingest: with and without Idempotency-Key both return the batch count", () => {
  assert.equal(seedIngestA.status, 200);
  assert.deepEqual(seedIngestA.data, {ingested: 1});
  assert.equal(seedIngestB.status, 200);
  assert.deepEqual(seedIngestB.data, {ingested: 1});
});
const integrated = await api(paths.submit, {
  thread_id: threadId,
  messages: [{sender: "Priya", content: "What is my verification code?"}],
  skip_decide: true,
}, {}, "submit integrated recall");
check("open_thread integrations: set then preserve social-memory bank", () => {
  assert.equal(integrated.status, 200);
  submitSchema(integrated.data);
  assert(integrated.data.recalled_context.includes(seedB), integrated.data.recalled_context);
  assert(!integrated.data.recalled_context.includes(seedA), integrated.data.recalled_context);
});
observations.open_thread.integration_recall = integrated.data.recalled_context;

await billable("respond: explicit pacing + stale epoch", async () => {
  const replyEpoch = integrated.data.turn_epoch;
  const draft = "Absolutely. First, I can confirm the requested code. Second, I can help with the next verification step.";
  const normal = await api(paths.respond, {
    thread_id: threadId,
    content: draft,
    turn_epoch: replyEpoch,
    agent_name: "Live Test Agent",
    system_prompt: "Be concise and friendly. Keep distinct steps as short chat bubbles.",
    pacing: {reading_delay_ms: 500, typing_wpm: 120, max_typing_ms: 1500},
    metadata: {opaque: "round-trip", nested: {value: 7}},
  }, {}, "respond normal");
  check("respond: scheduled schema, status literal, shared created_at, ordered delivery", () => {
    assert.equal(normal.status, 200, JSON.stringify(normal.data));
    scheduledSchema(normal.data, threadId);
  });
  check("respond: explicit pacing math includes 200ms inter-bubble gap", () => {
    pacingFit(normal.data.scheduled, {readingDelayMs: 500, typingWpm: 120, maxTypingMs: 1500});
  });
  const deliverTimes = normal.data.scheduled.map((item) => Date.parse(item.deliver_at));
  observations.respond.normal = {
    request_content: draft,
    response: normal.data,
    spacing_ms: deliverTimes.slice(1).map((time, i) => time - deliverTimes[i]),
    first_deliver_offset_from_created_ms: deliverTimes[0] - Date.parse(normal.data.scheduled[0].created_at),
    first_deliver_offset_from_response_start_ms: deliverTimes[0] - normal.startedAt.getTime(),
    response_latency_ms: normal.endedAt.getTime() - normal.startedAt.getTime(),
    created_at_minus_request_start_ms: Date.parse(normal.data.scheduled[0].created_at) - normal.startedAt.getTime(),
  };

  const newer = await api(paths.submit, {
    thread_id: threadId,
    messages: [{sender: "Human", content: "Interrupt the previous draft."}],
    skip_decide: true,
  }, {}, "submit newer");
  const beforeStale = (await usage()).data;
  const stale = await api(paths.respond, {
    thread_id: threadId,
    content: "This stale draft must not be delivered.",
    turn_epoch: replyEpoch,
  }, {}, "respond stale");
  const afterStale = (await usage()).data;
  const staleDelta = usageDelta(beforeStale, afterStale);
  check("respond: stale epoch is superseded with empty schedule", () => {
    assert.equal(newer.data.turn_epoch, replyEpoch + 1);
    assert.equal(stale.status, 200);
    assert.deepEqual(stale.data, {scheduled: [], superseded: true});
  });
  check("respond: stale path captured no turn-taking/theoryofmind billing", () => {
    const affected = staleDelta.per_component.filter((row) =>
      /turn|theoryofmind/i.test(row.component),
    );
    assert.deepEqual(affected, []);
  });
  observations.respond.stale = {response: stale.data, usage_delta: staleDelta};
});

// WebSocket catalog: attach, drive HTTP from a separate Node process, and correlate frames.
await billable("websocket: signals thread, driver reply, expiry, reconnect", async () => {
  const signalScope = unique("signal-scope");
  const wsOpen = await api(paths.open, {
    integrations: {social_signals: {scope_id: signalScope}},
  }, {}, "ws open");
  const wsThread = wsOpen.data.thread.id;
  const beforeAttachEvent = await api(paths.event, {
    thread_id: wsThread,
    type: "message_edited",
    sender: "Before Attach Human",
    client_ts: new Date().toISOString(),
  }, {}, "ws event before attach");
  check("signals: event before WebSocket attachment returns exactly {tags:[]}", () => {
    assert.equal(beforeAttachEvent.status, 200);
    eventSchema(beforeAttachEvent.data);
  });
  const {socket, frames, arrivals} = await connectAndCapture(wsOpen.data.realtime.connect_url);
  await waitFor(() => frames.some((frame) => frame.type === "attached"), 5_000, "attached frame");
  const attachedEventResults = [];
  for (const [type, sender] of [
    ["typing_start", "Attached Alice"],
    ["typing_stop", "Attached Alice"],
    ["message_edited", "Attached Bob"],
  ]) {
    attachedEventResults.push(await api(paths.event, {
      thread_id: wsThread,
      type,
      sender,
      client_ts: new Date().toISOString(),
    }, {}, `ws event ${type}`));
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  const signalSubmit = await api(paths.submit, {
    thread_id: wsThread,
    messages: [
      {sender: "Attached Alice", content: "Bob, are you still typing?"},
      {sender: "Attached Bob", content: "Alice, I finished editing it."},
    ],
    system_prompt: "You are a lurker. This human-to-human exchange is useful for behavioral signal tagging.",
  }, {}, "ws signal submit");
  check("signals: configured thread returns exact event bodies and submit schema", () => {
    for (const response of attachedEventResults) {
      assert.equal(response.status, 200);
      eventSchema(response.data);
    }
    assert.equal(signalSubmit.status, 200);
    submitSchema(signalSubmit.data);
    assert.equal(signalSubmit.data.turn_epoch, 1);
    assert.deepEqual(signalSubmit.data.tags, []);
    if (signalSubmit.data.decision === "stay_silent") {
      assert.deepEqual(signalSubmit.data, {decision: "stay_silent", turn_epoch: 1, tags: [], recalled_context: ""});
    } else {
      assert.equal(signalSubmit.data.recalled_context, "");
    }
  });
  observations.decisions.push({kind: "signals_thread_modeled_batch", ...signalSubmit.data});
  await new Promise((resolve) => setTimeout(resolve, 2_000));
  const driver = await runDriver(wsThread);
  const expectedMessages = driver.responded.data.scheduled.length;
  await waitFor(
    () => frames.filter((frame) => frame.type === "turn_taking.message").length >= expectedMessages &&
      frames.some((frame) => frame.type === "turn_taking.typing" && frame.data?.typing === false),
    15_000,
    "typing/message delivery",
  );
  check("websocket: driver reply scheduled schema", () => {
    assert.equal(driver.responded.status, 200, JSON.stringify(driver.responded.data));
    scheduledSchema(driver.responded.data, wsThread);
  });
  check("websocket: driver pacing math (100ms read, 2000wpm, 400ms cap, 500ms floor)", () => {
    const scheduled = driver.responded.data.scheduled;
    const deliverTimes = scheduled.map((item) => Date.parse(item.deliver_at));
    const created = Date.parse(scheduled[0].created_at);
    observations.respond.driver_typing_ms = [deliverTimes[0] - created - 100, ...deliverTimes.slice(1).map((time, i) => time - deliverTimes[i] - 200)];
    pacingFit(scheduled, {readingDelayMs: 100, typingWpm: 2000, maxTypingMs: 400});
  });
  let messageFrames = [];
  check("websocket: exact frame sequence attached → typing:true → messages → typing:false", () => {
    messageFrames = frameSequence(frames, wsThread, wsOpen.data.channel, expectedMessages);
  });
  check("websocket: forced five-paragraph reply produced 2–5 bubbles", () => {
    assert(expectedMessages >= 2 && expectedMessages <= 5, `expected 2–5 bubbles, got ${expectedMessages}`);
  });
  check("websocket: metadata echo and delivery ids differ from schedule ids", () => {
    messageFrames.forEach((frame, position) => {
      assert.deepEqual(frame.data.metadata, driver.metadata);
      assert.notEqual(frame.data.message_id, driver.responded.data.scheduled[position].id);
    });
    const deliveredIds = new Set(messageFrames.map((frame) => frame.data.message_id));
    assert.equal(deliveredIds.size, messageFrames.length);
  });
  check("websocket: every bubble arrives near its scheduled time", () => {
    const messageArrivals = arrivals.filter(({frame}) => frame.type === "turn_taking.message");
    assert.equal(messageArrivals.length, expectedMessages);
    messageArrivals.forEach(({received_at}, position) => {
      const scheduledAt = Date.parse(driver.responded.data.scheduled[position].deliver_at);
      const receivedAt = Date.parse(received_at);
      assert(receivedAt >= scheduledAt - 250, `${receivedAt - scheduledAt}ms before schedule`);
      assert(receivedAt <= scheduledAt + 3_000, `${receivedAt - scheduledAt}ms after schedule`);
    });
  });
  const signalFrames = frames.filter((frame) => frame.type === "turn_taking.signal");
  observations.websocket.signal_frames_after_three_events = signalFrames.length;
  check("signals: before/after attach events emitted no signal frame", () => {
    assert.equal(signalFrames.length, 0);
  });

  const waitUntil = Date.parse(wsOpen.data.realtime.expires_at) + 1_500;
  if (Date.now() < waitUntil) {
    await new Promise((resolve) => setTimeout(resolve, waitUntil - Date.now()));
  }
  check("websocket: attached connection survives grant expiry", () => {
    assert.equal(socket.readyState, WebSocket.OPEN);
  });
  const afterExpiryEvent = await api(paths.event, {
    thread_id: wsThread,
    type: "typing_start",
    sender: "After Expiry Human",
  }, {}, "ws event after expiry");
  check("websocket: HTTP thread remains usable after grant expiry", () => {
    assert.equal(afterExpiryEvent.status, 200);
    eventSchema(afterExpiryEvent.data);
  });
  const lateStartedAt = Date.now();
  const late = await lateConnect(wsOpen.data.realtime.connect_url);
  const lateDelayMs = lateStartedAt - Date.parse(wsOpen.data.realtime.expires_at);
  check("websocket: expired grant upgrades then closes with code 4000 and empty reason", () => {
    assert.equal(late.opened, true);
    assert.equal(late.close?.code, 4000);
    assert.equal(late.close?.reason, "");
  });
  const garbageUrl = new URL(wsOpen.data.realtime.connect_url);
  garbageUrl.searchParams.set("token", "garbage");
  const garbage = await lateConnect(garbageUrl.toString());
  check("websocket: garbage grant upgrades then closes with code 4000 and empty reason", () => {
    assert.equal(garbage.opened, true);
    assert.equal(garbage.close?.code, 4000);
    assert.equal(garbage.close?.reason, "");
  });
  const reconnectGrant = await api(paths.open, {thread_id: wsThread}, {}, "ws reopen");
  const reconnected = await connectAndCapture(reconnectGrant.data.realtime.connect_url);
  await waitFor(
    () => reconnected.frames.some((frame) => frame.type === "attached"),
    5_000,
    "reconnected attached frame",
  );
  check("websocket: reopen grant reconnects same channel with attached first", () => {
    assert.equal(reconnectGrant.data.thread.id, wsThread);
    assert.notEqual(reconnectGrant.data.realtime.connect_url, wsOpen.data.realtime.connect_url);
    assert.equal(reconnected.frames.length, 1);
    exactKeys(reconnected.frames[0], ["type", "channel", "server_time"]);
    assert.equal(reconnected.frames[0].type, "attached");
    isoOffset(reconnected.frames[0].server_time);
    assert.equal(reconnected.frames[0].channel, wsOpen.data.channel);
  });
  socket.close();
  reconnected.socket.close();
  observations.websocket.frames = frames;
  observations.websocket.types = [...new Set(frames.map((frame) => frame.type))];
  observations.websocket.event_id_prefixes = [...new Set(frames.filter((frame) => frame.id).map((frame) => frame.id.split("_")[0]))];
  observations.websocket.expired_connection_state = socket.readyState === WebSocket.OPEN ? "OPEN" : socket.readyState;
  observations.websocket.late_connect = {...late, delay_after_expiry_ms: lateDelayMs};
  observations.websocket.garbage_grant = garbage;
  observations.websocket.reconnect_attached = reconnected.frames.find((frame) => frame.type === "attached");
  observations.websocket.driver = driver;
  observations.websocket.multi_bubble = {
    scheduled_count: expectedMessages,
    scheduled_ids: driver.responded.data.scheduled.map((item) => item.id),
    delivered_ids: messageFrames.map((frame) => frame.data.message_id),
    deltas: deliveryDeltas(frames, arrivals, driver.responded.data.scheduled),
  };
  observations.websocket.signal_experiments = {
    scope_id_configured: signalScope,
    before_attach: {status: beforeAttachEvent.status, body: beforeAttachEvent.data},
    after_attach: attachedEventResults.map(({status, data}) => ({status, body: data})),
    submit: {status: signalSubmit.status, body: signalSubmit.data},
    signal_frames: signalFrames,
  };
});

// Default pacing: no pacing and no metadata; then reading_delay 0 / cap 60000 with typing_wpm omitted.
const pacingDraft = [
  "[ONE] The first paragraph confirms the request was received and understood.",
  "[TWO] The second paragraph explains the next step in simple words.",
  "[THREE] The third paragraph closes with a short friendly sign-off.",
].join("\n\n");
const longPacingDraft = [
  "[ONE] Got it, thanks for confirming.",
  "[TWO] Here is the next step in simple words.",
  "[THREE] The third paragraph is intentionally long so that it runs well past any plausible default typing cap: it keeps going with more plain words about schedules, timing, delivery, ordering, positions, identifiers, metadata, and sign-off until it is comfortably over forty words in total length.",
].join("\n\n");
const pacingPrompt = "Send each paragraph as its own separate chat bubble. Preserve the bracketed labels. Never merge paragraphs.";

await billable("respond: default pacing and omitted metadata", async () => {
  const run = await respondOverSockets({
    label: "default pacing",
    inbound: {sender: "Default Human", content: "Please reply with the three-part message."},
    respond: {content: pacingDraft, agent_name: "Live Test Agent", system_prompt: pacingPrompt},
  });
  const {responded, connections, threadId: defaultThread, open} = run;
  check("respond: default pacing scheduled schema", () => {
    assert.equal(responded.status, 200, JSON.stringify(responded.data));
    scheduledSchema(responded.data, defaultThread);
  });
  let messageFrames = [];
  check("websocket: omitted metadata is delivered as null with the exact frame sequence", () => {
    assert(run.delivered, "delivery timed out");
    messageFrames = frameSequence(connections[0].frames, defaultThread, open.data.channel, responded.data.scheduled.length);
    for (const frame of messageFrames) assert.equal(frame.data.metadata, null);
  });
  const scheduled = responded.data.scheduled ?? [];
  const deliverTimes = scheduled.map((item) => Date.parse(item.deliver_at));
  observations.pacing_defaults.no_pacing = {
    scheduled,
    words: scheduled.map((item) => wordCount(item.content)),
    first_offset_ms: deliverTimes.length ? deliverTimes[0] - Date.parse(scheduled[0].created_at) : null,
    gaps_ms: deliverTimes.slice(1).map((time, i) => time - deliverTimes[i]),
    metadata_frames: messageFrames.map((frame) => frame.data.metadata),
    deltas: run.delivered ? deliveryDeltas(connections[0].frames, connections[0].arrivals, scheduled) : null,
  };
});

await billable("respond: partial pacing reveals default typing speed", async () => {
  const open = await api(paths.open, {}, {}, "partial pacing open");
  const partialThread = open.data.thread.id;
  const submitted = await api(paths.submit, {
    thread_id: partialThread,
    messages: [{sender: "Partial Human", content: "Please reply with the three-part message."}],
    skip_decide: true,
  }, {}, "partial pacing submit");
  const partial = await api(paths.respond, {
    thread_id: partialThread,
    turn_epoch: submitted.data.turn_epoch,
    content: longPacingDraft,
    agent_name: "Live Test Agent",
    system_prompt: pacingPrompt + " Keep the third paragraph long (at least forty words) and do not shorten it.",
    pacing: {reading_delay_ms: 0},
  }, {}, "partial pacing respond");
  observations.pacing_defaults.partial = {status: partial.status, body: partial.data};
  check("respond: partial pacing object (only reading_delay_ms) is accepted", () => {
    assert.equal(partial.status, 200, JSON.stringify(partial.data));
    scheduledSchema(partial.data, partialThread);
  });
  if (partial.status !== 200) return;
  const scheduled = partial.data.scheduled;
  const deliverTimes = scheduled.map((item) => Date.parse(item.deliver_at));
  const created = Date.parse(scheduled[0].created_at);
  const words = scheduled.map((item) => wordCount(item.content));
  const typingMs = [deliverTimes[0] - created, ...deliverTimes.slice(1).map((time, i) => time - deliverTimes[i] - 200)];
  const wpmEstimates = typingMs.map((ms, i) => (ms > 0 ? words[i] * 60_000 / ms : null));
  const rawAt150 = words.map((count) => count / 150 * 60_000);
  const capped = typingMs.map((ms, i) => ms < rawAt150[i] - 10);
  const capValues = typingMs.filter((_, i) => capped[i]);
  const defaultCap = capValues.length ? capValues[0] : null;
  observations.pacing_defaults.partial = {
    ...observations.pacing_defaults.partial,
    words,
    typing_ms: typingMs,
    wpm_estimates: wpmEstimates,
    raw_at_150_wpm: rawAt150,
    capped,
    default_max_typing_ms: defaultCap,
    default_max_typing_lower_bound_ms: defaultCap === null ? Math.max(...typingMs) : null,
  };
  check("respond: default typing speed is exactly 150 WPM (400ms per whitespace word) on uncapped bubbles", () => {
    const uncapped = typingMs.filter((_, i) => !capped[i]);
    assert(uncapped.length >= 1, "no uncapped bubble");
    typingMs.forEach((ms, i) => { if (!capped[i]) assertWithinMs(ms, rawAt150[i]); });
  });
  check("respond: default max_typing_ms is exactly 8000ms", () => {
    assert(capValues.length >= 1, `no bubble reached the default cap: ${JSON.stringify({words, typingMs})}`);
    capValues.forEach((value) => assertWithinMs(value, DEFAULT_PACING.maxTypingMs));
    pacingFit(scheduled, DEFAULT_PACING);
    observations.pacing_defaults.inferred = {
      ...(observations.pacing_defaults.inferred || {}),
      typing_wpm: 150,
      reading_delay_ms: 0,
      max_typing_ms: defaultCap,
      max_typing_lower_bound_ms: defaultCap === null ? Math.max(...typingMs) : null,
    };
  });
  const noPacing = observations.pacing_defaults.no_pacing;
  if (noPacing?.scheduled?.length) {
    check("respond: omitted pacing fits reading_delay 0, 150 WPM, 8000ms cap, 500ms floor", () => {
      pacingFit(noPacing.scheduled, DEFAULT_PACING);
    });
  }
});

// Floor vs clamp: at typing_wpm 2000 with a huge cap, short bubbles reveal whether typing has a floor
// (constant for short bubbles) or the WPM is clamped (typing proportional to words with a slope above 30ms/word).
await billable("respond: typing floor / WPM clamp probe", async () => {
  const open = await api(paths.open, {}, {}, "floor probe open");
  const probeThread = open.data.thread.id;
  const submitted = await api(paths.submit, {
    thread_id: probeThread,
    messages: [{sender: "Probe Human", content: "Please reply with the three labelled parts."}],
    skip_decide: true,
  }, {}, "floor probe submit");
  const probe = await api(paths.respond, {
    thread_id: probeThread,
    turn_epoch: submitted.data.turn_epoch,
    content: [
      "[A] Okay.",
      "[B] Here are ten plain words to form the second bubble.",
      "[C] This third bubble carries twenty plain words so that the typing time can be compared against the short first bubble cleanly.",
    ].join("\n\n"),
    agent_name: "Live Test Agent",
    system_prompt: "Send each bracketed paragraph as its own separate chat bubble, verbatim. Keep [A] extremely short (one or two words). Never merge paragraphs.",
    pacing: {reading_delay_ms: 0, typing_wpm: 2000, max_typing_ms: 60_000},
  }, {}, "floor probe respond");
  check("respond: floor/clamp probe scheduled schema", () => {
    assert.equal(probe.status, 200, JSON.stringify(probe.data));
    scheduledSchema(probe.data, probeThread);
  });
  if (probe.status !== 200) return;
  const scheduled = probe.data.scheduled;
  const deliverTimes = scheduled.map((item) => Date.parse(item.deliver_at));
  const created = Date.parse(scheduled[0].created_at);
  const words = scheduled.map((item) => wordCount(item.content));
  const typing = [deliverTimes[0] - created, ...deliverTimes.slice(1).map((time, i) => time - deliverTimes[i] - 200)];
  const msPerWord = typing.map((ms, i) => ms / words[i]);
  observations.pacing_defaults.floor_probe = {
    contents: scheduled.map((item) => item.content),
    words,
    typing_ms: typing,
    raw_at_2000_wpm: words.map((count) => count * 30),
    ms_per_word: msPerWord,
  };
  check("respond: typing has a 500ms floor below which words/wpm does not apply", () => {
    const floored = typing.filter((_, i) => words[i] * 30 < TYPING_FLOOR_MS - 10);
    assert(floored.length >= 1, `no bubble short enough to hit the floor: ${JSON.stringify(words)}`);
    floored.forEach((ms) => assertWithinMs(ms, TYPING_FLOOR_MS));
    pacingFit(scheduled, {readingDelayMs: 0, typingWpm: 2000, maxTypingMs: 60_000});
    observations.pacing_defaults.floor_probe.verdict = `floor ${TYPING_FLOOR_MS}ms`;
  });
});

// Two sockets on one channel plus a six-paragraph draft that must be bounded to five bubbles.
await billable("websocket: dual sockets + six-paragraph cap", async () => {
  const metadata = {probe: "dual-socket", run: observations.run_id};
  const sixDraft = [
    "[P1] First paragraph.",
    "[P2] Second paragraph.",
    "[P3] Third paragraph.",
    "[P4] Fourth paragraph.",
    "[P5] Fifth paragraph.",
    "[P6] Sixth paragraph.",
  ].join("\n\n");
  const run = await respondOverSockets({
    label: "dual socket",
    socketCount: 2,
    inbound: {sender: "Dual Human", content: "Send all six labelled paragraphs."},
    respond: {
      content: sixDraft,
      agent_name: "Live Test Agent",
      system_prompt: "Send each bracketed paragraph as its own separate chat bubble. Preserve every bracketed label verbatim. Never merge paragraphs.",
      pacing: {reading_delay_ms: 100, typing_wpm: 2000, max_typing_ms: 400},
      metadata,
    },
    deliveryTimeoutMs: 30_000,
  });
  const {responded, connections, threadId: dualThread, open} = run;
  const labels = ["[P1]", "[P2]", "[P3]", "[P4]", "[P5]", "[P6]"];
  const joined = (responded.data.scheduled ?? []).map((item) => item.content).join("\n");
  check("respond: six-paragraph draft is merged into at most five bubbles without dropping content", () => {
    assert.equal(responded.status, 200, JSON.stringify(responded.data));
    scheduledSchema(responded.data, dualThread);
    assert(responded.data.scheduled.length >= 2 && responded.data.scheduled.length <= 5);
    assert.deepEqual(labels.filter((label) => joined.includes(label)), labels, joined);
  });
  observations.respond.six_paragraphs = {
    scheduled_count: responded.data.scheduled?.length,
    labels_present: labels.filter((label) => joined.includes(label)),
    labels_per_bubble: (responded.data.scheduled ?? []).map((item) => labels.filter((label) => item.content.includes(label))),
    contents: (responded.data.scheduled ?? []).map((item) => item.content),
  };
  check("websocket: both sockets receive the identical frame sequence with identical ids", () => {
    assert(run.delivered, "delivery timed out");
    const expected = responded.data.scheduled.length;
    const [first, second] = connections;
    frameSequence(first.frames, dualThread, open.data.channel, expected);
    frameSequence(second.frames, dualThread, open.data.channel, expected);
    const strip = (frames) => frames.slice(1).map((frame) => ({id: frame.id, type: frame.type, data: frame.data}));
    assert.deepEqual(strip(first.frames), strip(second.frames));
    for (const frame of first.frames.filter((item) => item.type === "turn_taking.message")) {
      assert.deepEqual(frame.data.metadata, metadata);
    }
  });
  observations.websocket.dual_socket = {
    scheduled_count: responded.data.scheduled?.length,
    socket_frame_types: connections.map((connection) => connection.frames.map((frame) => frame.type)),
    message_ids: connections.map((connection) =>
      connection.frames.filter((frame) => frame.type === "turn_taking.message").map((frame) => frame.data.message_id)),
  };
});

// Social Memory uses fresh scopes so every run is live and independent.
const emptyScope = unique("empty-memory");
await billable("social-memory recall: empty scope", async () => {
  const emptyRecall = await api(paths.recall, {
    scope_id: emptyScope,
    message: {speaker: "Nobody", text: "What is remembered?"},
  }, {}, "recall empty scope");
  check("social-memory recall: empty scope is exact empty context", () => {
    assert.equal(emptyRecall.status, 200);
    assert.deepEqual(emptyRecall.data, {context: ""});
  });
  observations.memory.empty_recall = emptyRecall.data;
});

const emptyTranscript = await api(paths.ingest, {scope_id: unique("empty-transcript"), transcript: []}, {}, "validation empty transcript");
observations.validation.push({case: "empty transcript", ...errorSnapshot(emptyTranscript)});
check("social-memory ingest: empty transcript is too_short at transcript", () => validationShape(emptyTranscript, ["transcript"], "too_short"));

const memoryScope = unique("memory");
const idempotencyKey = crypto.randomUUID();
const factCode = `ORBIT-${crypto.randomInt(100000, 999999)}`;
const ingestBody = {
  scope_id: memoryScope,
  transcript: [
    {speaker: "Yara", text: `Person Xena chose the code ${factCode}.`},
    {speaker: "Xena", text: "The blue card comes first."},
    {speaker: "Yara", text: "The green card comes second."},
  ],
};
const ingestFirst = await api(paths.ingest, ingestBody, {
  headers: {"idempotency-key": idempotencyKey},
}, "ingest first");
const ingestReplay = await api(paths.ingest, ingestBody, {
  headers: {"idempotency-key": idempotencyKey},
}, "ingest replay");
const ingestConflict = await api(paths.ingest, {
  ...ingestBody,
  transcript: [{speaker: "Yara", text: "Different body under the same key."}],
}, {headers: {"idempotency-key": idempotencyKey}}, "ingest conflict");
check("social-memory ingest: ordered batch count and replay", () => {
  assert.equal(ingestFirst.status, 200);
  assert.deepEqual(ingestFirst.data, {ingested: 3});
  assert.equal(ingestReplay.status, 200);
  assert.deepEqual(ingestReplay.data, ingestFirst.data);
});
check("social-memory ingest: same key different body replays original", () => {
  assert.equal(ingestConflict.status, 200);
  assert.deepEqual(ingestConflict.data, ingestFirst.data);
});
observations.memory.ingest = {
  first: {status: ingestFirst.status, body: ingestFirst.data},
  replay: {status: ingestReplay.status, body: ingestReplay.data},
  conflict: {status: ingestConflict.status, body: ingestConflict.data},
};

const employerScope = unique("idempotency-employer");
const employerKey = crypto.randomUUID();
const employerSuffix = crypto.randomInt(100000, 999999);
const acme = `Acme-${employerSuffix}`;
const globex = `Globex-${employerSuffix}`;
const employerOriginal = {
  scope_id: employerScope,
  transcript: [{speaker: "Witness", text: `Xavier works at ${acme}.`}],
};
const employerFirst = await api(paths.ingest, employerOriginal, {
  headers: {"idempotency-key": employerKey},
}, "ingest employer first");
const employerSameReplay = await api(paths.ingest, employerOriginal, {
  headers: {"idempotency-key": employerKey},
}, "ingest employer same");
const employerChangedReplay = await api(paths.ingest, {
  scope_id: employerScope,
  transcript: [{speaker: "Witness", text: `Xavier works at ${globex}.`}],
}, {headers: {"idempotency-key": employerKey}}, "ingest employer changed");
check("social-memory idempotency: same and changed bodies replay original response", () => {
  assert.equal(employerFirst.status, 200);
  assert.deepEqual(employerFirst.data, {ingested: 1});
  assert.equal(employerSameReplay.status, 200);
  assert.deepEqual(employerSameReplay.data, employerFirst.data);
  assert.equal(employerChangedReplay.status, 200);
  assert.deepEqual(employerChangedReplay.data, employerFirst.data);
});

// Idempotency scope: the same key reused on a different scope_id with a different-length body.
const scopeKey = crypto.randomUUID();
const scopeOne = unique("idem-scope-one");
const scopeTwo = unique("idem-scope-two");
const tokenX = `XRAY-${crypto.randomInt(100000, 999999)}`;
const tokenY = `YANKEE-${crypto.randomInt(100000, 999999)}`;
const scopeOneIngest = await api(paths.ingest, {
  scope_id: scopeOne,
  transcript: [{speaker: "Witness", text: `Zed's locker code is ${tokenX}.`}],
}, {headers: {"idempotency-key": scopeKey}}, "ingest scope one");
const scopeTwoIngest = await api(paths.ingest, {
  scope_id: scopeTwo,
  transcript: [
    {speaker: "Witness", text: `Zed's locker code is ${tokenY}.`},
    {speaker: "Zed", text: "Thanks for reminding me."},
  ],
}, {headers: {"idempotency-key": scopeKey}}, "ingest scope two same key");
observations.memory.idempotency_scope = {
  scope_one: {status: scopeOneIngest.status, body: scopeOneIngest.data},
  scope_two_same_key: {status: scopeTwoIngest.status, body: scopeTwoIngest.data},
};
check("social-memory idempotency: key is scoped per (owner, key) — second scope replays the first response", () => {
  assert.equal(scopeOneIngest.status, 200);
  assert.deepEqual(scopeOneIngest.data, {ingested: 1});
  assert.equal(scopeTwoIngest.status, 200);
  assert.deepEqual(scopeTwoIngest.data, {ingested: 1});
});

await billable("social-memory idempotency: recall proves storage semantics", async () => {
  const employerRecall = await api(paths.recall, {
    scope_id: employerScope,
    message: {speaker: "Xavier", text: "Where do I work?"},
  }, {}, "recall employer");
  const employerAsk = await api(paths.ask, {
    scope_id: employerScope,
    question: "Where does Xavier work?",
  }, {}, "ask employer");
  check("social-memory idempotency: original body wins and changed body is absent", () => {
    assert.equal(employerRecall.status, 200);
    assert.equal(employerAsk.status, 200);
    assert(employerRecall.data.context.includes(acme), employerRecall.data.context);
    assert(!employerRecall.data.context.includes(globex), employerRecall.data.context);
    assert(employerAsk.data.answer.includes(acme), employerAsk.data.answer);
    assert(!employerAsk.data.answer.includes(globex), employerAsk.data.answer);
  });
  check("social-memory idempotency: same-body replay has no recall duplication", () => {
    assert.equal(employerRecall.data.context.split(acme).length - 1, 1, employerRecall.data.context);
  });
  observations.memory.idempotency_storage = {
    original: {status: employerFirst.status, body: employerFirst.data, fact: `Xavier works at ${acme}`},
    same_body_replay: {status: employerSameReplay.status, body: employerSameReplay.data},
    changed_body_replay: {
      status: employerChangedReplay.status,
      body: employerChangedReplay.data,
      ignored_fact: `Xavier works at ${globex}`,
    },
    recall: employerRecall.data,
    ask: employerAsk.data,
  };
  const scopeTwoRecall = await api(paths.recall, {
    scope_id: scopeTwo,
    message: {speaker: "Zed", text: "What is my locker code?"},
  }, {}, "recall scope two");
  observations.memory.idempotency_scope.scope_two_recall = scopeTwoRecall.data;
  check("social-memory idempotency: cross-scope key reuse stored nothing in the second scope", () => {
    assert.equal(scopeTwoRecall.status, 200);
    assert.deepEqual(scopeTwoRecall.data, {context: ""});
  });
});

const emptyQuestion = await api(paths.ask, {scope_id: memoryScope, question: ""}, {}, "validation empty question");
check("social-memory ask: empty question is string_too_short", () => validationShape(emptyQuestion, ["question"], "string_too_short"));
observations.validation.push({case: "empty memory question", ...errorSnapshot(emptyQuestion)});

await billable("social-memory: recall/ask grounding", async () => {
  const recall = await api(paths.recall, {
    scope_id: memoryScope,
    message: {speaker: "Xena", text: "Remind me of my chosen code."},
  }, {}, "recall fact");
  check("social-memory recall: speaker-aware subject attribution", () => {
    assert.equal(recall.status, 200);
    exactKeys(recall.data, ["context"]);
    assert(recall.data.context.includes(factCode), recall.data.context);
    assert.match(recall.data.context, /Xena/i);
  });
  const askFact = await api(paths.ask, {
    scope_id: memoryScope,
    question: "What code did Xena choose?",
  }, {}, "ask fact");
  const askOrder = await api(paths.ask, {
    scope_id: memoryScope,
    question: "Which card comes first and which comes second?",
  }, {}, "ask order");
  check("social-memory ask: grounded fact answer", () => {
    assert.equal(askFact.status, 200);
    exactKeys(askFact.data, ["answer"]);
    assert(askFact.data.answer.includes(factCode), askFact.data.answer);
  });
  check("social-memory ingest: transcript ordering remains queryable", () => {
    assert.equal(askOrder.status, 200);
    assert.match(askOrder.data.answer, /blue/i);
    assert.match(askOrder.data.answer, /green/i);
    assert(askOrder.data.answer.toLowerCase().indexOf("blue") <
      askOrder.data.answer.toLowerCase().indexOf("green"));
  });
  observations.memory.recall = recall.data;
  observations.memory.ask_fact = askFact.data;
  observations.memory.ask_order = askOrder.data;
});

// The last authenticated call is deliberately the final usage projection.
const usageEndResponse = await usage();
const usageEnd = usageEndResponse.data;
check("usage-summary: final exact schema", () => usageSchema(usageEnd));
observations.billing.end = usageEnd;
observations.billing.delta = usageDelta(usageStart, usageEnd);
observations.billing.component_slugs = Object.keys(componentMap(usageEnd)).sort();

// Transport invariants over every captured HTTP response, including 401/422.
check("headers: every response carries a non-empty x-request-id", () => {
  const missing = responses.filter(({headers}) => typeof headers["x-request-id"] !== "string" || headers["x-request-id"].length === 0);
  assert.deepEqual(missing.map(({label, status}) => `${label} (${status})`), []);
});
check("headers: every response is application/json", () => {
  const wrong = responses.filter(({headers}) => !/^application\/json\b/.test(headers["content-type"] || ""));
  assert.deepEqual(wrong.map(({label, status}) => `${label} (${status}): ${headers(wrong)}`), []);
  function headers(list) { return list.map((item) => item.headers["content-type"]).join("|"); }
});
check("headers: no response exposes rate-limit or Retry-After headers", () => {
  const exposed = responses.filter(({headers}) =>
    Object.keys(headers).some((name) => /^(x-)?rate|retry-after/i.test(name)));
  assert.deepEqual(exposed.map(({label, status, headers}) =>
    `${label} (${status}): ${Object.keys(headers).filter((name) => /^(x-)?rate|retry-after/i.test(name)).join(",")}`), []);
});
observations.headers.response_count = responses.length;
observations.headers.status_histogram = responses.reduce((acc, {status}) => ({...acc, [status]: (acc[status] || 0) + 1}), {});

const redacted = JSON.parse(JSON.stringify(observations), (key, value) => {
  if (key === "user_id") return "[REDACTED]";
  if (key === "connect_url" && typeof value === "string") return redactWsUrl(value);
  if (key === "authorization") return "[REDACTED]";
  return value;
});
console.log(`OBSERVATIONS ${JSON.stringify(redacted)}`);

const passed = results.filter((result) => result.pass).length;
const skipped = results.filter((result) => result.skip).length;
const failed = results.length - passed - skipped;
console.log(`SUMMARY ${passed} passed, ${failed} failed, ${skipped} skipped`);
console.log(`CREDITS ${JSON.stringify(observations.billing.delta)}`);
if (creditsDepleted) console.error("CREDITS DEPLETED: billable blocks skipped after HTTP 402");
process.exitCode = failed ? 1 : creditsDepleted ? 3 : 0;
