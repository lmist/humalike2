import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import crypto from "node:crypto";
import {fileURLToPath} from "node:url";
import {WebSocket} from "ws";
import {
  componentMap,
  paths,
  post,
  requireKey,
  unique,
  usageDelta,
} from "./client.mjs";

requireKey();

const results = [];
const observations = {
  run_id: unique("realtime"),
  headers: {},
  auth: {},
  validation: [],
  open_thread: {},
  decisions: [],
  events: [],
  respond: {},
  websocket: {frames: []},
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

function exactKeys(value, keys) {
  assert(value && typeof value === "object" && !Array.isArray(value));
  assert.deepEqual(Object.keys(value).sort(), [...keys].sort());
}

function iso(value) {
  assert.equal(typeof value, "string");
  assert(!Number.isNaN(Date.parse(value)), `${value} is not ISO-like`);
}

function uuid(value) {
  assert.match(value, /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
}

function assertWithinMs(actual, expected, tolerance = 10) {
  assert(
    Math.abs(actual - expected) <= tolerance,
    `expected ${actual}ms to be within ±${tolerance}ms of ${expected}ms`,
  );
}

function validationShape(response, expectedLoc) {
  assert.equal(response.status, 422);
  exactKeys(response.data, ["error"]);
  assert.equal(response.data.error.code, "validation_failed");
  assert.equal(response.data.error.message, "request validation failed");
  assert(Array.isArray(response.data.error.details));
  assert(response.data.error.details.length >= 1);
  const detail = response.data.error.details.find((item) =>
    JSON.stringify(item.loc) === JSON.stringify(expectedLoc),
  );
  assert(detail, `missing detail at ${JSON.stringify(expectedLoc)}`);
  exactKeys(detail, ["loc", "msg", "type"]);
  assert.equal(typeof detail.msg, "string");
  assert.equal(typeof detail.type, "string");
}

function captureHeaders(label, response) {
  const headers = response.headers;
  observations.headers[label] = headers;
  check(`${label}: JSON content type`, () => assert.match(headers["content-type"] || "", /^application\/json\b/));
  check(`${label}: x-request-id present`, () => assert.equal(typeof headers["x-request-id"], "string"));
}

async function api(path, body, options) {
  const response = await post(path, body, options);
  if (response.status === 402) creditsDepleted = true;
  return response;
}

async function usage() {
  const response = await api(paths.usage, {});
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

function openSchema(body) {
  exactKeys(body, ["thread", "channel", "realtime"]);
  exactKeys(body.thread, ["id", "user_id", "created_at", "updated_at"]);
  uuid(body.thread.id);
  assert.equal(typeof body.thread.user_id, "string");
  iso(body.thread.created_at);
  iso(body.thread.updated_at);
  assert.equal(body.channel, `turn-taking-thread/${body.thread.id}`);
  exactKeys(body.realtime, ["connect_url", "expires_at"]);
  const url = new URL(body.realtime.connect_url);
  assert.equal(url.protocol, "wss:");
  assert.equal(url.hostname, "api.humalike.com");
  assert.equal(url.pathname, "/v1/ws/turn-taking-thread");
  assert(url.search.length > 1);
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
  exactKeys(body, ["tags"]);
  assert(Array.isArray(body.tags) && body.tags.every((tag) => typeof tag === "string"));
}

function scheduledSchema(body, threadId) {
  exactKeys(body, ["scheduled", "superseded"]);
  assert.equal(body.superseded, false);
  assert(body.scheduled.length >= 1 && body.scheduled.length <= 5);
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
    assert.equal(typeof item.status, "string");
  });
}

function redactWsUrl(value) {
  const url = new URL(value);
  url.search = "?grant=[REDACTED]";
  return url.toString();
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

console.log(`Live Humalike realtime test run ${observations.run_id}`);

// The first authenticated call is deliberately the baseline usage projection.
const usageStartResponse = await usage();
const usageStart = usageStartResponse.data;
observations.billing.start = usageStart;
captureHeaders("usage-summary", usageStartResponse);
check("usage-summary: exact schema", () => usageSchema(usageStart));

const whoami = await api(paths.whoami, {});
captureHeaders("whoami", whoami);
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
  const response = await api(paths.whoami, {}, options);
  observations.auth[label] = errorSnapshot(response);
  check(`auth: ${label} exact 401`, () => {
    assert.equal(response.status, 401);
    assert.deepEqual(response.data, {
      error: {code: "UNAUTHORIZED", message: "missing or invalid credentials"},
    });
  });
}

const rateHeaderNames = Object.keys(usageStartResponse.headers).filter((name) =>
  /^(x-)?rate|retry-after/i.test(name),
);
observations.headers.rate_limit_headers = rateHeaderNames;
check("headers: rate-limit inventory captured", () => assert(Array.isArray(rateHeaderNames)));

const invalidUuid = await api(paths.open, {thread_id: "not-a-uuid"});
observations.validation.push({case: "invalid UUID", ...errorSnapshot(invalidUuid)});
captureHeaders("validation-error", invalidUuid);
check("validation: lowercase envelope and UUID detail", () => validationShape(invalidUuid, ["thread_id"]));

const bankA = unique("bank-a");
const bankB = unique("bank-b");
const opened = await api(paths.open, {
  integrations: {
    social_signals: {channel_id: unique("signals")},
    social_memory: {memory_bank_id: bankA},
  },
});
check("open_thread: create schema and grant anatomy", () => {
  assert.equal(opened.status, 200);
  openSchema(opened.data);
});
const threadId = opened.data.thread.id;
observations.open_thread.create = {
  ...opened.data,
  realtime: {...opened.data.realtime, connect_url: redactWsUrl(opened.data.realtime.connect_url)},
};

await new Promise((resolve) => setTimeout(resolve, 30));
const reopenedSet = await api(paths.open, {
  thread_id: threadId,
  integrations: {social_memory: {memory_bank_id: bankB}},
});
check("open_thread: reopen same id and rotate grant", () => {
  assert.equal(reopenedSet.status, 200);
  openSchema(reopenedSet.data);
  assert.equal(reopenedSet.data.thread.id, threadId);
  assert.notEqual(reopenedSet.data.realtime.connect_url, opened.data.realtime.connect_url);
  assert(Date.parse(reopenedSet.data.realtime.expires_at) > Date.parse(opened.data.realtime.expires_at));
  assert(Date.parse(reopenedSet.data.thread.updated_at) >= Date.parse(opened.data.thread.updated_at));
});
const reopenedPreserve = await api(paths.open, {thread_id: threadId});
check("open_thread: omission preserves callable thread", () => {
  assert.equal(reopenedPreserve.status, 200);
  assert.equal(reopenedPreserve.data.thread.id, threadId);
  assert.notEqual(reopenedPreserve.data.realtime.connect_url, reopenedSet.data.realtime.connect_url);
});
observations.open_thread.reopen = {
  id_same: reopenedSet.data.thread.id === threadId,
  grant_rotated: reopenedSet.data.realtime.connect_url !== opened.data.realtime.connect_url,
  updated_at_changed: reopenedSet.data.thread.updated_at !== opened.data.thread.updated_at,
  create_ttl_ms: Date.parse(opened.data.realtime.expires_at) - opened.endedAt.getTime(),
  path: new URL(opened.data.realtime.connect_url).pathname,
  query_keys: [...new URL(opened.data.realtime.connect_url).searchParams.keys()],
};

const emptyMessages = await api(paths.submit, {thread_id: threadId, messages: []});
const tooManyMessages = await api(paths.submit, {
  thread_id: threadId,
  messages: Array.from({length: 21}, (_, i) => ({sender: `u${i}`, content: "x"})),
});
const tooLongContent = await api(paths.submit, {
  thread_id: threadId,
  messages: [{sender: "u", content: "x".repeat(4001)}],
});
const tooLongSender = await api(paths.submit, {
  thread_id: threadId,
  messages: [{sender: "s".repeat(256), content: "x"}],
});
for (const [label, response, loc] of [
  ["empty messages", emptyMessages, ["messages"]],
  ["21 messages", tooManyMessages, ["messages"]],
  ["content >4000", tooLongContent, ["messages", 0, "content"]],
  ["sender >255", tooLongSender, ["messages", 0, "sender"]],
]) {
  observations.validation.push({case: label, ...errorSnapshot(response)});
  check(`validation: ${label}`, () => validationShape(response, loc));
}

const noIntegrationOpen = await api(paths.open, {});
const noIntegrationSubmit = await api(paths.submit, {
  thread_id: noIntegrationOpen.data.thread.id,
  messages: [{sender: "Human", content: "short circuit without integrations"}],
  skip_decide: true,
});
check("submit: skip_decide short-circuits and no integrations are empty", () => {
  assert.equal(noIntegrationSubmit.status, 200);
  submitSchema(noIntegrationSubmit.data);
  assert.equal(noIntegrationSubmit.data.decision, "speak");
  assert.deepEqual(noIntegrationSubmit.data.tags, []);
  assert.equal(noIntegrationSubmit.data.recalled_context, "");
});

const skip = await api(paths.submit, {
  thread_id: threadId,
  messages: [{sender: "Human", content: "first short-circuit batch"}],
  skip_decide: true,
});
const media = await api(paths.submit, {
  thread_id: threadId,
  messages: [{sender: "Human", content: "[image]", has_media: true}],
});
check("submit: skip_decide and media each advance exactly one epoch", () => {
  submitSchema(skip.data);
  submitSchema(media.data);
  assert.equal(skip.data.decision, "speak");
  assert.equal(media.data.decision, "speak");
  assert.equal(media.data.turn_epoch, skip.data.turn_epoch + 1);
});
observations.decisions.push({kind: "skip_decide", ...skip.data}, {kind: "has_media", ...media.data});

if (!creditsDepleted) {
  const modeledSpeak = await api(paths.submit, {
    thread_id: threadId,
    messages: [{
      sender: "Human",
      content: "Live Test Agent, please answer me directly: are you available?",
    }],
    system_prompt: "You are Live Test Agent. Speak when directly addressed. Stay silent during unrelated side chatter.",
  });
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
    });
    silenceResults.push(response);
    observations.decisions.push({
      kind: `modeled_silence_attempt_${index + 1}`,
      request: message,
      ...response.data,
    });
  }
  check("submit: five engineered silence decisions have valid schemas", () => {
    assert.equal(silenceResults.length, 5);
    for (const response of silenceResults) {
      assert.equal(response.status, 200);
      submitSchema(response.data);
    }
  });
  observations.decisions.push({
    kind: "stay_silent_induction_result",
    induced: silenceResults.some((response) => response.data.decision === "stay_silent"),
    attempts: silenceResults.length,
    outcomes: silenceResults.map((response) => response.data.decision),
  });
}

