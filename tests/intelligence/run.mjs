#!/usr/bin/env node

import process from "node:process";
import { randomUUID } from "node:crypto";

const BASE_URL = (process.env.HUMALIKE_API_URL || "https://api.humalike.com").replace(/\/$/, "");
const API_KEY = process.env.HUMALIKE_API_KEY;
const POLL_MS = Number(process.env.HUMALIKE_POLL_MS ?? 3000);
const JOB_TIMEOUT_MS = Number(process.env.HUMALIKE_JOB_TIMEOUT_MS ?? 12 * 60_000);
const AUDIT_TIMEOUT_MS = Number(process.env.HUMALIKE_AUDIT_TIMEOUT_MS ?? 20 * 60_000);

if (!API_KEY) {
  console.error("HUMALIKE_API_KEY is required");
  process.exit(2);
}

// Values pinned from earlier live runs. Anything here is asserted exactly; anything
// recorded with learn() but absent here is reported under LEARNED for pinning.
const PINNED = {
  validation_message: "request validation failed",
  invalid_id_message: "invalid id",
  unknown_run_message: "unknown run",
  unknown_run_detail: { field: "run_id", message: "no such run" },
  nonparticipant_message: "agent_name must be one of the transcript's speakers",
  nonparticipant_detail: "'support-bot-typo' never speaks",
  unparsable_message: "no messages could be read from this text",
  unparsable_detail: { field: "raw_text", message: "no messages detected" },
  too_many_messages_message: "This transcript has 251 messages; the audit accepts at most 250.",
  too_many_messages_detail: { field: "raw_text", message: "over the 250-message cap" },
  oversized_message: "This paste is too large to read: about 120,300 tokens, and the audit accepts about 32,768. Send at most 250 messages.",
  oversized_detail: { field: "raw_text", message: "at most ~32768 tokens allowed" },
  non_applicable_detail: "0 applicable constraint(s) passed",
  schema_fail_detail: "hours='unknown' is not numeric",
  constraints_fail_detail: "age_nonnegative: age=-3 >= 0 (0)",
  enhance_initial_status: "pending",
  population_phases: ["designing", "generating", "complete"],
  evaluation_phases: ["evaluating", "complete"], // short single-persona runs skip straight to "complete"
  audit_launch_repeat_status: "queued",
  audit_launch_terminal_status: "completed",
  audit_message_id_pattern: /^m[1-9][0-9]*$/,
  audit_verdict_indexes: [1, 3, 5], // 0-based positions of the agent's turns in transcript.messages
  audit_risk_vocabulary: ["low", "medium", "high"],
  foresee_subject_name: "customer",
  meta_channels: ["lounge", "unlabelled"],
  interaction_types: ["transactional", "bonding", "venting", "banter", "friction", "hostile"],
  component_slugs: ["personas", "social-learning", "social-memory", "social-observability", "theoryofmind", "turn-taking"],
  scorecard_gate_names: ["schema", "constraints"],
  batch_gate_names: ["max_pairwise_similarity"], // plus one `marginal_tvd:<attribute>` per marginal
  soft_score_keys: ["voice_attribution"], // sparse: a scorecard may carry any subset, including none
  generated_persona_id_pattern: /^p\d{4}$/,
  enhanced_persona_id_pattern: /^enhanced-[0-9a-f]{12}$/,
  generated_markdown_prefix: "# Persona\n",
  generated_system_prompt_prefix: "You are the person described below. Stay in character, speak in their voice, and never break character or mention being an AI.",
  enhancement_source_section: "USER-PROVIDED AGENT INFORMATION\nUse this as high-priority context for identity, preferences, and behavior:\n",
  enhancement_markdown_prefix: "CHARACTER PROFILE\n",
};

let passed = 0;
let failed = 0;
let skipped = 0;
let creditDepleted = false;
const calls = [];
const jobTimings = {};
const learned = {};
const ranges = {};

function pass(name) {
  passed += 1;
  console.log(`PASS ${name}`);
}

function fail(name, detail) {
  failed += 1;
  console.error(`FAIL ${name}: ${detail}`);
}

function skip(name, detail) {
  skipped += 1;
  console.log(`SKIP ${name}: ${detail}`);
}

function check(name, condition, detail = "assertion failed") {
  if (condition) pass(name);
  else fail(name, detail);
  return Boolean(condition);
}