for (const type of ["typing_start", "typing_stop", "message_edited"]) {
  const response = await api(paths.event, {
    thread_id: threadId,
    type,
    sender: "Human",
    client_ts: new Date().toISOString(),
  });
  observations.events.push({type, status: response.status, body: response.data});
  check(`record_event: ${type} exact schema`, () => {
    assert.equal(response.status, 200);
    eventSchema(response.data);
  });
}
const unknownEvent = await api(paths.event, {
  thread_id: threadId,
  type: "unknown_event",
  sender: "Human",
});
observations.validation.push({case: "unknown event", ...errorSnapshot(unknownEvent)});
check("record_event: unknown type validation", () => validationShape(unknownEvent, ["type"]));

// Seed both banks, proving reopen-with-integrations changes the bank and omission keeps it.
const seedA = `ALPHA-${crypto.randomInt(100000, 999999)}`;
const seedB = `BRAVO-${crypto.randomInt(100000, 999999)}`;
await api(paths.ingest, {
  scope_id: bankA,
  transcript: [{speaker: "Priya", text: `Priya's verification code is ${seedA}.`}],
}, {headers: {"idempotency-key": crypto.randomUUID()}});
await api(paths.ingest, {
  scope_id: bankB,
  transcript: [{speaker: "Priya", text: `Priya's verification code is ${seedB}.`}],
}, {headers: {"idempotency-key": crypto.randomUUID()}});
const integrated = await api(paths.submit, {
  thread_id: threadId,
  messages: [{sender: "Priya", content: "What is my verification code?"}],
  skip_decide: true,
});
check("open_thread integrations: set then preserve social-memory bank", () => {
  assert.equal(integrated.status, 200);
  submitSchema(integrated.data);
  assert(integrated.data.recalled_context.includes(seedB), integrated.data.recalled_context);
  assert(!integrated.data.recalled_context.includes(seedA), integrated.data.recalled_context);
});
observations.open_thread.integration_recall = integrated.data.recalled_context;

if (!creditsDepleted) {
  const replyEpoch = integrated.data.turn_epoch;
  const normal = await api(paths.respond, {
    thread_id: threadId,
    content: "Absolutely. First, I can confirm the requested code. Second, I can help with the next verification step.",
    turn_epoch: replyEpoch,
    agent_name: "Live Test Agent",
    system_prompt: "Be concise and friendly. Keep distinct steps as short chat bubbles.",
    pacing: {reading_delay_ms: 500, typing_wpm: 120, max_typing_ms: 1500},
    metadata: {opaque: "round-trip", nested: {value: 7}},
  });
  check("respond: scheduled schema including production timestamps", () => {
    assert.equal(normal.status, 200);
    scheduledSchema(normal.data, threadId);
  });
  const deliverTimes = normal.data.scheduled.map((item) => Date.parse(item.deliver_at));
  check("respond: positions and delivery times strictly ordered", () => {
    for (let i = 1; i < deliverTimes.length; i++) assert(deliverTimes[i] > deliverTimes[i - 1]);
  });
  const spacings = deliverTimes.slice(1).map((time, i) => time - deliverTimes[i]);
  const createdTimes = normal.data.scheduled.map((item) => Date.parse(item.created_at));
  const wordCounts = normal.data.scheduled.map((item) =>
    item.content.trim().split(/\s+/).filter(Boolean).length,
  );
  const typingDelays = wordCounts.map((words) => Math.min(1500, words / 120 * 60_000));
  check("respond: explicit pacing math includes 200ms inter-bubble gap", () => {
    assertWithinMs(deliverTimes[0] - createdTimes[0], 500 + typingDelays[0]);
    spacings.forEach((spacing, index) => {
      assertWithinMs(spacing, 200 + typingDelays[index + 1]);
    });
  });
  observations.respond.normal = {
    request_content: "Absolutely. First, I can confirm the requested code. Second, I can help with the next verification step.",
    response: normal.data,
    spacing_ms: spacings,
    first_deliver_offset_from_response_start_ms: deliverTimes[0] - normal.startedAt.getTime(),
  };

  const newer = await api(paths.submit, {
    thread_id: threadId,
    messages: [{sender: "Human", content: "Interrupt the previous draft."}],
    skip_decide: true,
  });
  const beforeStale = (await usage()).data;
  const stale = await api(paths.respond, {
    thread_id: threadId,
    content: "This stale draft must not be delivered.",
    turn_epoch: replyEpoch,
  });
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
}