function equal(name, actual, expected) {
  return check(name, Object.is(actual, expected), `expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (isObject(value)) return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  return JSON.stringify(value);
}

function deepEqual(name, actual, expected) {
  return check(name, canonical(actual) === canonical(expected), `expected ${canonical(expected)}, got ${canonical(actual)}`);
}

function sameSet(actual, expected) {
  return Array.isArray(actual) && actual.length === expected.length && [...actual].sort().join("\u0000") === [...expected].sort().join("\u0000");
}

function learn(name, value) {
  learned[name] = value;
  console.log(`LEARNED ${name} ${JSON.stringify(redact(value))}`);
}

function track(name, value) {
  if (typeof value !== "number" || Number.isNaN(value)) return;
  const entry = ranges[name] ?? { min: value, max: value, n: 0 };
  entry.min = Math.min(entry.min, value);
  entry.max = Math.max(entry.max, value);
  entry.n += 1;
  ranges[name] = entry;
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

const isStr = (value) => typeof value === "string";
const isNonEmptyStr = (value) => typeof value === "string" && value.length > 0;
const isNum = (value) => typeof value === "number" && Number.isFinite(value);
const isUnit = (value) => isNum(value) && value >= 0 && value <= 1;
const strArr = (value) => Array.isArray(value) && value.every(isStr);
const isIso = (value) => isStr(value) && !Number.isNaN(Date.parse(value));
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const isUuid = (value) => isStr(value) && UUID_RE.test(value);

function hasExactKeys(value, required, optional = []) {
  if (!isObject(value)) return false;
  const keys = Object.keys(value).sort();
  const allowed = new Set([...required, ...optional]);
  return required.every((key) => keys.includes(key)) && keys.every((key) => allowed.has(key));
}

function valuesAreStrings(value) {
  return isObject(value) && Object.values(value).every((item) => typeof item === "string");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function redact(value) {
  if (typeof value === "string") {
    return value.replace(/ak_[A-Za-z0-9_-]+/g, "<redacted>");
  }
  if (Array.isArray(value)) return value.map(redact);
  if (isObject(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [
      /authorization|token|api.?key/i.test(key) ? "<redacted-key>" : key,
      /authorization|token|api.?key/i.test(key) ? "<redacted>" : redact(item),
    ]));
  }
  return value;
}

function observe(label, value) {
  console.log(`OBSERVED ${label} ${JSON.stringify(redact(value), null, 2)}`);
}

class HttpError extends Error {
  constructor(label, response) {
    super(`${label} returned HTTP ${response.status}`);
    this.response = response;
  }
}

// A connect timeout means the TCP connection was never established, so the
// request was never sent and retrying cannot double-bill or double-ingest.
function isConnectTimeout(error) {
  let cause = error;
  for (let depth = 0; cause && depth < 4; depth += 1) {
    if (cause.code === "UND_ERR_CONNECT_TIMEOUT") return true;
    cause = cause.cause;
  }
  return false;
}

async function fetchWithConnectRetry(url, init, attempts = 3) {
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

async function request(label, method, path, body, { timeoutMs = 180_000, billable = false, auth = true } = {}) {
  if (billable && creditDepleted) {
    skip(label, "billable call suppressed after HTTP 402");
    return null;
  }

  const started = Date.now();
  let response;
  try {
    response = await fetchWithConnectRetry(`${BASE_URL}${path}`, {
      method,
      headers: {
        ...(auth ? { Authorization: `Bearer ${API_KEY}` } : {}),
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    fail(`${label} transport`, error.message);
    throw error;
  }

  const text = await response.text();
  let data;
  try {
    data = text === "" ? null : JSON.parse(text);
  } catch {
    data = text;
  }

  const headers = Object.fromEntries(response.headers.entries());
  const elapsedMs = Date.now() - started;
  const record = { label, method, path, status: response.status, elapsed_ms: elapsedMs, headers, body: data };
  calls.push(record);
  console.log(`CALL ${label} ${response.status} ${elapsedMs}ms request-id=${headers["x-request-id"] ?? "<absent>"}`);
  observe(label, { status: response.status, elapsed_ms: elapsedMs, headers, body: data });

  if (response.status === 402) {
    creditDepleted = true;
    fail(`${label} credits`, "HTTP 402 PAYMENT_REQUIRED");
  }

  return record;
}

function assertRequestMetadata(record) {
  if (!record) return;
  check(`${record.label} returns x-request-id`, isNonEmptyStr(record.headers["x-request-id"]));
  check(`${record.label} content-type json`, isStr(record.headers["content-type"]) && record.headers["content-type"].startsWith("application/json"), record.headers["content-type"]);
}

function assertUnauthorized(record) {
  if (!record) return;
  assertRequestMetadata(record);
  equal(`${record.label} status`, record.status, 401);
  deepEqual(`${record.label} exact body`, record.body, { error: { code: "UNAUTHORIZED", message: "missing or invalid credentials" } });
}

// Request-model (Pydantic-style) failure: HTTP 422, lowercase code, fixed message, {loc,msg,type} details.
function assertRequestValidation(record, expectations = []) {
  if (!record) return;
  equal(`${record.label} status`, record.status, 422);
  check(`${record.label} error envelope`, hasExactKeys(record.body, ["error"]) && hasExactKeys(record.body.error, ["code", "message", "details"]));
  equal(`${record.label} error code`, record.body?.error?.code, "validation_failed");
  equal(`${record.label} error message`, record.body?.error?.message, PINNED.validation_message);
  const details = record.body?.error?.details;
  check(`${record.label} detail shape`, Array.isArray(details) && details.length >= 1 && details.every(
    (detail) => hasExactKeys(detail, ["loc", "msg", "type"])
      && Array.isArray(detail.loc)
      && detail.loc.every((item) => isStr(item) || Number.isInteger(item))
      && detail.loc[0] !== "body"
      && isNonEmptyStr(detail.msg)
      && isNonEmptyStr(detail.type),
  ), JSON.stringify(details));
  for (const { loc, type, msg } of expectations) {
    const detail = (details ?? []).find((item) => Array.isArray(item.loc) && item.loc.join(".") === loc);
    check(`${record.label} detail at ${loc}`, detail !== undefined, JSON.stringify(details));
    if (type !== undefined) equal(`${record.label} detail type at ${loc}`, detail?.type, type);
    if (msg !== undefined) equal(`${record.label} detail msg at ${loc}`, detail?.msg, msg);
  }
  if (expectations.length) {
    equal(`${record.label} detail count`, details?.length, expectations.length);
  }
}

// Semantic failure: HTTP 400, uppercase code, route-specific message and optional {field,message} details.
function assertSemanticValidation(record, { message, details } = {}) {
  if (!record) return;
  equal(`${record.label} status`, record.status, 400);
  check(`${record.label} error envelope`, hasExactKeys(record.body, ["error"]) && hasExactKeys(record.body.error, ["code", "message"], ["details"]));
  equal(`${record.label} error code`, record.body?.error?.code, "VALIDATION_ERROR");
  if (message === undefined) {
    check(`${record.label} error message`, isNonEmptyStr(record.body?.error?.message));
    learn(`${record.label} message`, record.body?.error?.message);
  } else {
    equal(`${record.label} error message`, record.body?.error?.message, message);
  }
  if (details === null) {
    check(`${record.label} has no details`, record.body?.error?.details === undefined);
  } else if (details !== undefined) {
    deepEqual(`${record.label} details`, record.body?.error?.details, details);
  } else {
    learn(`${record.label} details`, record.body?.error?.details);
  }
}

function assertPersona(label, persona, { allowEmptyFields = false } = {}) {
  check(`${label} exact resource keys`, hasExactKeys(persona, ["persona_id", "fields", "system_prompt", "markdown"]));
  check(`${label} persona_id`, isNonEmptyStr(persona?.persona_id));
  check(`${label} flat string fields`, valuesAreStrings(persona?.fields)
    && (allowEmptyFields || Object.keys(persona.fields).length > 0));
  check(`${label} system_prompt`, isNonEmptyStr(persona?.system_prompt));
  check(`${label} markdown`, isNonEmptyStr(persona?.markdown));
}

function assertDistribution(label, distribution) {
  check(`${label} numeric distribution`, hasExactKeys(distribution, ["min", "max", "mean", "sd", "integer"])
    && ["min", "max", "mean", "sd"].every((key) => isNum(distribution[key]))
    && typeof distribution.integer === "boolean"
    && distribution.min <= distribution.max);
}

function assertWeights(label, categorical) {
  check(label, hasExactKeys(categorical, ["weights"])
    && isObject(categorical.weights)
    && Object.keys(categorical.weights).length > 0
    && Object.values(categorical.weights).every((weight) => isNum(weight) && weight >= 0));
}

function assertBlueprint(label, blueprint) {
  check(`${label} blueprint keys`, hasExactKeys(
    blueprint,
    ["domain", "language", "order", "fields", "constraints", "style_axes", "name_origins", "rationale", "sources"],
  ));
  check(`${label} domain`, isNonEmptyStr(blueprint?.domain));
  check(`${label} language`, isStr(blueprint?.language));
  check(`${label} order`, strArr(blueprint?.order));
  check(`${label} fields`, Array.isArray(blueprint?.fields) && blueprint.fields.length > 0);
  const fieldNames = (blueprint?.fields ?? []).map((field) => field?.name);
  check(`${label} field names unique`, new Set(fieldNames).size === fieldNames.length);
  check(`${label} order within fields`, (blueprint?.order ?? []).every((name) => fieldNames.includes(name)), JSON.stringify(blueprint?.order));
  for (const [index, field] of (blueprint?.fields ?? []).entries()) {
    const fieldLabel = `${label} field[${index}]`;
    check(`${fieldLabel} base schema`, hasExactKeys(
      field,
      ["name", "label", "kind", "description", "formula", "parents", "categorical", "numeric", "conditionals", "ordered_values"],
    ));
    check(`${fieldLabel} strings`, isNonEmptyStr(field?.name) && isStr(field?.label) && isStr(field?.description) && isStr(field?.formula));
    check(`${fieldLabel} kind`, ["categorical", "numeric", "text", "derived"].includes(field?.kind));
    check(`${fieldLabel} parents`, strArr(field?.parents) && field.parents.every((parent) => fieldNames.includes(parent)));
    check(`${fieldLabel} ordered_values`, field?.ordered_values === null || strArr(field?.ordered_values));
    // Sampled fields carry their distribution at top level or, when fully conditional on parents, only inside conditionals.
    const conditionals = Array.isArray(field?.conditionals) ? field.conditionals : [];
    const categoricalCovered = field?.categorical !== null || (conditionals.length > 0 && conditionals.every((conditional) => conditional?.categorical !== null));
    const numericCovered = field?.numeric !== null || (conditionals.length > 0 && conditionals.every((conditional) => conditional?.numeric !== null));
    check(`${fieldLabel} distribution matches kind`,
      (field?.kind === "categorical" && field.numeric === null && categoricalCovered)
      || (field?.kind === "numeric" && field.categorical === null && numericCovered)
      || ((field?.kind === "text" || field?.kind === "derived") && field.categorical === null && field.numeric === null && conditionals.length === 0),
    JSON.stringify({ kind: field?.kind, categorical: field?.categorical !== null, numeric: field?.numeric !== null, conditionals: conditionals.length }));
    if (field?.categorical !== null && field?.categorical !== undefined) assertWeights(`${fieldLabel} categorical`, field.categorical);
    if (field?.numeric !== null && field?.numeric !== undefined) assertDistribution(`${fieldLabel} numeric`, field.numeric);
    check(`${fieldLabel} conditionals`, Array.isArray(field?.conditionals));
    for (const [conditionalIndex, conditional] of (field?.conditionals ?? []).entries()) {
      const conditionalLabel = `${fieldLabel} conditional[${conditionalIndex}]`;
      check(conditionalLabel, hasExactKeys(conditional, ["when", "categorical", "numeric"])
        && isObject(conditional.when)
        && Object.keys(conditional.when).length > 0
        && Object.keys(conditional.when).every((parent) => fieldNames.includes(parent))
        && valuesAreStrings(conditional.when));
      if (conditional.categorical !== null) assertWeights(`${conditionalLabel} categorical`, conditional.categorical);
      if (conditional.numeric !== null) assertDistribution(`${conditionalLabel} numeric`, conditional.numeric);
    }
  }
  check(`${label} constraints`, Array.isArray(blueprint?.constraints));
  for (const [index, constraint] of (blueprint?.constraints ?? []).entries()) {
    check(`${label} constraint[${index}]`, hasExactKeys(constraint, ["name", "lhs", "op", "rhs"])
      && [constraint.name, constraint.lhs, constraint.op, constraint.rhs].every(isStr));
  }
  check(`${label} style_axes`, isObject(blueprint?.style_axes) && Object.values(blueprint.style_axes).every(strArr));
  check(`${label} name_origins`, strArr(blueprint?.name_origins));
  check(`${label} rationale`, isStr(blueprint?.rationale));
  check(`${label} sources`, strArr(blueprint?.sources));
}

function assertDiversity(label, diversity) {
  check(`${label} exact diversity schema`, hasExactKeys(
    diversity,
    ["max_pairwise_similarity", "mean_pairwise_similarity", "duplicate_pairs"],
  ));
  check(`${label} diversity values`, isUnit(diversity?.max_pairwise_similarity)
    && isUnit(diversity?.mean_pairwise_similarity)
    && diversity.mean_pairwise_similarity <= diversity.max_pairwise_similarity
    && Number.isInteger(diversity?.duplicate_pairs) && diversity.duplicate_pairs >= 0);
  track("diversity.max_pairwise_similarity", diversity?.max_pairwise_similarity);
  track("diversity.mean_pairwise_similarity", diversity?.mean_pairwise_similarity);
}

function assertMarginals(label, marginals) {
  check(`${label} marginals`, Array.isArray(marginals));
  for (const [index, marginal] of (marginals ?? []).entries()) {
    check(`${label} marginal[${index}] schema`, hasExactKeys(marginal, ["attribute", "cells", "total_variation_distance"])
      && isNonEmptyStr(marginal.attribute)
      && isUnit(marginal.total_variation_distance));
    check(`${label} marginal[${index}] cells`, Array.isArray(marginal.cells) && marginal.cells.length > 0 && marginal.cells.every(
      (cell) => hasExactKeys(cell, ["key", "requested", "achieved"])
        && isStr(cell.key)
        && isNum(cell.requested) && cell.requested >= 0
        && isNum(cell.achieved) && cell.achieved >= 0,
    ));
    track("marginal.total_variation_distance", marginal.total_variation_distance);
    for (const cell of marginal.cells ?? []) {
      track("marginal.cell.requested", cell.requested);
      track("marginal.cell.achieved", cell.achieved);
    }
  }
}

function assertReport(label, report, { inputIds, participants, userIds } = {}) {
  check(`${label} exact top-level schema`, hasExactKeys(
    report,
    ["health_score", "summary", "interactions", "interaction_totals", "per_user", "findings"],
  ));
  check(`${label} health_score`, isUnit(report?.health_score));
  track("report.health_score", report?.health_score);
  check(`${label} summary`, isNonEmptyStr(report?.summary));
  check(`${label} interactions`, Array.isArray(report?.interactions) && report.interactions.length > 0);
  const idSet = inputIds ? new Set(inputIds) : null;
  const idsKnown = (ids) => Array.isArray(ids) && (idSet === null || ids.every((id) => idSet.has(id)));
  for (const [index, interaction] of (report?.interactions ?? []).entries()) {
    check(`${label} interaction[${index}]`, hasExactKeys(interaction, ["type", "topic", "participants", "message_ids"])
      && PINNED.interaction_types.includes(interaction.type)
      && isNonEmptyStr(interaction.topic)
      && Array.isArray(interaction.participants) && interaction.participants.length > 0
      && interaction.participants.every((participant) => hasExactKeys(participant, ["name", "stance"], ["user_id"])
        && isNonEmptyStr(participant.name) && isStr(participant.stance)
        && (participant.user_id === undefined || isStr(participant.user_id))
        && (!participants || participants.includes(participant.name)))
      && strArr(interaction.message_ids) && interaction.message_ids.length > 0 && idsKnown(interaction.message_ids), JSON.stringify(interaction));
  }
  const totals = report?.interaction_totals;
  check(`${label} interaction_totals`, Array.isArray(totals)
    && sameSet(totals.map((item) => item?.type), PINNED.interaction_types)
    && totals.every((item) => hasExactKeys(item, ["type", "count"]) && Number.isInteger(item.count) && item.count >= 0), JSON.stringify(totals));
  check(`${label} interaction_totals sum`, Array.isArray(totals) && totals.reduce((sum, item) => sum + (item?.count ?? 0), 0) === (report?.interactions?.length ?? -1));
  check(`${label} interaction_totals consistent`, Array.isArray(totals) && totals.every((item) =>
    item.count === (report?.interactions ?? []).filter((interaction) => interaction.type === item.type).length));
  check(`${label} per_user`, Array.isArray(report?.per_user) && report.per_user.length > 0);
  for (const [index, user] of (report?.per_user ?? []).entries()) {
    check(`${label} per_user[${index}]`, hasExactKeys(
      user,
      ["name", "reception", "frustration", "trend", "behaviors", "evidence", "confidence", "interaction_count", "dominant_type", "distribution", "key_moments"],
      ["user_id", "note"],
    ));
    check(`${label} per_user[${index}] enums`, ["engaged", "neutral", "bored", "annoyed", "churn_risk"].includes(user.reception)
      && ["improving", "stable", "declining"].includes(user.trend));
    check(`${label} per_user[${index}] name`, isNonEmptyStr(user.name) && (!participants || participants.includes(user.name)));
    check(`${label} per_user[${index}] scalars`, isUnit(user.frustration) && isUnit(user.confidence)
      && strArr(user.behaviors) && strArr(user.evidence) && idsKnown(user.evidence)
      && (user.note === undefined || isStr(user.note))
      && Number.isInteger(user.interaction_count) && user.interaction_count >= 0
      && isStr(user.dominant_type), JSON.stringify({ frustration: user.frustration, confidence: user.confidence, evidence: user.evidence }));
    track("report.per_user.frustration", user.frustration);
    track("report.per_user.confidence", user.confidence);
    if (userIds === null) {
      equal(`${label} per_user[${index}] user_id null`, user.user_id, null);
    } else if (userIds && userIds[user.name] !== undefined) {
      equal(`${label} per_user[${index}] user_id echo`, user.user_id, userIds[user.name]);
    } else {
      check(`${label} per_user[${index}] user_id`, user.user_id === undefined || user.user_id === null || isStr(user.user_id));
    }
    check(`${label} per_user[${index}] dominant_type`, PINNED.interaction_types.includes(user.dominant_type) || user.interaction_count === 0, user.dominant_type);
    check(`${label} per_user[${index}] distribution`, Array.isArray(user.distribution)
      && sameSet(user.distribution.map((item) => item?.type), PINNED.interaction_types)
      && user.distribution.every((item) => hasExactKeys(item, ["type", "count"]) && Number.isInteger(item.count) && item.count >= 0)
      && user.distribution.reduce((sum, item) => sum + item.count, 0) === user.interaction_count, JSON.stringify(user.distribution));
    const participated = (report?.interactions ?? []).filter((interaction) => interaction.participants.some((participant) => participant.name === user.name)).length;
    check(`${label} per_user[${index}] interaction_count matches participation`, user.interaction_count === participated, `${user.interaction_count} vs ${participated}`);
    check(`${label} per_user[${index}] key moments`, Array.isArray(user.key_moments)
      && user.key_moments.every((item) => hasExactKeys(item, ["label", "type", "message_ids"], ["agent_critique"])
        && isNonEmptyStr(item.label) && isStr(item.type)
        && strArr(item.message_ids) && idsKnown(item.message_ids)
        && (item.agent_critique === undefined || isStr(item.agent_critique))), JSON.stringify(user.key_moments));
  }
  check(`${label} findings`, Array.isArray(report?.findings));
  for (const [index, finding] of (report?.findings ?? []).entries()) {
    check(`${label} finding[${index}]`, hasExactKeys(
      finding,
      ["issue", "severity", "affected_users", "evidence", "recommendation", "confidence"],
      ["before_message_id", "rewritten_reply", "suggested_component", "how_it_helps"],
    ) && ["low", "medium", "high"].includes(finding.severity)
      && isNonEmptyStr(finding.issue) && isNonEmptyStr(finding.recommendation)
      && strArr(finding.affected_users) && (!participants || finding.affected_users.every((name) => participants.includes(name)))
      && strArr(finding.evidence) && idsKnown(finding.evidence)
      && isUnit(finding.confidence)
      && (finding.before_message_id === undefined || (isStr(finding.before_message_id) && idsKnown([finding.before_message_id])))
      && (finding.rewritten_reply === undefined || isStr(finding.rewritten_reply))
      && (finding.suggested_component === undefined || isStr(finding.suggested_component))
      && (finding.how_it_helps === undefined || isStr(finding.how_it_helps)), JSON.stringify(finding));
    track("report.finding.confidence", finding.confidence);
  }
  learn(`${label} key_moment types`, [...new Set((report?.per_user ?? []).flatMap((user) => user.key_moments.map((item) => item.type)))]);
  learn(`${label} suggested_components`, [...new Set((report?.findings ?? []).map((finding) => finding.suggested_component).filter(Boolean))]);
}

function assertMentalStates(label, states) {
  check(label, Array.isArray(states) && states.every((state) => hasExactKeys(state, ["name", "beliefs", "goals", "emotions"])
    && isNonEmptyStr(state.name)
    && strArr(state.beliefs)
    && strArr(state.goals)
    && Array.isArray(state.emotions)
    && state.emotions.every((emotion) => hasExactKeys(emotion, ["type", "intensity"])
      && isNonEmptyStr(emotion.type) && isUnit(emotion.intensity))), JSON.stringify(states));
  for (const state of states ?? []) for (const emotion of state.emotions ?? []) track("mental_state.emotion.intensity", emotion.intensity);
}

function assertProfile(label, profile, { messageCount, source }) {
  check(`${label} profile exact top-level schema`, hasExactKeys(
    profile,
    ["summary", "register", "style", "lexicon", "banned_phrases", "address", "taboos", "humor", "roles", "norms", "in_jokes", "meta"],
  ));
  check(`${label} profile summary`, isStr(profile?.summary)); // may be "" for sparse transcripts
  check(`${label} profile register`, hasExactKeys(profile?.register, ["formality", "warmth", "casing", "notes", "confidence"])
    && ["formality", "warmth", "casing", "notes"].every((key) => isStr(profile.register[key]))
    && isUnit(profile.register.confidence));
  track("profile.register.confidence", profile?.register?.confidence);
  check(`${label} profile style`, hasExactKeys(profile?.style, ["length", "formatting", "emoji"])
    && ["length", "formatting", "emoji"].every((key) => isStr(profile.style[key])));
  check(`${label} profile collection fields`, ["lexicon", "banned_phrases", "taboos", "roles", "norms", "in_jokes"]
    .every((key) => Array.isArray(profile?.[key])));
  check(`${label} profile address schema`, hasExactKeys(profile?.address, ["default", "deference"])
    && isStr(profile.address.default)
    && Array.isArray(profile.address.deference));
  check(`${label} profile humor schema`, hasExactKeys(profile?.humor, ["style", "rules"])
    && isStr(profile.humor.style)
    && strArr(profile.humor.rules));
  check(`${label} profile lexicon item schema`, (profile?.lexicon ?? []).every((item) => hasExactKeys(item, ["term", "meaning", "usage"])
    && [item.term, item.meaning, item.usage].every(isStr)));
  check(`${label} profile taboo item schema`, (profile?.taboos ?? []).every((item) => hasExactKeys(item, ["rule", "scope", "evidence"])
    && isStr(item.rule) && isStr(item.scope) && strArr(item.evidence)));
  check(`${label} profile norm item schema`, (profile?.norms ?? []).every((item) => hasExactKeys(item, ["rule", "type", "evidence", "confidence"])
    && isStr(item.rule) && isStr(item.type) && isUnit(item.confidence)
    && Array.isArray(item.evidence)
    && item.evidence.every((evidence) => hasExactKeys(evidence, ["breach", "sanction"]) && isStr(evidence.breach) && isStr(evidence.sanction))));
  for (const norm of profile?.norms ?? []) track("profile.norm.confidence", norm.confidence);
  check(`${label} profile meta`, hasExactKeys(profile?.meta, ["source", "channels", "message_count"])
    && profile.meta.source === source
    && profile.meta.message_count === messageCount
    && strArr(profile.meta.channels));
  learn(`${label} banned_phrases/roles/in_jokes/deference samples`, {
    banned_phrases: profile?.banned_phrases, roles: profile?.roles, in_jokes: profile?.in_jokes, deference: profile?.address?.deference,
  });
  learn(`${label} norm types`, [...new Set((profile?.norms ?? []).map((norm) => norm.type))]);
  learn(`${label} taboo scopes`, [...new Set((profile?.taboos ?? []).map((taboo) => taboo.scope))]);
}

function assertPopulationResource(label, resource, { id, prompt, count, grounding } = {}) {
  check(`${label} resource schema`, hasExactKeys(
    resource,
    ["id", "created_at", "updated_at", "status", "progress", "prompt", "count", "grounding", "result", "error"],
  ));
  check(`${label} id`, isUuid(resource?.id) && (id === undefined || resource.id === id));
  check(`${label} timestamps`, isIso(resource?.created_at) && isIso(resource?.updated_at)
    && Date.parse(resource.updated_at) >= Date.parse(resource.created_at));
  check(`${label} status`, ["pending", "running", "succeeded", "failed"].includes(resource?.status));
  check(`${label} request echo`, resource?.prompt === (prompt ?? resource?.prompt)
    && resource?.count === (count ?? resource?.count)
    && resource?.grounding === (grounding ?? resource?.grounding)
    && isStr(resource?.prompt) && Number.isInteger(resource?.count) && ["off", "web", "research"].includes(resource?.grounding));
  if (resource?.progress !== null) {
    check(`${label} progress schema`, hasExactKeys(resource?.progress, ["phase", "produced", "total"])
      && isNonEmptyStr(resource.progress.phase)
      && Number.isInteger(resource.progress.produced)
      && Number.isInteger(resource.progress.total)
      && resource.progress.produced <= resource.progress.total
      && (count === undefined || resource.progress.total === count));
  }
  if (["pending", "running"].includes(resource?.status)) {
    check(`${label} non-terminal result/error null`, resource.result === null && resource.error === null);
  }
  if (resource?.status === "succeeded") {
    check(`${label} terminal error null`, resource.error === null);
  }
}

function assertEnhancementResource(label, resource, { id, source, grounding } = {}) {
  check(`${label} resource schema`, hasExactKeys(
    resource,
    ["id", "created_at", "updated_at", "status", "source", "grounding", "persona", "error"],
  ));
  check(`${label} id`, isUuid(resource?.id) && (id === undefined || resource.id === id));
  check(`${label} timestamps`, isIso(resource?.created_at) && isIso(resource?.updated_at)
    && Date.parse(resource.updated_at) >= Date.parse(resource.created_at));
  check(`${label} status`, ["pending", "running", "succeeded", "failed"].includes(resource?.status));
  check(`${label} request echo`, resource?.source === (source ?? resource?.source)
    && resource?.grounding === (grounding ?? resource?.grounding)
    && isStr(resource?.source) && ["off", "web", "research"].includes(resource?.grounding));
  if (["pending", "running"].includes(resource?.status)) {
    check(`${label} non-terminal persona/error null`, resource.persona === null && resource.error === null);
  }
}

function assertEvaluationResource(label, resource, { id, personas, blueprint } = {}) {
  check(`${label} resource schema`, hasExactKeys(
    resource,
    ["id", "created_at", "updated_at", "status", "progress", "personas", "blueprint", "result", "error"],
  ));
  check(`${label} id`, isUuid(resource?.id) && (id === undefined || resource.id === id));
  check(`${label} timestamps`, isIso(resource?.created_at) && isIso(resource?.updated_at)
    && Date.parse(resource.updated_at) >= Date.parse(resource.created_at));
  check(`${label} status`, ["pending", "running", "succeeded", "failed"].includes(resource?.status));
  check(`${label} input echoes`, Array.isArray(resource?.personas) && (resource?.blueprint === null || isObject(resource?.blueprint)));
  if (personas !== undefined) deepEqual(`${label} personas echo`, resource?.personas, personas);
  if (blueprint === null) equal(`${label} blueprint null`, resource?.blueprint, null);
  if (resource?.progress !== null) {
    check(`${label} progress schema`, hasExactKeys(resource?.progress, ["phase"]) && isNonEmptyStr(resource.progress.phase));
  }
  if (["pending", "running"].includes(resource?.status)) {
    check(`${label} non-terminal result/error null`, resource.result === null && resource.error === null);
  }
  if (resource?.status === "succeeded") {
    check(`${label} terminal error null`, resource.error === null);
  }
}

function assertEvaluation(label, evaluation, { singlePersona = false } = {}) {
  const result = evaluation?.result;
  check(`${label} result schema`, hasExactKeys(
    result,
    ["passed", "gates", "scorecards", "diversity", "marginals", "notes"],
  ));
  check(`${label} passed boolean`, typeof result?.passed === "boolean");
  const gateSchema = (gate) => hasExactKeys(gate, ["name", "passed", "score", "detail"])
    && isNonEmptyStr(gate.name)
    && typeof gate.passed === "boolean"
    && (gate.score === null || isNum(gate.score))
    && isStr(gate.detail);
  check(`${label} batch gates`, Array.isArray(result?.gates) && result.gates.every(gateSchema));
  learn(`${label} batch gates`, result?.gates);
  check(`${label} scorecards`, Array.isArray(result?.scorecards) && result.scorecards.every(
    (card) => hasExactKeys(card, ["persona_id", "gates", "soft_scores"])
      && isNonEmptyStr(card.persona_id)
      && Array.isArray(card.gates)
      && card.gates.every(gateSchema)
      && isObject(card.soft_scores)
      && Object.values(card.soft_scores).every(isNum),
  ));
  if (evaluation?.blueprint === null) {
    deepEqual(`${label} no scorecards without blueprint`, result?.scorecards, []);
    deepEqual(`${label} no batch gates without blueprint`, result?.gates, []);
  } else {
    check(`${label} scorecard ids match personas`, Array.isArray(result?.scorecards)
      && sameSet(result.scorecards.map((card) => card.persona_id), (evaluation?.personas ?? []).map((persona) => persona.persona_id)));
  }
  for (const [index, card] of (result?.scorecards ?? []).entries()) {
    check(`${label} scorecard[${index}] gate names`, sameSet(card.gates.map((gate) => gate.name), PINNED.scorecard_gate_names), JSON.stringify(card.gates.map((gate) => gate.name)));
    check(`${label} scorecard[${index}] soft score keys`, Object.keys(card.soft_scores).every((key) => PINNED.soft_score_keys.includes(key))
      && Object.values(card.soft_scores).every(isUnit), JSON.stringify(card.soft_scores));
    for (const [key, value] of Object.entries(card.soft_scores)) track(`soft_scores.${key}`, value);
    for (const gate of card.gates) if (gate.score !== null) track(`gate.${gate.name}.score`, gate.score);
  }
  const passedGates = (result?.gates ?? []).every((gate) => gate.passed) && (result?.scorecards ?? []).every((card) => card.gates.every((gate) => gate.passed));
  equal(`${label} passed equals all gates passed`, result?.passed, passedGates);
  if (singlePersona) {
    equal(`${label} single-persona diversity null`, result?.diversity, null);
    deepEqual(`${label} single-persona marginals empty`, result?.marginals, []);
    deepEqual(`${label} single-persona batch gates empty`, result?.gates, []);
  } else {
    assertDiversity(`${label} result`, result?.diversity);
    assertMarginals(`${label} result`, result?.marginals);
    const expectedBatchGates = [...PINNED.batch_gate_names, ...(result?.marginals ?? []).map((marginal) => `marginal_tvd:${marginal.attribute}`)];
    check(`${label} batch gate names`, sameSet((result?.gates ?? []).map((gate) => gate.name), expectedBatchGates), JSON.stringify((result?.gates ?? []).map((gate) => gate.name)));
    const similarityGate = (result?.gates ?? []).find((gate) => gate.name === "max_pairwise_similarity");
    equal(`${label} similarity gate score`, similarityGate?.score, result?.diversity?.max_pairwise_similarity);
    check(`${label} marginal gate scores`, (result?.marginals ?? []).every((marginal) =>
      (result?.gates ?? []).find((gate) => gate.name === `marginal_tvd:${marginal.attribute}`)?.score === marginal.total_variation_distance));
  }
  check(`${label} notes`, strArr(result?.notes));
  learn(`${label} notes`, result?.notes);
}

async function pollGet(label, path, terminal, timeoutMs = JOB_TIMEOUT_MS, validatePoll = undefined) {
  const started = Date.now();
  const states = [];
  const phases = [];
  for (;;) {
    const record = await request(`${label} poll`, "GET", path, undefined, { timeoutMs: 60_000 });
    if (!record) return null;
    assertRequestMetadata(record);
    if (record.status !== 200) throw new HttpError(label, record);
    if (validatePoll) validatePoll(record.body);
    const state = JSON.stringify({ status: record.body?.status, progress: record.body?.progress });
    if (!states.includes(state)) states.push(state);
    const phase = record.body?.progress?.phase;
    if (phase !== undefined && phases[phases.length - 1] !== phase) phases.push(phase);
    if (terminal(record.body)) {
      jobTimings[label] = { elapsed_ms: Date.now() - started, states: states.map(JSON.parse), phases };
      observe(`${label} lifecycle`, jobTimings[label]);
      return record.body;
    }
    if (Date.now() - started > timeoutMs) throw new Error(`${label} timed out`);
    await sleep(POLL_MS);
  }
}

function assertPhaseSequence(label, phases, expected) {
  // Observed phases (in order, deduplicated) must be a subsequence of the pinned sequence and end on its last element.
  let cursor = 0;
  const subsequence = phases.every((phase) => {
    const next = expected.indexOf(phase, cursor);
    if (next === -1) return false;
    cursor = next + 1;
    return true;
  });
  check(`${label} phase sequence`, subsequence && phases[phases.length - 1] === expected[expected.length - 1], JSON.stringify(phases));
}

async function usageSummary(label) {
  const record = await request(label, "POST", "/v1/credits/projections/usage-summary", {});
  if (!record) return null;
  equal(`${label} status`, record.status, 200);
  assertRequestMetadata(record);
  check(`${label} schema`, hasExactKeys(record.body, ["total_calls", "total_credits", "per_component", "daily_series"])
    && Number.isInteger(record.body.total_calls) && Number.isInteger(record.body.total_credits)
    && Array.isArray(record.body.per_component)
    && record.body.per_component.every((item) => hasExactKeys(item, ["component", "calls", "credits"])
      && isNonEmptyStr(item.component) && Number.isInteger(item.calls) && Number.isInteger(item.credits))
    && Array.isArray(record.body.daily_series) && record.body.daily_series.length === 7
    && record.body.daily_series.every((item) => hasExactKeys(item, ["date", "requests"])
      && ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].includes(item.date) && Number.isInteger(item.requests)));
  check(`${label} component slugs known`, record.body.per_component.every((item) => PINNED.component_slugs.includes(item.component)),
    JSON.stringify(record.body.per_component.map((item) => item.component)));
  return record.body;
}

function usageDelta(start, end) {
  if (!start || !end) return null;
  const before = new Map(start.per_component.map((item) => [item.component, item]));
  const after = new Map(end.per_component.map((item) => [item.component, item]));
  const components = [...new Set([...before.keys(), ...after.keys()])].sort().map((component) => ({
    component,
    calls: (after.get(component)?.calls ?? 0) - (before.get(component)?.calls ?? 0),
    credits: (after.get(component)?.credits ?? 0) - (before.get(component)?.credits ?? 0),
  })).filter((item) => item.calls !== 0 || item.credits !== 0);
  return {
    total_calls: end.total_calls - start.total_calls,
    total_credits: end.total_credits - start.total_credits,
    per_component: components,
  };
}

const auditLines = (count, offset = 0) => Array.from({ length: count }, (_, index) => `[12:${String((index + offset) % 60).padStart(2, "0")}] ${index % 2 ? "support_bot" : "Casey"}: message ${index + 1}`).join("\n");

async function main() {
  const usageStart = await usageSummary("usage start");
  learn("component slugs", usageStart?.per_component?.map((item) => item.component));
  const terminalPollTargets = [];

  // --- Authentication (free) ---
  assertUnauthorized(await request("extract unauthenticated", "POST", "/v1/social-learning/actions/extract", { transcript: { messages: [{ id: "x", speaker: "a", text: "b" }] } }, { auth: false }));
  assertUnauthorized(await request("foresee unauthenticated", "POST", "/v1/foresee/actions/foresee", { transcript: [{ speaker: "a", text: "b" }], candidate_reply: "c" }, { auth: false }));
  assertUnauthorized(await request("analyze unauthenticated", "POST", "/v1/social-observability/actions/analyze", { agent_name: "a", transcript: { messages: [{ id: "x", speaker: "a", text: "b" }] } }, { auth: false }));
  assertUnauthorized(await request("audit prepare unauthenticated", "POST", "/v1/social-observability/actions/audit_prepare", { raw_text: "a: b" }, { auth: false }));
  assertUnauthorized(await request("generate unauthenticated", "POST", "/v1/personas/actions/generate", { prompt: "x", count: 1, grounding: "off" }, { auth: false }));
  assertUnauthorized(await request("population unauthenticated", "GET", `/v1/personas/repositories/Population/by-id/${randomUUID()}`, undefined, { auth: false }));

  // --- Social Learning ---
  const extractMissing = await request("extract missing transcript", "POST", "/v1/social-learning/actions/extract", {});
  assertRequestMetadata(extractMissing);
  assertRequestValidation(extractMissing, [{ loc: "transcript", type: "missing", msg: "Field required" }]);

  const extractEmpty = await request("extract empty transcript", "POST", "/v1/social-learning/actions/extract", {
    transcript: { messages: [] },
  });
  assertRequestMetadata(extractEmpty);
  assertRequestValidation(extractEmpty, [{ loc: "transcript.messages", type: "too_short", msg: "List should have at least 1 item after validation, not 0" }]);

  const extractUnknownField = await request("extract unknown field ignored", "POST", "/v1/social-learning/actions/extract", {
    transcript: { messages: [] },
    bogus: 1,
  });
  assertRequestMetadata(extractUnknownField);
  assertRequestValidation(extractUnknownField, [{ loc: "transcript.messages", type: "too_short" }]);

  const extractMissingId = await request("extract message missing id", "POST", "/v1/social-learning/actions/extract", {
    transcript: { messages: [{ speaker: "a", text: "b" }] },
  });
  assertRequestMetadata(extractMissingId);
  assertRequestValidation(extractMissingId, [{ loc: "transcript.messages.0.id", type: "missing", msg: "Field required" }]);

  const tinyExtract = await request("extract tiny", "POST", "/v1/social-learning/actions/extract", {
    transcript: { source: "live-contract-tiny", messages: [{ id: "t1", speaker: "Ada", text: "hello" }] },
  }, { billable: true });
  if (tinyExtract && tinyExtract.status === 200) {
    assertRequestMetadata(tinyExtract);
    check("extract tiny exact top-level schema", hasExactKeys(tinyExtract.body, ["prompt_block", "profile"]));
    check("extract tiny prompt block", isNonEmptyStr(tinyExtract.body.prompt_block));
    assertProfile("extract tiny", tinyExtract.body.profile, { messageCount: 1, source: "live-contract-tiny" });
    learn("extract tiny channels (model-authored; [] and [\"general\"] observed)", tinyExtract.body.profile?.meta?.channels);
  } else if (tinyExtract && tinyExtract.status !== 402) fail("extract tiny status", `HTTP ${tinyExtract.status}`);

  const richMessages = [
    { id: "r1", speaker: "Mira", text: "yo, tea run at 3?", channel: "lounge" },
    { id: "r2", speaker: "Sol", text: "yep yep jasmine for me pls", reply_to: "r1" },
    { id: "r3", speaker: "Mira", text: "gotchu 🌿 no giant status update this time lol", reply_to: "r2" },
    { id: "r4", speaker: "Sol", text: "bless. tiny updates > essays", reply_to: "r3" },
    { id: "r5", speaker: "Mira", text: "shipping the patch after tea", channel: "lounge" },
    { id: "r6", speaker: "Sol", text: "nice, ping me when green", reply_to: "r5" },
  ];
  const richExtract = await request("extract rich", "POST", "/v1/social-learning/actions/extract", {
    transcript: { source: "live-contract-rich", messages: richMessages },
  }, { billable: true });
  if (richExtract && richExtract.status === 200) {
    assertRequestMetadata(richExtract);
    check("extract rich exact top-level schema", hasExactKeys(richExtract.body, ["prompt_block", "profile"]));
    check("extract rich prompt block", isNonEmptyStr(richExtract.body.prompt_block));
    assertProfile("extract rich", richExtract.body.profile, { messageCount: richMessages.length, source: "live-contract-rich" });
    check("extract rich channels", sameSet(richExtract.body.profile?.meta?.channels, PINNED.meta_channels), JSON.stringify(richExtract.body.profile?.meta?.channels));
    check("rich extraction differs from tiny", tinyExtract?.status !== 200 || richExtract.body.prompt_block !== tinyExtract.body.prompt_block);
  } else if (richExtract && richExtract.status !== 402) fail("extract rich status", `HTTP ${richExtract.status}`);

  // --- Theory of Mind ---
  const foreseeWrong = await request("foresee wrong fields", "POST", "/v1/foresee/actions/foresee", {
    conversation: [{ speaker: "customer", text: "hello" }],
    draft: "hi",
  });
  assertRequestMetadata(foreseeWrong);
  assertRequestValidation(foreseeWrong, [
    { loc: "transcript", type: "missing", msg: "Field required" },
    { loc: "candidate_reply", type: "missing", msg: "Field required" },
  ]);

  const foreseeEmpty = await request("foresee empty transcript", "POST", "/v1/foresee/actions/foresee", {
    transcript: [],
    candidate_reply: "I can help.",
    bogus: 1,
  });
  assertRequestMetadata(foreseeEmpty);
  assertRequestValidation(foreseeEmpty, [{ loc: "transcript", type: "too_short", msg: "List should have at least 1 item after validation, not 0" }]);

  const foresee = await request("foresee valid", "POST", "/v1/foresee/actions/foresee", {
    transcript: [
      { speaker: "customer", text: "The export failed twice." },
      { speaker: "agent", text: "Try clearing your cache." },
      { speaker: "customer", text: "I already did. I will just do it manually." },
    ],
    candidate_reply: "Okay, reach out if you need anything else.",
    agent_name: "agent",
    subject_name: "customer",
    system_prompt: "You are a concise support agent. Preserve the customer's trust and own unresolved issues.",
  }, { billable: true });
  if (foresee?.status === 200) {
    assertRequestMetadata(foresee);
    check("foresee exact top-level schema", hasExactKeys(
      foresee.body,
      ["mental_state", "predicted_reaction", "refined_reply", "refinement_rationale"],
    ));
    assertMentalStates("foresee mental_state", foresee.body.mental_state);
    equal("foresee one modeled subject", foresee.body.mental_state?.length, 1);
    equal("foresee subject name", foresee.body.mental_state?.[0]?.name, PINNED.foresee_subject_name);
    check("foresee predicted_reaction", Array.isArray(foresee.body.predicted_reaction)
      && foresee.body.predicted_reaction.length === 1
      && foresee.body.predicted_reaction.every((reaction) => hasExactKeys(
        reaction,
        ["name", "summary", "predicted_message", "risk"],
      ) && isNonEmptyStr(reaction.name) && isNonEmptyStr(reaction.summary) && isNonEmptyStr(reaction.predicted_message)
        && ["low", "medium", "high"].includes(reaction.risk)), JSON.stringify(foresee.body.predicted_reaction));
    equal("foresee reaction subject name", foresee.body.predicted_reaction?.[0]?.name, PINNED.foresee_subject_name);
    check("foresee refined reply", isNonEmptyStr(foresee.body.refined_reply));
    check("foresee rationale", isNonEmptyStr(foresee.body.refinement_rationale));
  } else if (foresee && foresee.status !== 402) fail("foresee valid status", `HTTP ${foresee.status}`);

  // --- Social Observability: analyze ---
  const analyzeMessages = [
    { id: "a1", speaker: "Casey", user_id: "usr_casey", text: "the export broke again" },
    { id: "a2", speaker: "support_bot", text: "Have you tried clearing your cache?" },
    { id: "a3", speaker: "Casey", user_id: "usr_casey", text: "yes, twice. same answer as last week." },
    { id: "a4", speaker: "support_bot", text: "Please retry later." },
    { id: "a5", speaker: "Casey", user_id: "usr_casey", text: "nevermind, i'll do it by hand" },
    { id: "a6", speaker: "Jordan", user_id: "usr_jordan", text: "mine is broken too" },
  ];
  const analyze = await request("analyze valid", "POST", "/v1/social-observability/actions/analyze", {
    agent_name: "support_bot",
    transcript: { source: "live-contract-analysis", messages: analyzeMessages },
    focus: "Are repetitive replies increasing frustration?",
  }, { timeoutMs: 180_000, billable: true });

  if (analyze?.status === 200) {
    assertRequestMetadata(analyze);
    assertReport("analyze", analyze.body, {
      inputIds: analyzeMessages.map((message) => message.id),
      participants: ["Casey", "support_bot", "Jordan"],
      userIds: { Casey: "usr_casey", Jordan: "usr_jordan", support_bot: undefined },
    });
    const reportId = analyze.body?.id
      ?? analyze.headers["x-report-id"]
      ?? analyze.headers.location?.match(/[0-9a-f-]{36}/i)?.[0];
    check("analyze omits persisted report id", reportId === undefined);
    const requestIdProbe = await request(
      "report request-id probe",
      "GET",
      `/v1/social-observability/repositories/Report/by-id/${analyze.headers["x-request-id"]}`,
    );
    assertRequestMetadata(requestIdProbe);
    check("request id is not report id", requestIdProbe.status === 200 && requestIdProbe.body === null
      || (requestIdProbe.status === 400 && requestIdProbe.body?.error?.message === PINNED.invalid_id_message), JSON.stringify({ status: requestIdProbe.status, body: requestIdProbe.body }));
    learn("request-id probe outcome", { status: requestIdProbe.status, body: requestIdProbe.body });
  } else if (analyze && analyze.status !== 402) fail("analyze valid status", `HTTP ${analyze.status}`);

  const reportAbsent = await request("report absent", "GET", `/v1/social-observability/repositories/Report/by-id/${randomUUID()}`);
  assertRequestMetadata(reportAbsent);
  equal("report absent status", reportAbsent.status, 200);
  equal("report absent body", reportAbsent.body, null);

  const reportMalformed = await request("report malformed id", "GET", "/v1/social-observability/repositories/Report/by-id/not-a-uuid");
  assertRequestMetadata(reportMalformed);
  assertSemanticValidation(reportMalformed, { message: PINNED.invalid_id_message, details: null });

  // --- Audit ---
  const auditMissing = await request("audit prepare missing raw_text", "POST", "/v1/social-observability/actions/audit_prepare", {});
  assertRequestMetadata(auditMissing);
  assertRequestValidation(auditMissing, [{ loc: "raw_text", type: "missing", msg: "Field required" }]);

  const auditEmptyText = await request("audit prepare empty raw_text", "POST", "/v1/social-observability/actions/audit_prepare", { raw_text: "" });
  assertRequestMetadata(auditEmptyText);
  assertRequestValidation(auditEmptyText, [{ loc: "raw_text", type: "string_too_short", msg: "String should have at least 1 character" }]);

  const auditOversized = await request("audit prepare oversized chars", "POST", "/v1/social-observability/actions/audit_prepare", {
    raw_text: "x".repeat(300_001),
  }, { timeoutMs: 60_000 });
  assertRequestMetadata(auditOversized);
  assertRequestValidation(auditOversized, [{ loc: "raw_text", type: "string_too_long", msg: "String should have at most 300000 characters" }]);

  const auditBoundary = await request("audit prepare boundary 300000 chars", "POST", "/v1/social-observability/actions/audit_prepare", {
    raw_text: "x".repeat(300_000),
  }, { timeoutMs: 60_000 });
  assertRequestMetadata(auditBoundary);
  assertSemanticValidation(auditBoundary, { message: PINNED.oversized_message, details: [PINNED.oversized_detail] });

  const auditMalformed = await request("audit prepare unparsable", "POST", "/v1/social-observability/actions/audit_prepare", {
    raw_text: "This text contains no speaker-labelled conversation.",
  }, { billable: true });
  if (auditMalformed?.status !== 402) {
    assertRequestMetadata(auditMalformed);
    assertSemanticValidation(auditMalformed, { message: PINNED.unparsable_message, details: [PINNED.unparsable_detail] });
  }

  const auditTooMany = await request("audit prepare over 250 messages", "POST", "/v1/social-observability/actions/audit_prepare", {
    raw_text: auditLines(251),
  }, { timeoutMs: 180_000, billable: true });
  if (auditTooMany?.status !== 402) {
    assertRequestMetadata(auditTooMany);
    assertSemanticValidation(auditTooMany, { message: PINNED.too_many_messages_message, details: [PINNED.too_many_messages_detail] });
  }

  const auditAtCap = await request("audit prepare exactly 250 messages", "POST", "/v1/social-observability/actions/audit_prepare", {
    raw_text: auditLines(250),
  }, { timeoutMs: 180_000, billable: true });
  if (auditAtCap?.status === 200) {
    assertRequestMetadata(auditAtCap);
    check("audit cap exact schema", hasExactKeys(auditAtCap.body, ["run_id", "messages", "participants", "agent_guess"]) && isUuid(auditAtCap.body.run_id));
    equal("audit cap parsed count", auditAtCap.body.messages, 250);
    deepEqual("audit cap participants", auditAtCap.body.participants, ["Casey", "support_bot"]);
    equal("audit cap agent guess", auditAtCap.body.agent_guess, "support_bot");
  } else if (auditAtCap && auditAtCap.status !== 402) fail("audit prepare exactly 250 status", `HTTP ${auditAtCap.status}`);

  const auditNoTimestamps = await request("audit prepare without timestamps", "POST", "/v1/social-observability/actions/audit_prepare", {
    raw_text: "Casey: the export broke\nsupport_bot: try again\nCasey: no",
  }, { billable: true });
  if (auditNoTimestamps?.status === 200) {
    assertRequestMetadata(auditNoTimestamps);
    check("audit no-timestamp exact schema", hasExactKeys(auditNoTimestamps.body, ["run_id", "messages", "participants", "agent_guess"]) && isUuid(auditNoTimestamps.body.run_id));
    equal("audit no-timestamp parsed count", auditNoTimestamps.body.messages, 3);
    deepEqual("audit no-timestamp participants", auditNoTimestamps.body.participants, ["Casey", "support_bot"]);
    equal("audit no-timestamp agent guess", auditNoTimestamps.body.agent_guess, "support_bot");
  } else if (auditNoTimestamps && auditNoTimestamps.status !== 402) fail("audit prepare without timestamps status", `HTTP ${auditNoTimestamps.status}`);

  const auditMultiword = await request("audit prepare multiword speaker", "POST", "/v1/social-observability/actions/audit_prepare", {
    raw_text: "[10:01] Support Bot: hi there\n[10:02] Casey: hello\n[10:03] Support Bot: how can I help?",
  }, { billable: true });
  if (auditMultiword?.status === 200) {
    assertRequestMetadata(auditMultiword);
    equal("audit multiword parsed count", auditMultiword.body.messages, 3);
    deepEqual("audit multiword participants", auditMultiword.body.participants, ["Support Bot", "Casey"]);
    equal("audit multiword agent guess", auditMultiword.body.agent_guess, "Support Bot");
  } else if (auditMultiword && auditMultiword.status !== 402) fail("audit prepare multiword speaker status", `HTTP ${auditMultiword.status}`);

  const rawAuditLines = [
    "[10:01] Casey: the export broke again",
    "[10:02] support_bot: Have you tried clearing your cache?",
    "[10:03] Casey: yes, twice already",
    "[10:04] support_bot: Please retry later.",
    "[10:05] Casey: that does not help",
    "[10:06] support_bot: Is there anything else?",
    "[10:07] Casey: no, i will do it manually",
    "[10:08] Jordan: mine is failing too",
  ];
  const expectedTranscript = rawAuditLines.map((line, index) => {
    const match = line.match(/^\[\d\d:\d\d\] ([^:]+): (.*)$/);
    return { id: `m${index + 1}`, speaker: match[1], text: match[2], user_id: null, channel: null, timestamp: null, reply_to: null };
  });
  const auditPrepare = await request("audit prepare valid", "POST", "/v1/social-observability/actions/audit_prepare", {
    raw_text: rawAuditLines.join("\n"),
  }, { timeoutMs: 180_000, billable: true });

  let auditFinal;
  if (auditPrepare?.status === 200) {
    assertRequestMetadata(auditPrepare);
    check("audit prepare exact schema", hasExactKeys(auditPrepare.body, ["run_id", "messages", "participants", "agent_guess"]));
    check("audit prepare run id uuid", isUuid(auditPrepare.body.run_id));
    equal("audit prepare parsed count", auditPrepare.body.messages, 8);
    deepEqual("audit prepare participant order", auditPrepare.body.participants, ["Casey", "support_bot", "Jordan"]);
    equal("audit prepare agent guess", auditPrepare.body.agent_guess, "support_bot");

    const runId = auditPrepare.body.run_id;

    const auditBefore = await request("audit projection before launch", "POST", "/v1/social-observability/projections/audit-run", { run_id: runId });
    assertRequestMetadata(auditBefore);
    equal("audit projection before launch status", auditBefore.status, 200);
    deepEqual("audit projection before launch body", auditBefore.body, {
      run_id: runId,
      agent_name: "support_bot",
      transcript: { messages: expectedTranscript, source: null },
      read: null,
      verdicts: null,
      report: null,
      replies: [],
    });

    const auditMalformedRun = await request("audit launch malformed run id", "POST", "/v1/social-observability/actions/audit_launch", {
      run_id: "nope",
      agent_name: "support_bot",
    });
    assertRequestMetadata(auditMalformedRun);
    assertRequestValidation(auditMalformedRun, [{ loc: "run_id", type: "uuid_parsing" }]);

    const auditWrong = await request("audit launch wrong participant", "POST", "/v1/social-observability/actions/audit_launch", {
      run_id: runId,
      agent_name: "support-bot-typo",
    });
    assertRequestMetadata(auditWrong);
    assertSemanticValidation(auditWrong, {
      message: PINNED.nonparticipant_message,
      details: [{ field: "agent_name", message: PINNED.nonparticipant_detail }],
    });

    const auditLaunch = await request("audit launch valid", "POST", "/v1/social-observability/actions/audit_launch", {
      run_id: runId,
      agent_name: "support_bot",
    }, { billable: true });
    if (auditLaunch?.status === 200) {
      assertRequestMetadata(auditLaunch);
      deepEqual("audit launch exact body", auditLaunch.body, { run_id: runId, agent_name: "support_bot", status: "queued" });

      const auditRepeat = await request("audit launch repeat", "POST", "/v1/social-observability/actions/audit_launch", {
        run_id: runId,
        agent_name: "Casey",
      });
      assertRequestMetadata(auditRepeat);
      equal("audit repeat status code", auditRepeat.status, 200);
      check("audit repeat exact schema", hasExactKeys(auditRepeat.body, ["run_id", "agent_name", "status"]));
      equal("audit repeat run id", auditRepeat.body.run_id, runId);
      equal("audit repeat preserves first agent", auditRepeat.body.agent_name, "support_bot");
      check("audit repeat status value", isNonEmptyStr(auditRepeat.body.status));
      learn("audit repeat launch status (early)", auditRepeat.body.status);

      const auditStarted = Date.now();
      const stages = [];
      const firstSeen = {};
      let pollIndex = 0;
      let previousSignature = null;
      let monotonic = true;
      let stableCount = 0;
      let lastRepliesLength = null;
      for (;;) {
        const poll = await request("audit projection poll", "POST", "/v1/social-observability/projections/audit-run", { run_id: runId });
        assertRequestMetadata(poll);
        if (poll.status !== 200) throw new HttpError("audit projection", poll);
        const body = poll.body ?? {};
        const signature = {
          report: body.report !== null,
          read: body.read !== null,
          verdicts: body.verdicts !== null,
          replies: Array.isArray(body.replies) ? body.replies.length : null,
          extra_keys: Object.keys(body).filter((key) => !["run_id", "agent_name", "transcript", "report", "read", "verdicts", "replies"].includes(key)),
        };
        for (const section of ["report", "read", "verdicts"]) {
          if (signature[section] && firstSeen[section] === undefined) firstSeen[section] = pollIndex;
        }
        if (signature.replies > 0 && firstSeen.replies === undefined) firstSeen.replies = pollIndex;
        if (previousSignature) {
          for (const section of ["report", "read", "verdicts"]) if (previousSignature[section] && !signature[section]) monotonic = false;
          if (signature.replies < previousSignature.replies) monotonic = false;
        }
        previousSignature = signature;
        if (!stages.some((item) => JSON.stringify(item) === JSON.stringify(signature))) stages.push(signature);
        const sectionsDone = body.report !== null && body.read !== null && body.verdicts !== null;
        const repliesComplete = sectionsDone && Array.isArray(body.replies) && body.replies.length === body.verdicts.length && body.replies.length > 0;
        if (sectionsDone && body.replies?.length === lastRepliesLength) stableCount += 1;
        else stableCount = 0;
        lastRepliesLength = body.replies?.length ?? null;
        // Terminal: every verdict has its reply and the projection was unchanged across two consecutive polls.
        if (repliesComplete && stableCount >= 1) {
          auditFinal = body;
          learn("audit terminal rule", "replies.length === verdicts.length and unchanged across two polls");
          break;
        }
        // Safety valve: sections done but replies not matching verdicts for 45 s — accept and let assertions report it.
        if (sectionsDone && stableCount * POLL_MS >= 45_000) {
          auditFinal = body;
          learn("audit terminal rule", "sections non-null and replies stable 45s (replies != verdicts)");
          break;
        }
        if (Date.now() - auditStarted > AUDIT_TIMEOUT_MS) throw new Error("audit projection timed out");
        pollIndex += 1;
        await sleep(POLL_MS);
      }
      jobTimings.audit = { elapsed_ms: Date.now() - auditStarted, states: stages, first_seen: firstSeen, polls: pollIndex + 1 };
      terminalPollTargets.push({ label: "audit terminal", method: "POST", path: "/v1/social-observability/projections/audit-run", body: { run_id: runId } });
      observe("audit lifecycle", jobTimings.audit);

      check("audit sections monotonic", monotonic, JSON.stringify(stages));
      check("audit progression order report<=read<=verdicts<=replies",
        firstSeen.report !== undefined && firstSeen.read !== undefined && firstSeen.verdicts !== undefined && firstSeen.replies !== undefined
        && firstSeen.report <= firstSeen.read && firstSeen.read <= firstSeen.verdicts && firstSeen.verdicts <= firstSeen.replies, JSON.stringify(firstSeen));
      check("audit projection never exposes status or stage", stages.every((stage) => stage.extra_keys.length === 0), JSON.stringify(stages));

      check("audit projection exact schema", hasExactKeys(
        auditFinal,
        ["run_id", "agent_name", "transcript", "report", "read", "verdicts", "replies"],
      ));
      equal("audit projection run id", auditFinal.run_id, runId);
      equal("audit projection agent", auditFinal.agent_name, "support_bot");
      deepEqual("audit parsed transcript", auditFinal.transcript, { messages: expectedTranscript, source: null });
      check("audit message id pattern", auditFinal.transcript.messages.every((message) => PINNED.audit_message_id_pattern.test(message.id)));
      assertReport("audit report", auditFinal.report, {
        inputIds: expectedTranscript.map((message) => message.id),
        participants: ["Casey", "support_bot", "Jordan"],
        userIds: null,
      });
      check("audit read exact schema", hasExactKeys(auditFinal.read, [], ["prompt_block", "portrait", "mental_state", "profiles"]));
      learn("audit read keys", Object.keys(auditFinal.read ?? {}));
      const read = auditFinal.read ?? {};
      if (read.prompt_block !== undefined) check("audit read prompt_block", read.prompt_block === null || isNonEmptyStr(read.prompt_block));
      if (read.portrait !== undefined) check("audit read portrait", read.portrait === null
        || (hasExactKeys(read.portrait, ["role", "personality", "register"]) && ["role", "personality", "register"].every((key) => isStr(read.portrait[key]))));
      if (read.mental_state !== undefined && read.mental_state !== null) assertMentalStates("audit read mental_state", read.mental_state);
      if (read.mental_state !== undefined) learn("audit read mental_state names", read.mental_state?.map((state) => state.name) ?? null);
      if (read.profiles !== undefined) check("audit read profiles", read.profiles === null
        || (Array.isArray(read.profiles) && read.profiles.every(
          (profile) => hasExactKeys(profile, ["name", "facts"]) && isNonEmptyStr(profile.name) && strArr(profile.facts),
        )));
      if (read.profiles !== undefined) learn("audit read profile names", read.profiles?.map((profile) => profile.name) ?? null);
      check("audit verdicts schema", Array.isArray(auditFinal.verdicts) && auditFinal.verdicts.length > 0 && auditFinal.verdicts.every(
        (verdict) => hasExactKeys(verdict, ["index", "risk", "summary", "predicted_message"])
          && Number.isInteger(verdict.index)
          && PINNED.audit_risk_vocabulary.includes(verdict.risk)
          && isNonEmptyStr(verdict.summary)
          && isStr(verdict.predicted_message),
      ), JSON.stringify(auditFinal.verdicts));
      const agentTurnPositions = expectedTranscript.map((message, position) => (message.speaker === "support_bot" ? position : -1)).filter((position) => position >= 0);
      deepEqual("audit verdict indexes are 0-based agent turn positions", auditFinal.verdicts.map((verdict) => verdict.index), agentTurnPositions);
      deepEqual("audit verdict indexes pinned", auditFinal.verdicts.map((verdict) => verdict.index), PINNED.audit_verdict_indexes);
      check("audit replies schema", Array.isArray(auditFinal.replies) && auditFinal.replies.every(
        (reply) => hasExactKeys(reply, ["index", "reply", "messages", "risk"])
          && Number.isInteger(reply.index)
          && isNonEmptyStr(reply.reply)
          && strArr(reply.messages) && reply.messages.length > 0
          && PINNED.audit_risk_vocabulary.includes(reply.risk),
      ), JSON.stringify(auditFinal.replies));
      deepEqual("audit replies cover every verdict index", auditFinal.replies.map((reply) => reply.index), auditFinal.verdicts.map((verdict) => verdict.index));
      learn("audit reply risks vs verdict risks", auditFinal.replies.map((reply) => ({ index: reply.index, reply_risk: reply.risk, verdict_risk: auditFinal.verdicts.find((verdict) => verdict.index === reply.index)?.risk })));
      learn("audit verdict risks", auditFinal.verdicts.map((verdict) => verdict.risk));
      learn("audit replies sample", auditFinal.replies.map((reply) => ({ index: reply.index, messages: reply.messages, reply: reply.reply.slice(0, 120) })));

      const auditRelaunch = await request("audit launch after completion", "POST", "/v1/social-observability/actions/audit_launch", {
        run_id: runId,
        agent_name: "Casey",
      });
      assertRequestMetadata(auditRelaunch);
      equal("audit relaunch status code", auditRelaunch.status, 200);
      equal("audit relaunch preserves first agent", auditRelaunch.body?.agent_name, "support_bot");
      equal("audit relaunch run id", auditRelaunch.body?.run_id, runId);
      equal("audit relaunch status value", auditRelaunch.body?.status, PINNED.audit_launch_terminal_status);
      const auditAfterRelaunch = await request("audit projection after relaunch", "POST", "/v1/social-observability/projections/audit-run", { run_id: runId });
      assertRequestMetadata(auditAfterRelaunch);
      deepEqual("audit relaunch did not restart", auditAfterRelaunch.body, auditFinal);
    } else if (auditLaunch && auditLaunch.status !== 402) fail("audit launch valid status", `HTTP ${auditLaunch.status}`);
  } else if (auditPrepare && auditPrepare.status !== 402) fail("audit prepare valid status", `HTTP ${auditPrepare.status}`);

  const auditAbsent = await request("audit projection absent", "POST", "/v1/social-observability/projections/audit-run", {
    run_id: randomUUID(),
  });
  assertRequestMetadata(auditAbsent);
  assertSemanticValidation(auditAbsent, { message: PINNED.unknown_run_message, details: [PINNED.unknown_run_detail] });

  const auditLaunchAbsent = await request("audit launch absent run", "POST", "/v1/social-observability/actions/audit_launch", {
    run_id: randomUUID(),
    agent_name: "x",
  });
  assertRequestMetadata(auditLaunchAbsent);
  assertSemanticValidation(auditLaunchAbsent, { message: PINNED.unknown_run_message, details: [PINNED.unknown_run_detail] });

  const auditProjectionMalformed = await request("audit projection malformed run id", "POST", "/v1/social-observability/projections/audit-run", { run_id: "nope" });
  assertRequestMetadata(auditProjectionMalformed);
  assertRequestValidation(auditProjectionMalformed, [{ loc: "run_id", type: "uuid_parsing" }]);

  // --- Personas: generation ---
  const populationAbsent = await request("population absent", "GET", `/v1/personas/repositories/Population/by-id/${randomUUID()}`);
  assertRequestMetadata(populationAbsent);
  equal("population absent status", populationAbsent.status, 200);
  equal("population absent body", populationAbsent.body, null);

  const populationMalformed = await request("population malformed id", "GET", "/v1/personas/repositories/Population/by-id/not-a-uuid");
  assertRequestMetadata(populationMalformed);
  assertSemanticValidation(populationMalformed, { message: PINNED.invalid_id_message, details: null });

  const generateEmpty = await request("generate empty prompt", "POST", "/v1/personas/actions/generate", {
    prompt: "",
    count: 1,
    grounding: "off",
    bogus: 1,
  });
  assertRequestMetadata(generateEmpty);
  assertRequestValidation(generateEmpty, [{ loc: "prompt", type: "string_too_short", msg: "String should have at least 1 character" }]);

  const generateZero = await request("generate zero count", "POST", "/v1/personas/actions/generate", {
    prompt: "x",
    count: 0,
    grounding: "off",
  });
  assertRequestMetadata(generateZero);
  assertRequestValidation(generateZero, [{ loc: "count", type: "greater_than_equal", msg: "Input should be greater than or equal to 1" }]);

  const generateBogusGrounding = await request("generate bogus grounding", "POST", "/v1/personas/actions/generate", {
    prompt: "x",
    count: 1,
    grounding: "bogus",
  });
  assertRequestMetadata(generateBogusGrounding);
  assertRequestValidation(generateBogusGrounding, [{ loc: "grounding", type: "literal_error", msg: "Input should be 'off', 'web' or 'research'" }]);

  const generateMissingGrounding = await request("generate missing grounding", "POST", "/v1/personas/actions/generate", {
    prompt: "",
    count: 1,
  });
  assertRequestMetadata(generateMissingGrounding);
  assertRequestValidation(generateMissingGrounding, [{ loc: "prompt", type: "string_too_short" }]);

  const generatePrompt = "Two fictional community librarians with varied ages and weekly reading hours";
  const generate = await request("generate population", "POST", "/v1/personas/actions/generate", {
    prompt: generatePrompt,
    count: 2,
    grounding: "off",
  }, { billable: true });

  let population;
  if (generate?.status === 200) {
    assertRequestMetadata(generate);
    check("generate initial exact schema", hasExactKeys(generate.body, ["id", "status"]) && isUuid(generate.body.id));
    equal("generate initial status", generate.body.status, "pending");
    const populationContext = { id: generate.body.id, prompt: generatePrompt, count: 2, grounding: "off" };
    population = await pollGet(
      "population",
      `/v1/personas/repositories/Population/by-id/${generate.body.id}`,
      (body) => ["succeeded", "failed"].includes(body.status),
      JOB_TIMEOUT_MS,
      (body) => assertPopulationResource(`population ${body.status}`, body, populationContext),
    );
    equal("population terminal status", population.status, "succeeded");
    assertPhaseSequence("population", jobTimings.population.phases, PINNED.population_phases);
    if (population.status === "succeeded") {
      terminalPollTargets.push({
        label: "population terminal",
        method: "GET",
        path: `/v1/personas/repositories/Population/by-id/${generate.body.id}`,
      });
      deepEqual("population final progress", population.progress, { phase: "complete", produced: 2, total: 2 });
      const result = population.result;
      check("population result exact schema", hasExactKeys(result, ["personas", "blueprint", "diversity", "marginals"]));
      equal("population count", result.personas.length, 2);
      result.personas.forEach((persona, index) => assertPersona(`population persona[${index}]`, persona));
      check("population persona ids unique", new Set(result.personas.map((persona) => persona.persona_id)).size === result.personas.length);
      deepEqual("population persona ids sequential", result.personas.map((persona) => persona.persona_id), ["p0001", "p0002"]);
      check("population persona id pattern", result.personas.every((persona) => PINNED.generated_persona_id_pattern.test(persona.persona_id)));
      check("population markdown template", result.personas.every((persona) => persona.markdown.startsWith(PINNED.generated_markdown_prefix)));
      check("population system prompt template", result.personas.every((persona) => persona.system_prompt.startsWith(PINNED.generated_system_prompt_prefix)));
      check("population system prompt differs from markdown", result.personas.every((persona) => persona.system_prompt !== persona.markdown));
      check("population blueprint labels populated", result.blueprint.fields.every((field) => isNonEmptyStr(field.label)));
      check("population derived fields carry formulas", result.blueprint.fields.every((field) => field.kind !== "derived" || isNonEmptyStr(field.formula)));
      check("population conditionals reference parents", result.blueprint.fields.every((field) =>
        field.conditionals.every((conditional) => Object.keys(conditional.when).every((parent) => field.parents.includes(parent)))));
      assertBlueprint("population", result.blueprint);
      const fieldNames = result.blueprint.fields.map((field) => field.name).sort();
      check("population persona keys match blueprint", result.personas.every(
        (persona) => JSON.stringify(Object.keys(persona.fields).sort()) === JSON.stringify(fieldNames),
      ));
      check("population persona field values non-empty", result.personas.every(
        (persona) => Object.values(persona.fields).every(isNonEmptyStr),
      ));
      const orderedKinds = result.blueprint.fields.filter((field) => result.blueprint.order.includes(field.name)).map((field) => field.kind);
      const unorderedKinds = result.blueprint.fields.filter((field) => !result.blueprint.order.includes(field.name)).map((field) => field.kind);
      learn("population order kinds", { in_order: [...new Set(orderedKinds)], omitted_from_order: [...new Set(unorderedKinds)] });
      check("population order holds every sampled field", result.blueprint.fields.every((field) =>
        !["categorical", "numeric"].includes(field.kind) || result.blueprint.order.includes(field.name)), JSON.stringify({ order: result.blueprint.order, kinds: result.blueprint.fields.map((field) => [field.name, field.kind]) }));
      learn("population blueprint summary", {
        domain: result.blueprint.domain,
        language: result.blueprint.language,
        order: result.blueprint.order,
        fields: result.blueprint.fields.map((field) => ({ name: field.name, kind: field.kind, parents: field.parents, conditionals: field.conditionals.length, ordered_values: field.ordered_values, weights: field.categorical?.weights ?? null, numeric: field.numeric })),
        constraints: result.blueprint.constraints,
        style_axes: result.blueprint.style_axes,
        name_origins: result.blueprint.name_origins,
        sources: result.blueprint.sources,
      });
      assertDiversity("population", result.diversity);
      assertMarginals("population", result.marginals);
      check("population marginals cover categorical fields", result.marginals.every((marginal) => fieldNames.includes(marginal.attribute)));
      learn("population marginals", result.marginals);
      check("population marginal cells are fractions summing to one", result.marginals.every((marginal) =>
        Math.abs(marginal.cells.reduce((sum, cell) => sum + cell.requested, 0) - 1) < 0.02
        && Math.abs(marginal.cells.reduce((sum, cell) => sum + cell.achieved, 0) - 1) < 0.02));
      check("population marginals tvd matches cells", result.marginals.every((marginal) =>
        Math.abs(marginal.total_variation_distance - 0.5 * marginal.cells.reduce((sum, cell) => sum + Math.abs(cell.requested - cell.achieved), 0)) < 0.011));
      learn("population marginal cell semantics", result.marginals.map((marginal) => ({
        attribute: marginal.attribute,
        requested_sum: marginal.cells.reduce((sum, cell) => sum + cell.requested, 0),
        achieved_sum: marginal.cells.reduce((sum, cell) => sum + cell.achieved, 0),
      })));
    }
  } else if (generate && generate.status !== 402) fail("generate population status", `HTTP ${generate.status}`);

  // --- Personas: enhancement ---
  const enhancementAbsent = await request("enhancement absent", "GET", `/v1/personas/repositories/Enhancement/by-id/${randomUUID()}`);
  assertRequestMetadata(enhancementAbsent);
  equal("enhancement absent status", enhancementAbsent.status, 200);
  equal("enhancement absent body", enhancementAbsent.body, null);

  const enhancementMalformed = await request("enhancement malformed id", "GET", "/v1/personas/repositories/Enhancement/by-id/not-a-uuid");
  assertRequestMetadata(enhancementMalformed);
  assertSemanticValidation(enhancementMalformed, { message: PINNED.invalid_id_message, details: null });

  const enhanceEmpty = await request("enhance empty persona", "POST", "/v1/personas/actions/enhance", {
    persona: "",
    grounding: "off",
  });
  assertRequestMetadata(enhanceEmpty);
  assertRequestValidation(enhanceEmpty, [{ loc: "persona", type: "string_too_short", msg: "String should have at least 1 character" }]);

  const enhanceBogusGrounding = await request("enhance bogus grounding", "POST", "/v1/personas/actions/enhance", {
    persona: "x",
    grounding: "bogus",
  });
  assertRequestMetadata(enhanceBogusGrounding);
  assertRequestValidation(enhanceBogusGrounding, [{ loc: "grounding", type: "literal_error", msg: "Input should be 'off', 'web' or 'research'" }]);

  const enhancementMarker = `contract-${randomUUID()}`;
  const seedFacts = `Iris Vale is exactly 47 years old, lives in Turku, repairs antique clocks, always carries a cobalt-blue notebook, and uses the private marker ${enhancementMarker}.`;
  const enhance = await request("enhance persona", "POST", "/v1/personas/actions/enhance", {
    persona: seedFacts,
    grounding: "off",
  }, { billable: true });
  if (enhance?.status === 200) {
    assertRequestMetadata(enhance);
    check("enhance initial exact schema", hasExactKeys(enhance.body, ["id", "status"]) && isUuid(enhance.body.id));
    equal("enhance initial status", enhance.body.status, PINNED.enhance_initial_status);
    const enhancementContext = { id: enhance.body.id, source: seedFacts, grounding: "off" };
    const enhancement = await pollGet(
      "enhancement",
      `/v1/personas/repositories/Enhancement/by-id/${enhance.body.id}`,
      (body) => ["succeeded", "failed"].includes(body.status),
      JOB_TIMEOUT_MS,
      (body) => assertEnhancementResource(`enhancement ${body.status}`, body, enhancementContext),
    );
    equal("enhancement terminal status", enhancement.status, "succeeded");
    learn("enhancement statuses observed", jobTimings.enhancement.states.map((state) => state.status));
    if (enhancement.status === "succeeded") {
      terminalPollTargets.push({
        label: "enhancement terminal",
        method: "GET",
        path: `/v1/personas/repositories/Enhancement/by-id/${enhance.body.id}`,
      });
      equal("enhancement success error", enhancement.error, null);
      assertPersona("enhanced persona", enhancement.persona, { allowEmptyFields: true });
      equal("enhancement fields are empty", Object.keys(enhancement.persona.fields).length, 0);
      equal("enhancement system_prompt equals markdown", enhancement.persona.system_prompt, enhancement.persona.markdown);
      const searchable = JSON.stringify(enhancement.persona).toLowerCase();
      check("enhancement preserves age", /\b47\b/.test(enhancement.persona.markdown));
      check("enhancement preserves city", searchable.includes("turku"));
      check("enhancement preserves occupation", searchable.includes("antique") && searchable.includes("clock"));
      check("enhancement preserves notebook fact", searchable.includes("cobalt") && searchable.includes("notebook"));
      check("enhancement preserves unique marker", searchable.includes(enhancementMarker));
      check("enhancement embeds source verbatim", enhancement.persona.markdown.includes(seedFacts));
      check("enhancement embeds source under user-provided section", enhancement.persona.markdown.includes(`${PINNED.enhancement_source_section}${seedFacts}`));
      check("enhancement markdown template", enhancement.persona.markdown.startsWith(PINNED.enhancement_markdown_prefix));
      check("enhancement persona id pattern", PINNED.enhanced_persona_id_pattern.test(enhancement.persona.persona_id), enhancement.persona.persona_id);
      const markdownLines = enhancement.persona.markdown.split("\n");
      const seedLine = markdownLines.findIndex((line) => line.includes(enhancementMarker));
      const headings = markdownLines.slice(0, seedLine).filter((line) => /^#{1,6}\s/.test(line));
      learn("enhancement heading above seed", headings[headings.length - 1] ?? null);
      learn("enhancement markdown headings", markdownLines.filter((line) => /^#{1,6}\s/.test(line)));
      learn("enhancement persona_id", enhancement.persona.persona_id);
      learn("enhancement prompt length", enhancement.persona.markdown.length);
    }
  } else if (enhance && enhance.status !== 402) fail("enhance persona status", `HTTP ${enhance.status}`);

  // --- Personas: validation ---
  const evaluationAbsent = await request("evaluation absent", "GET", `/v1/personas/repositories/Evaluation/by-id/${randomUUID()}`);
  assertRequestMetadata(evaluationAbsent);
  equal("evaluation absent status", evaluationAbsent.status, 200);
  equal("evaluation absent body", evaluationAbsent.body, null);

  const evaluationMalformed = await request("evaluation malformed id", "GET", "/v1/personas/repositories/Evaluation/by-id/not-a-uuid");
  assertRequestMetadata(evaluationMalformed);
  assertSemanticValidation(evaluationMalformed, { message: PINNED.invalid_id_message, details: null });

  function normalizeBlueprint(blueprint) {
    return {
      domain: blueprint.domain,
      language: blueprint.language ?? "",
      order: blueprint.order,
      fields: blueprint.fields.map((field) => ({
        name: field.name,
        label: field.label ?? "",
        kind: field.kind,
        description: field.description ?? "",
        formula: field.formula ?? "",
        parents: field.parents ?? [],
        categorical: field.categorical ?? null,
        numeric: field.numeric ?? null,
        conditionals: field.conditionals ?? [],
        ordered_values: field.ordered_values ?? null,
      })),
      constraints: blueprint.constraints ?? [],
      style_axes: blueprint.style_axes ?? {},
      name_origins: blueprint.name_origins ?? [],
      rationale: blueprint.rationale ?? "",
      sources: blueprint.sources ?? [],
    };
  }

  async function runValidation(label, body, { singlePersona, expectBlueprint }) {
    const submit = await request(label, "POST", "/v1/personas/actions/validate", body, { billable: true });
    if (submit?.status !== 200) {
      if (submit && submit.status !== 402) fail(`${label} status`, `HTTP ${submit.status}`);
      return null;
    }
    assertRequestMetadata(submit);
    check(`${label} initial exact schema`, hasExactKeys(submit.body, ["id", "status"]) && isUuid(submit.body.id));
    equal(`${label} initial status`, submit.body.status, "pending");
    const context = { id: submit.body.id, personas: body.personas, blueprint: body.blueprint === undefined ? null : undefined };
    const evaluation = await pollGet(
      label,
      `/v1/personas/repositories/Evaluation/by-id/${submit.body.id}`,
      (resource) => ["succeeded", "failed"].includes(resource.status),
      JOB_TIMEOUT_MS,
      (resource) => assertEvaluationResource(`${label} ${resource.status}`, resource, context),
    );
    equal(`${label} job status`, evaluation.status, "succeeded");
    assertPhaseSequence(label, jobTimings[label].phases, PINNED.evaluation_phases);
    deepEqual(`${label} final progress`, evaluation.progress, { phase: "complete" });
    if (expectBlueprint) {
      assertBlueprint(`${label} echoed blueprint`, evaluation.blueprint);
      deepEqual(`${label} blueprint normalized with defaults`, evaluation.blueprint, normalizeBlueprint(body.blueprint));
    }
    assertEvaluation(label, evaluation, { singlePersona });
    terminalPollTargets.push({
      label: `${label} terminal`,
      method: "GET",
      path: `/v1/personas/repositories/Evaluation/by-id/${submit.body.id}`,
    });
    return evaluation;
  }

  if (population?.status === "succeeded") {
    const evaluation = await runValidation("validate generated population", {
      personas: population.result.personas,
      blueprint: population.result.blueprint,
    }, { singlePersona: false, expectBlueprint: true });
    if (evaluation) {
      equal("validate generated population passed", evaluation.result?.passed, true);
      deepEqual("validate generated population echoes blueprint", evaluation.blueprint, population.result.blueprint);
      check("validate generated population gates all pass", evaluation.result?.scorecards?.every((card) => card.gates.every((gate) => gate.passed)));
      learn("validate generated population gate details", evaluation.result?.scorecards?.map((card) => card.gates));
      learn("validate generated population soft scores", evaluation.result?.scorecards?.map((card) => card.soft_scores));
      learn("validate generated population diversity/marginals equal population", {
        diversity: canonical(evaluation.result?.diversity) === canonical(population.result.diversity),
        marginals: canonical(evaluation.result?.marginals) === canonical(population.result.marginals),
      });
    }
  } else {
    skip("validate generated population", "population unavailable");
  }

  const customBlueprint = {
    domain: "constraint_probe",
    order: ["age", "hours"],
    fields: [
      { name: "age", kind: "numeric", description: "age in years", parents: [], numeric: { min: 0, max: 120, mean: 40, sd: 15, integer: true }, conditionals: [] },
      { name: "hours", kind: "numeric", description: "weekly hours", parents: [], numeric: { min: 0, max: 100, mean: 20, sd: 10, integer: true }, conditionals: [] },
    ],
    constraints: [
      { name: "age_nonnegative", lhs: "age", op: ">=", rhs: "0" },
      { name: "hours_nonnegative", lhs: "hours", op: ">=", rhs: "0" },
    ],
  };
  const invalidPersona = {
    persona_id: "constraint_probe_1",
    fields: { age: "-3", hours: "unknown" },
    system_prompt: "You are the constraint probe.",
    markdown: "# Constraint probe",
  };
  const failEvaluation = await runValidation("validate constraint violation", {
    personas: [invalidPersona],
    blueprint: customBlueprint,
  }, { singlePersona: true, expectBlueprint: true });
  if (failEvaluation) {
    equal("validate constraint violation verdict", failEvaluation.result?.passed, false);
    const gates = failEvaluation.result?.scorecards?.[0]?.gates ?? [];
    const schemaGate = gates.find((gate) => gate.name === "schema");
    const constraintsGate = gates.find((gate) => gate.name === "constraints");
    equal("nonnumeric field fails schema gate", schemaGate?.passed, false);
    equal("schema gate detail", schemaGate?.detail, PINNED.schema_fail_detail);
    equal("violated constraint fails aggregate gate", constraintsGate?.passed, false);
    equal("constraints gate detail", constraintsGate?.detail, PINNED.constraints_fail_detail);
    learn("validate constraint violation normalized blueprint", failEvaluation.blueprint);
    learn("validate constraint violation gates", gates);
    learn("validate constraint violation batch gates", failEvaluation.result?.gates);
  }

  const notApplicableBlueprint = {
    domain: "not_applicable_probe",
    order: ["hours"],
    fields: [
      { name: "hours", kind: "numeric", description: "weekly hours", parents: [], numeric: { min: 0, max: 100, mean: 20, sd: 10, integer: true }, conditionals: [] },
    ],
    constraints: [{ name: "hours_nonnegative", lhs: "hours", op: ">=", rhs: "0" }],
  };
  const notApplicablePersona = {
    persona_id: "not_applicable_probe_1",
    fields: { hours: "unknown" },
    system_prompt: "You are the not-applicable probe.",
    markdown: "# Not-applicable probe",
  };
  const notApplicableEvaluation = await runValidation("validate non-applicable constraint", {
    personas: [notApplicablePersona],
    blueprint: notApplicableBlueprint,
  }, { singlePersona: true, expectBlueprint: true });
  if (notApplicableEvaluation) {
    equal("non-applicable evaluation verdict", notApplicableEvaluation.result?.passed, false);
    const gates = notApplicableEvaluation.result?.scorecards?.[0]?.gates ?? [];
    const schemaGate = gates.find((gate) => gate.name === "schema");
    const constraintsGate = gates.find((gate) => gate.name === "constraints");
    equal("non-applicable probe schema fails", schemaGate?.passed, false);
    equal("non-applicable constraint aggregate passes", constraintsGate?.passed, true);
    equal("non-applicable aggregate detail", constraintsGate?.detail, PINNED.non_applicable_detail);
    learn("validate non-applicable gates", gates);
  }

  const soloPersona = { persona_id: "solo_1", fields: { age: "31", city: "Turku" }, system_prompt: "You are solo.", markdown: "# Solo" };
  const blueprintless = await runValidation("validate without blueprint", { personas: [soloPersona] }, { singlePersona: true, expectBlueprint: false });
  if (blueprintless) {
    equal("validate without blueprint blueprint null", blueprintless.blueprint, null);
    deepEqual("validate without blueprint result", blueprintless.result, { passed: true, gates: [], scorecards: [], diversity: null, marginals: [], notes: [] });
  }

  const minimalPersonaSubmit = await request("validate minimal persona", "POST", "/v1/personas/actions/validate", { personas: [{ persona_id: "p" }] }, { billable: true });
  if (minimalPersonaSubmit?.status === 200) {
    assertRequestMetadata(minimalPersonaSubmit);
    deepEqual("validate minimal persona initial body", { ...minimalPersonaSubmit.body, id: isUuid(minimalPersonaSubmit.body.id) ? "<uuid>" : minimalPersonaSubmit.body.id }, { id: "<uuid>", status: "pending" });
    const minimal = await pollGet("validate minimal persona", `/v1/personas/repositories/Evaluation/by-id/${minimalPersonaSubmit.body.id}`, (resource) => ["succeeded", "failed"].includes(resource.status));
    deepEqual("validate minimal persona defaults", minimal.personas, [{ persona_id: "p", fields: {}, system_prompt: "", markdown: "" }]);
    equal("validate minimal persona status", minimal.status, "succeeded");
    deepEqual("validate minimal persona result", minimal.result, { passed: true, gates: [], scorecards: [], diversity: null, marginals: [], notes: [] });
  } else if (minimalPersonaSubmit && minimalPersonaSubmit.status !== 402) fail("validate minimal persona status", `HTTP ${minimalPersonaSubmit.status}`);

  const validateEmpty = await request("validate empty personas", "POST", "/v1/personas/actions/validate", {
    personas: [],
  });
  assertRequestMetadata(validateEmpty);
  assertRequestValidation(validateEmpty, [{ loc: "personas", type: "too_short", msg: "List should have at least 1 item after validation, not 0" }]);

  const validateMissing = await request("validate missing personas", "POST", "/v1/personas/actions/validate", {});
  assertRequestMetadata(validateMissing);
  assertRequestValidation(validateMissing, [{ loc: "personas", type: "missing", msg: "Field required" }]);

  // --- Terminal polling is free ---
  const pollingUsageStart = await usageSummary("polling usage start");
  for (const target of terminalPollTargets) {
    const record = await request(`${target.label} free re-poll`, target.method, target.path, target.body);
    equal(`${target.label} free re-poll status`, record.status, 200);
  }
  await sleep(1500);
  const pollingUsageEnd = await usageSummary("polling usage end");
  const pollingDelta = usageDelta(pollingUsageStart, pollingUsageEnd);
  observe("POLLING_USAGE_DELTA", pollingDelta);
  const ownPollingDelta = pollingDelta.per_component.filter(
    (item) => ["personas", "social-observability"].includes(item.component),
  );
  check("terminal job polling adds no billed calls or credits", ownPollingDelta.every(
    (item) => item.calls === 0 && item.credits === 0,
  ), JSON.stringify(ownPollingDelta));

  const usageEnd = await usageSummary("usage end");
  const delta = usageDelta(usageStart, usageEnd);
  observe("USAGE_DELTA", delta);

  const requestIdMissing = calls.filter((call) => !call.headers["x-request-id"]).map((call) => call.label);
  check("all sampled responses carry x-request-id", requestIdMissing.length === 0, JSON.stringify(requestIdMissing));
  const contentTypeMissing = calls.filter((call) => !String(call.headers["content-type"] ?? "").startsWith("application/json")).map((call) => call.label);
  check("all sampled responses are application/json", contentTypeMissing.length === 0, JSON.stringify(contentTypeMissing));
  const rateLimitHeaders = [...new Set(calls.flatMap((call) => Object.keys(call.headers).filter(
    (name) => name.startsWith("x-ratelimit") || name === "retry-after" || name.startsWith("ratelimit"),
  )))];
  check("no rate-limit headers in sampled responses", rateLimitHeaders.length === 0, JSON.stringify(rateLimitHeaders));

  const syncLabels = ["extract tiny", "extract rich", "foresee valid", "analyze valid", "audit prepare unparsable", "audit prepare over 250 messages", "audit prepare exactly 250 messages", "audit prepare valid", "audit launch valid", "generate population", "enhance persona"];
  observe("SYNC_DURATIONS_MS", Object.fromEntries(calls.filter((call) => syncLabels.includes(call.label)).map((call) => [call.label, call.elapsed_ms])));
  observe("JOB_TIMINGS", jobTimings);
  observe("RANGES", ranges);
  observe("LEARNED", learned);

  console.log(`SUMMARY pass=${passed} fail=${failed} skip=${skipped} calls=${calls.length} credit_depleted=${creditDepleted}`);
  if (creditDepleted) console.error("CREDITS DEPLETED");
  process.exitCode = creditDepleted ? 3 : (failed === 0 ? 0 : 1);
}

main().catch(async (error) => {
  fail("suite", error.stack ?? error.message);
  try {
    const usageEnd = await usageSummary("usage end after failure");
    observe("USAGE_END_AFTER_FAILURE", usageEnd);
  } catch {
    // Preserve the original failure.
  }
  observe("LEARNED", learned);
  console.log(`SUMMARY pass=${passed} fail=${failed} skip=${skipped} calls=${calls.length} credit_depleted=${creditDepleted}`);
  process.exitCode = creditDepleted ? 3 : 1;
});