// WebSocket catalog: attach, drive HTTP from a separate Node process, and correlate frames.
if (!creditsDepleted) {
  const signalScope = unique("signal-scope");
  const wsOpen = await api(paths.open, {
    integrations: {social_signals: {scope_id: signalScope}},
  });
  const wsThread = wsOpen.data.thread.id;
  const beforeAttachEvent = await api(paths.event, {
    thread_id: wsThread,
    type: "message_edited",
    sender: "Before Attach Human",
    client_ts: new Date().toISOString(),
  });
  check("signals: event before WebSocket attachment is accepted", () => {
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
    }));
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  const signalSubmit = await api(paths.submit, {
    thread_id: wsThread,
    messages: [
      {sender: "Attached Alice", content: "Bob, are you still typing?"},
      {sender: "Attached Bob", content: "Alice, I finished editing it."},
    ],
    system_prompt: "You are a lurker. This human-to-human exchange is useful for behavioral signal tagging.",
  });
  check("signals: configured thread returns valid event and submit schemas", () => {
    for (const response of attachedEventResults) {
      assert.equal(response.status, 200);
      eventSchema(response.data);
    }
    assert.equal(signalSubmit.status, 200);
    submitSchema(signalSubmit.data);
  });
  await new Promise((resolve) => setTimeout(resolve, 2_000));
  const driver = await runDriver(wsThread);
  const expectedMessages = driver.responded.data.scheduled.length;
  await waitFor(
    () => frames.filter((frame) => frame.type === "turn_taking.message").length >= expectedMessages &&
      frames.some((frame) => frame.type === "turn_taking.typing" && frame.data?.typing === false),
    15_000,
    "typing/message delivery",
  );
  check("websocket: event frames have canonical envelope", () => {
    for (const frame of frames.filter((item) => item.type !== "attached")) {
      exactKeys(frame, ["id", "type", "channel", "ts", "data"]);
      assert.equal(typeof frame.id, "string");
      assert.equal(frame.channel, wsOpen.data.channel);
      iso(frame.ts);
      assert(frame.data && typeof frame.data === "object");
    }
  });
  check("websocket: attached uses its distinct handshake schema", () => {
    const attached = frames.find((frame) => frame.type === "attached");
    exactKeys(attached, ["type", "channel", "server_time"]);
    assert.equal(attached.channel, wsOpen.data.channel);
    iso(attached.server_time);
  });
  check("websocket: attached, typing true/false, and messages captured", () => {
    assert(frames.some((frame) => frame.type === "attached"));
    assert(frames.some((frame) => frame.type === "turn_taking.typing" && frame.data.typing === true));
    assert(frames.some((frame) => frame.type === "turn_taking.typing" && frame.data.typing === false));
    assert.equal(
      frames.filter((frame) => frame.type === "turn_taking.message").length,
      expectedMessages,
    );
  });
  check("websocket: forced reply produced multiple scheduled bubbles", () => {
    assert(expectedMessages >= 2, `expected 2+ bubbles, got ${expectedMessages}`);
  });
  const messageFrames = frames.filter((frame) => frame.type === "turn_taking.message");
  check("websocket: ordered zero-based bubbles and metadata echo", () => {
    messageFrames.forEach((frame, position) => {
      exactKeys(frame.data, [
        "message_id", "thread_id", "content", "position", "sent_at", "metadata",
      ]);
      assert.equal(frame.data.thread_id, wsThread);
      assert.equal(frame.data.position, position);
      assert.deepEqual(frame.data.metadata, driver.metadata);
      iso(frame.data.sent_at);
      uuid(frame.data.message_id);
      assert.notEqual(frame.data.message_id, driver.responded.data.scheduled[position].id);
    });
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
  check("signals: configured social_signals submit returned empty tags", () => {
    assert.deepEqual(signalSubmit.data.tags, []);
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
  });
  check("websocket: HTTP thread remains usable after grant expiry", () => {
    assert.equal(afterExpiryEvent.status, 200);
    eventSchema(afterExpiryEvent.data);
  });
  const late = await lateConnect(wsOpen.data.realtime.connect_url);
  check("websocket: expired grant upgrades then closes with code 4000", () => {
    assert.equal(late.opened, true);
    assert.equal(late.close?.code, 4000);
  });
  const reconnectGrant = await api(paths.open, {thread_id: wsThread});
  const reconnected = await connectAndCapture(reconnectGrant.data.realtime.connect_url);
  await waitFor(
    () => reconnected.frames.some((frame) => frame.type === "attached"),
    5_000,
    "reconnected attached frame",
  );
  check("websocket: reopen grant reconnects same channel", () => {
    assert.equal(reconnectGrant.data.thread.id, wsThread);
    assert.notEqual(reconnectGrant.data.realtime.connect_url, wsOpen.data.realtime.connect_url);
    assert.equal(reconnected.frames[0].channel, wsOpen.data.channel);
  });
  socket.close();
  reconnected.socket.close();
  observations.websocket.frames = frames;
  observations.websocket.types = [...new Set(frames.map((frame) => frame.type))];
  observations.websocket.expired_connection_state = "OPEN";
  observations.websocket.late_connect = late;
  observations.websocket.reconnect_attached = reconnected.frames.find((frame) => frame.type === "attached");
  observations.websocket.driver = driver;
  observations.websocket.multi_bubble = {
    scheduled_count: expectedMessages,
    scheduled_ids: driver.responded.data.scheduled.map((item) => item.id),
    delivered_ids: messageFrames.map((frame) => frame.data.message_id),
    arrival_offsets_ms: arrivals
      .filter(({frame}) => frame.type === "turn_taking.message")
      .map(({received_at}, position) =>
        Date.parse(received_at) - Date.parse(driver.responded.data.scheduled[position].deliver_at),
      ),
  };
  observations.websocket.signal_experiments = {
    scope_id_configured: signalScope,
    before_attach: {status: beforeAttachEvent.status, body: beforeAttachEvent.data},
    after_attach: attachedEventResults.map(({status, data}) => ({status, body: data})),
    submit: {status: signalSubmit.status, body: signalSubmit.data},
    signal_frames: signalFrames,
  };
}

// Social Memory uses fresh scopes so every run is live and independent.
const emptyScope = unique("empty-memory");
if (!creditsDepleted) {
  const emptyRecall = await api(paths.recall, {
    scope_id: emptyScope,
    message: {speaker: "Nobody", text: "What is remembered?"},
  });
  check("social-memory recall: empty scope is exact empty context", () => {
    assert.equal(emptyRecall.status, 200);
    assert.deepEqual(emptyRecall.data, {context: ""});
  });
  observations.memory.empty_recall = emptyRecall.data;
}

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
});
const ingestReplay = await api(paths.ingest, ingestBody, {
  headers: {"idempotency-key": idempotencyKey},
});
const ingestConflict = await api(paths.ingest, {
  ...ingestBody,
  transcript: [{speaker: "Yara", text: "Different body under the same key."}],
}, {headers: {"idempotency-key": idempotencyKey}});
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
});
const employerSameReplay = await api(paths.ingest, employerOriginal, {
  headers: {"idempotency-key": employerKey},
});
const employerChangedReplay = await api(paths.ingest, {
  scope_id: employerScope,
  transcript: [{speaker: "Witness", text: `Xavier works at ${globex}.`}],
}, {headers: {"idempotency-key": employerKey}});
check("social-memory idempotency: same and changed bodies replay original response", () => {
  assert.equal(employerFirst.status, 200);
  assert.deepEqual(employerFirst.data, {ingested: 1});
  assert.equal(employerSameReplay.status, 200);
  assert.deepEqual(employerSameReplay.data, employerFirst.data);
  assert.equal(employerChangedReplay.status, 200);
  assert.deepEqual(employerChangedReplay.data, employerFirst.data);
});

if (!creditsDepleted) {
  const employerRecall = await api(paths.recall, {
    scope_id: employerScope,
    message: {speaker: "Xavier", text: "Where do I work?"},
  });
  const employerAsk = await api(paths.ask, {
    scope_id: employerScope,
    question: "Where does Xavier work?",
  });
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
}

const emptyQuestion = await api(paths.ask, {scope_id: memoryScope, question: ""});
check("social-memory ask: empty question validation shape", () => validationShape(emptyQuestion, ["question"]));
observations.validation.push({case: "empty memory question", ...errorSnapshot(emptyQuestion)});

if (!creditsDepleted) {
  const recall = await api(paths.recall, {
    scope_id: memoryScope,
    message: {speaker: "Xena", text: "Remind me of my chosen code."},
  });
  check("social-memory recall: speaker-aware subject attribution", () => {
    assert.equal(recall.status, 200);
    exactKeys(recall.data, ["context"]);
    assert(recall.data.context.includes(factCode), recall.data.context);
    assert.match(recall.data.context, /Xena/i);
  });
  const askFact = await api(paths.ask, {
    scope_id: memoryScope,
    question: "What code did Xena choose?",
  });
  const askOrder = await api(paths.ask, {
    scope_id: memoryScope,
    question: "Which card comes first and which comes second?",
  });
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
}

// The last authenticated call is deliberately the final usage projection.
const usageEndResponse = await usage();
const usageEnd = usageEndResponse.data;
check("usage-summary: final exact schema", () => usageSchema(usageEnd));
observations.billing.end = usageEnd;
observations.billing.delta = usageDelta(usageStart, usageEnd);

const redacted = JSON.parse(JSON.stringify(observations), (key, value) => {
  if (key === "user_id") return "[REDACTED]";
  if (key === "connect_url" && typeof value === "string") {
    return "wss://api.humalike.com/v1/ws/turn-taking-thread?grant=[REDACTED]";
  }
  return value;
});
for (const entry of Object.values(redacted.open_thread)) {
  if (entry?.realtime?.connect_url) entry.realtime.connect_url = "wss://api.humalike.com/v1/ws/turn-taking-thread?grant=[REDACTED]";
}
console.log(`OBSERVATIONS ${JSON.stringify(redacted)}`);

const passed = results.filter((result) => result.pass).length;
const failed = results.length - passed;
console.log(`SUMMARY ${passed} passed, ${failed} failed`);
console.log(`CREDITS ${JSON.stringify(observations.billing.delta)}`);
if (creditsDepleted) console.error("CREDITS DEPLETED: billable checks stopped after HTTP 402");
process.exitCode = failed ? 1 : 0;
