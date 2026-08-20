#!/usr/bin/env node

import process from "node:process";
import { randomUUID } from "node:crypto";

const BASE_URL = "https://api.humalike.com";
const API_KEY = process.env.HUMALIKE_API_KEY;
const POLL_MS = Number(process.env.HUMALIKE_POLL_MS ?? 3000);
const JOB_TIMEOUT_MS = Number(process.env.HUMALIKE_JOB_TIMEOUT_MS ?? 12 * 60_000);
const AUDIT_TIMEOUT_MS = Number(process.env.HUMALIKE_AUDIT_TIMEOUT_MS ?? 20 * 60_000);

if (!API_KEY) {
  console.error("HUMALIKE_API_KEY is required");
  process.exit(2);
}

let passed = 0;
let failed = 0;
let skipped = 0;
let creditDepleted = false;
const calls = [];
const jobTimings = {};

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

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

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

async function request(label, method, path, body, { timeoutMs = 180_000, billable = false } = {}) {
  if (billable && creditDepleted) {
    skip(label, "billable call suppressed after HTTP 402");
    return null;
  }

  const started = Date.now();
  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${API_KEY}`,
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
  check(`${record.label} returns x-request-id`, typeof record.headers["x-request-id"] === "string" && record.headers["x-request-id"].length > 0);
}

function assertError(record, status, code, detailLoc) {
  if (!record) return;
  equal(`${record.label} status`, record.status, status);
  check(`${record.label} error envelope`, hasExactKeys(record.body, ["error"]) && isObject(record.body.error));
  equal(`${record.label} error code`, record.body?.error?.code, code);
  check(`${record.label} error message`, typeof record.body?.error?.message === "string" && record.body.error.message.length > 0);
  if (detailLoc) {
    check(`${record.label} validation details`, Array.isArray(record.body?.error?.details) && record.body.error.details.some(
      (detail) => Array.isArray(detail.loc) && detail.loc.join(".") === detailLoc,
    ));
  }
}

function assertPersona(label, persona, { allowEmptyFields = false } = {}) {
  check(`${label} exact resource keys`, hasExactKeys(persona, ["persona_id", "fields", "system_prompt", "markdown"]));
  check(`${label} persona_id`, typeof persona?.persona_id === "string" && persona.persona_id.length > 0);
  check(`${label} flat string fields`, valuesAreStrings(persona?.fields)
    && (allowEmptyFields || Object.keys(persona.fields).length > 0));
  check(`${label} system_prompt`, typeof persona?.system_prompt === "string" && persona.system_prompt.length > 0);
  check(`${label} markdown`, typeof persona?.markdown === "string" && persona.markdown.length > 0);
}

function assertDistribution(label, distribution) {
  check(`${label} numeric distribution`, hasExactKeys(distribution, ["min", "max", "mean", "sd", "integer"])
    && ["min", "max", "mean", "sd"].every((key) => typeof distribution[key] === "number")
    && typeof distribution.integer === "boolean");
}

function assertBlueprint(label, blueprint) {
  check(`${label} blueprint keys`, hasExactKeys(
    blueprint,
    ["domain", "language", "order", "fields", "constraints", "style_axes", "name_origins", "rationale", "sources"],
  ));
  check(`${label} domain`, typeof blueprint?.domain === "string" && blueprint.domain.length > 0);
  check(`${label} order`, Array.isArray(blueprint?.order) && blueprint.order.every((item) => typeof item === "string"));
  check(`${label} fields`, Array.isArray(blueprint?.fields) && blueprint.fields.length > 0);
  for (const [index, field] of (blueprint?.fields ?? []).entries()) {
    const fieldLabel = `${label} field[${index}]`;
    check(`${fieldLabel} base schema`, hasExactKeys(
      field,
      ["name", "label", "kind", "description", "formula", "parents", "categorical", "numeric", "conditionals", "ordered_values"],
    ));
    check(`${fieldLabel} kind`, ["categorical", "numeric", "text", "derived"].includes(field.kind));
    check(`${fieldLabel} parents`, Array.isArray(field.parents) && field.parents.every((parent) => typeof parent === "string"));
    if (field.categorical !== null) {
      check(`${fieldLabel} categorical`, hasExactKeys(field.categorical, ["weights"])
        && isObject(field.categorical.weights)
        && Object.values(field.categorical.weights).every((weight) => typeof weight === "number"));
    }
    if (field.numeric !== null) assertDistribution(`${fieldLabel} numeric`, field.numeric);
    if (field.conditionals !== undefined) {
      check(`${fieldLabel} conditionals`, Array.isArray(field.conditionals));
      for (const [conditionalIndex, conditional] of field.conditionals.entries()) {
        check(`${fieldLabel} conditional[${conditionalIndex}]`, hasExactKeys(conditional, ["when", "categorical", "numeric"])
          && isObject(conditional.when));
        if (conditional.categorical !== null) {
          check(`${fieldLabel} conditional[${conditionalIndex}] categorical`, hasExactKeys(conditional.categorical, ["weights"]));
        }
        if (conditional.numeric !== null) assertDistribution(`${fieldLabel} conditional[${conditionalIndex}] numeric`, conditional.numeric);
      }
    }
  }
  check(`${label} constraints`, Array.isArray(blueprint?.constraints));
  for (const [index, constraint] of (blueprint?.constraints ?? []).entries()) {
    check(`${label} constraint[${index}]`, hasExactKeys(constraint, ["name", "lhs", "op", "rhs"])
      && [constraint.name, constraint.lhs, constraint.op, constraint.rhs].every((item) => typeof item === "string"));
  }
}

function assertDiversity(label, diversity) {
  check(`${label} exact diversity schema`, hasExactKeys(
    diversity,
    ["max_pairwise_similarity", "mean_pairwise_similarity", "duplicate_pairs"],
  ));
  check(`${label} diversity values`, typeof diversity?.max_pairwise_similarity === "number"
    && typeof diversity?.mean_pairwise_similarity === "number"
    && Number.isInteger(diversity?.duplicate_pairs));
}

function assertMarginals(label, marginals) {
  check(`${label} marginals`, Array.isArray(marginals));
  for (const [index, marginal] of (marginals ?? []).entries()) {
    check(`${label} marginal[${index}] schema`, hasExactKeys(marginal, ["attribute", "cells", "total_variation_distance"]));
    check(`${label} marginal[${index}] cells`, Array.isArray(marginal.cells) && marginal.cells.every(
      (cell) => hasExactKeys(cell, ["key", "requested", "achieved"])
        && typeof cell.key === "string"
        && typeof cell.requested === "number"
        && typeof cell.achieved === "number",
    ));
  }
}

function assertReport(label, report) {
  check(`${label} exact top-level schema`, hasExactKeys(
    report,
    ["health_score", "summary", "interactions", "interaction_totals", "per_user", "findings"],
    ["id"],
  ));
  check(`${label} health_score`, typeof report?.health_score === "number" && report.health_score >= 0 && report.health_score <= 1);
  check(`${label} summary`, typeof report?.summary === "string" && report.summary.length > 0);
  check(`${label} interactions`, Array.isArray(report?.interactions));
  for (const [index, interaction] of (report?.interactions ?? []).entries()) {
    check(`${label} interaction[${index}]`, hasExactKeys(interaction, ["type", "topic", "participants", "message_ids"])
      && ["transactional", "bonding", "venting", "banter", "friction", "hostile"].includes(interaction.type)
      && Array.isArray(interaction.participants)
      && interaction.participants.every((participant) => hasExactKeys(participant, ["name", "stance"], ["user_id"]))
      && Array.isArray(interaction.message_ids));
  }
  check(`${label} interaction_totals`, Array.isArray(report?.interaction_totals)
    && report.interaction_totals.length === 6
    && report.interaction_totals.every((item) => hasExactKeys(item, ["type", "count"]) && Number.isInteger(item.count)));
  check(`${label} per_user`, Array.isArray(report?.per_user));
  for (const [index, user] of (report?.per_user ?? []).entries()) {
    check(`${label} per_user[${index}]`, hasExactKeys(
      user,
      ["name", "reception", "frustration", "trend", "behaviors", "evidence", "confidence", "interaction_count", "dominant_type", "distribution", "key_moments"],
      ["user_id", "note"],
    ));
    check(`${label} per_user[${index}] enums`, ["engaged", "neutral", "bored", "annoyed", "churn_risk"].includes(user.reception)
      && ["improving", "stable", "declining"].includes(user.trend));
    check(`${label} per_user[${index}] distribution`, Array.isArray(user.distribution)
      && user.distribution.every((item) => hasExactKeys(item, ["type", "count"])));
    check(`${label} per_user[${index}] key moments`, Array.isArray(user.key_moments)
      && user.key_moments.every((item) => hasExactKeys(item, ["label", "type", "message_ids"], ["agent_critique"])));
  }
  check(`${label} findings`, Array.isArray(report?.findings));
  for (const [index, finding] of (report?.findings ?? []).entries()) {
    check(`${label} finding[${index}]`, hasExactKeys(
      finding,
      ["issue", "severity", "affected_users", "evidence", "recommendation", "confidence"],
      ["before_message_id", "rewritten_reply", "suggested_component", "how_it_helps"],
    ) && ["low", "medium", "high"].includes(finding.severity));
  }
}

function assertPopulationResource(label, resource) {
  check(`${label} resource schema`, hasExactKeys(
    resource,
    ["id", "created_at", "updated_at", "status", "progress", "prompt", "count", "grounding", "result", "error"],
  ));
  check(`${label} timestamps`, typeof resource.created_at === "string" && typeof resource.updated_at === "string");
  check(`${label} status`, ["pending", "running", "succeeded", "failed"].includes(resource.status));
  check(`${label} request echo`, typeof resource.prompt === "string"
    && Number.isInteger(resource.count)
    && ["off", "web", "research"].includes(resource.grounding));
  if (resource.progress !== null) {
    check(`${label} progress schema`, hasExactKeys(resource.progress, ["phase", "produced", "total"])
      && typeof resource.progress.phase === "string"
      && Number.isInteger(resource.progress.produced)
      && Number.isInteger(resource.progress.total));
  }
}

function assertEnhancementResource(label, resource) {
  check(`${label} resource schema`, hasExactKeys(
    resource,
    ["id", "created_at", "updated_at", "status", "source", "grounding", "persona", "error"],
  ));
  check(`${label} timestamps`, typeof resource.created_at === "string" && typeof resource.updated_at === "string");
  check(`${label} status`, ["pending", "running", "succeeded", "failed"].includes(resource.status));
  check(`${label} request echo`, typeof resource.source === "string"
    && ["off", "web", "research"].includes(resource.grounding));
}

function assertEvaluationResource(label, resource) {
  check(`${label} resource schema`, hasExactKeys(
    resource,
    ["id", "created_at", "updated_at", "status", "progress", "personas", "blueprint", "result", "error"],
  ));
  check(`${label} timestamps`, typeof resource.created_at === "string" && typeof resource.updated_at === "string");
  check(`${label} status`, ["pending", "running", "succeeded", "failed"].includes(resource.status));
  check(`${label} input echoes`, Array.isArray(resource.personas) && (resource.blueprint === null || isObject(resource.blueprint)));
  if (resource.progress !== null) {
    check(`${label} progress schema`, hasExactKeys(resource.progress, ["phase"]));
  }
}

async function pollGet(label, path, terminal, timeoutMs = JOB_TIMEOUT_MS, validatePoll = undefined) {
  const started = Date.now();
  const states = [];
  for (;;) {
    const record = await request(`${label} poll`, "GET", path, undefined, { timeoutMs: 60_000 });
    if (!record) return null;
    assertRequestMetadata(record);
    if (record.status !== 200) throw new HttpError(label, record);
    if (validatePoll) validatePoll(record.body);
    const state = JSON.stringify({ status: record.body?.status, progress: record.body?.progress });
    if (!states.includes(state)) states.push(state);
    if (terminal(record.body)) {
      jobTimings[label] = { elapsed_ms: Date.now() - started, states: states.map(JSON.parse) };
      observe(`${label} lifecycle`, jobTimings[label]);
      return record.body;
    }
    if (Date.now() - started > timeoutMs) throw new Error(`${label} timed out`);
    await sleep(POLL_MS);
  }
}

async function usageSummary(label) {
  const record = await request(label, "POST", "/v1/credits/projections/usage-summary", {});
  if (!record) return null;
  equal(`${label} status`, record.status, 200);
  assertRequestMetadata(record);
  check(`${label} schema`, hasExactKeys(record.body, ["total_calls", "total_credits", "per_component", "daily_series"]));
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

async function main() {
  const usageStart = await usageSummary("usage start");
  const terminalPollTargets = [];

  const extractMissing = await request("extract missing transcript", "POST", "/v1/social-learning/actions/extract", {});
  assertRequestMetadata(extractMissing);
  assertError(extractMissing, 422, "validation_failed", "transcript");

  const extractEmpty = await request("extract empty transcript", "POST", "/v1/social-learning/actions/extract", {
    transcript: { messages: [] },
  });
  assertRequestMetadata(extractEmpty);
  assertError(extractEmpty, 422, "validation_failed", "transcript.messages");

  const tinyExtract = await request("extract tiny", "POST", "/v1/social-learning/actions/extract", {
    transcript: { source: "live-contract-tiny", messages: [{ id: "t1", speaker: "Ada", text: "hello" }] },
  }, { billable: true });
  if (tinyExtract && tinyExtract.status === 200) {
    assertRequestMetadata(tinyExtract);
    check("extract tiny exact top-level schema", hasExactKeys(tinyExtract.body, ["prompt_block", "profile"]));
    check("extract tiny prompt block", typeof tinyExtract.body.prompt_block === "string" && tinyExtract.body.prompt_block.length > 0);
    check("extract tiny profile object", isObject(tinyExtract.body.profile));
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
    const profile = richExtract.body.profile;
    check("extract profile exact top-level schema", hasExactKeys(
      profile,
      ["summary", "register", "style", "lexicon", "banned_phrases", "address", "taboos", "humor", "roles", "norms", "in_jokes", "meta"],
    ));
    check("extract profile register", hasExactKeys(profile?.register, ["formality", "warmth", "casing", "notes", "confidence"]));
    check("extract profile style", hasExactKeys(profile?.style, ["length", "formatting", "emoji"]));
    check("extract profile collection fields", ["lexicon", "banned_phrases", "taboos", "roles", "norms", "in_jokes"]
      .every((key) => Array.isArray(profile?.[key]))
      && isObject(profile.address)
      && isObject(profile.humor));
    check("extract profile address schema", hasExactKeys(profile.address, ["default", "deference"])
      && Array.isArray(profile.address.deference));
    check("extract profile humor schema", hasExactKeys(profile.humor, ["style", "rules"])
      && Array.isArray(profile.humor.rules));
    check("extract profile lexicon item schema", profile.lexicon.every((item) => hasExactKeys(item, ["term", "meaning", "usage"])));
    check("extract profile taboo item schema", profile.taboos.every((item) => hasExactKeys(item, ["rule", "scope", "evidence"])));
    check("extract profile norm item schema", profile.norms.every((item) => hasExactKeys(item, ["rule", "type", "evidence", "confidence"])
      && item.evidence.every((evidence) => hasExactKeys(evidence, ["breach", "sanction"]))));
    check("extract profile meta", hasExactKeys(profile?.meta, ["source", "channels", "message_count"])
      && profile.meta.message_count === richMessages.length
      && Array.isArray(profile.meta.channels));
    check("rich extraction differs from tiny", tinyExtract?.status !== 200 || richExtract.body.prompt_block !== tinyExtract.body.prompt_block);
  } else if (richExtract && richExtract.status !== 402) fail("extract rich status", `HTTP ${richExtract.status}`);

  const foreseeWrong = await request("foresee wrong fields", "POST", "/v1/foresee/actions/foresee", {
    conversation: [{ speaker: "customer", text: "hello" }],
    draft: "hi",
  });
  assertRequestMetadata(foreseeWrong);
  assertError(foreseeWrong, 422, "validation_failed");
  check("foresee wrong fields identify transcript and candidate_reply", ["transcript", "candidate_reply"].every((field) =>
    foreseeWrong?.body?.error?.details?.some((detail) => detail.loc?.join(".") === field)));

  const foreseeEmpty = await request("foresee empty transcript", "POST", "/v1/foresee/actions/foresee", {
    transcript: [],
    candidate_reply: "I can help.",
  });
  assertRequestMetadata(foreseeEmpty);
  assertError(foreseeEmpty, 422, "validation_failed", "transcript");

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
    check("foresee mental_state", Array.isArray(foresee.body.mental_state) && foresee.body.mental_state.length === 1
      && foresee.body.mental_state.every((state) => hasExactKeys(state, ["name", "beliefs", "goals", "emotions"])
        && Array.isArray(state.beliefs)
        && Array.isArray(state.goals)
        && Array.isArray(state.emotions)
        && state.emotions.every((emotion) => hasExactKeys(emotion, ["type", "intensity"])
          && typeof emotion.intensity === "number" && emotion.intensity >= 0 && emotion.intensity <= 1)));
    check("foresee predicted_reaction", Array.isArray(foresee.body.predicted_reaction)
      && foresee.body.predicted_reaction.length === 1
      && foresee.body.predicted_reaction.every((reaction) => hasExactKeys(
        reaction,
        ["name", "summary", "predicted_message", "risk"],
      ) && ["low", "medium", "high"].includes(reaction.risk)));
    check("foresee refined reply", typeof foresee.body.refined_reply === "string" && foresee.body.refined_reply.length > 0);
    check("foresee rationale", typeof foresee.body.refinement_rationale === "string" && foresee.body.refinement_rationale.length > 0);
  } else if (foresee && foresee.status !== 402) fail("foresee valid status", `HTTP ${foresee.status}`);

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

  let analyzeReport;
  let reportId;
  if (analyze?.status === 200) {
    assertRequestMetadata(analyze);
    analyzeReport = analyze.body;
    assertReport("analyze", analyzeReport);
    reportId = analyze.body.id
      ?? analyze.headers["x-report-id"]
      ?? analyze.headers.location?.match(/[0-9a-f-]{36}/i)?.[0];
    check("analyze omits persisted report id", reportId === undefined);
    const requestIdProbe = await request(
      "report request-id probe",
      "GET",
      `/v1/social-observability/repositories/Report/by-id/${analyze.headers["x-request-id"]}`,
    );
    equal("request id is not report id status", requestIdProbe.status, 200);
    equal("request id is not report id body", requestIdProbe.body, null);
  } else if (analyze && analyze.status !== 402) fail("analyze valid status", `HTTP ${analyze.status}`);

  if (reportId) {
    const reportRead = await request("report read", "GET", `/v1/social-observability/repositories/Report/by-id/${reportId}`);
    assertRequestMetadata(reportRead);
    equal("report read status", reportRead.status, 200);
    check("report repository schema", hasExactKeys(reportRead.body, ["agent_name", "health_score", "report"]));
    equal("report repository agent_name", reportRead.body?.agent_name, "support_bot");
    equal("report repository health_score", reportRead.body?.health_score, analyzeReport?.health_score);
    assertReport("report repository report", reportRead.body?.report);
  } else {
    skip("report read", "production analyze response exposes no report id or Location header");
  }

  const reportAbsent = await request("report absent", "GET", `/v1/social-observability/repositories/Report/by-id/${randomUUID()}`);
  assertRequestMetadata(reportAbsent);
  equal("report absent status", reportAbsent.status, 200);
  equal("report absent body", reportAbsent.body, null);

  const reportMalformed = await request("report malformed id", "GET", "/v1/social-observability/repositories/Report/by-id/not-a-uuid");
  assertRequestMetadata(reportMalformed);
  assertError(reportMalformed, 400, "VALIDATION_ERROR");

  const auditMissing = await request("audit prepare missing raw_text", "POST", "/v1/social-observability/actions/audit_prepare", {});
  assertRequestMetadata(auditMissing);
  assertError(auditMissing, 422, "validation_failed", "raw_text");

  const auditOversized = await request("audit prepare oversized chars", "POST", "/v1/social-observability/actions/audit_prepare", {
    raw_text: "x".repeat(300_001),
  }, { timeoutMs: 60_000 });
  assertRequestMetadata(auditOversized);
  assertError(auditOversized, 422, "validation_failed", "raw_text");

  const auditMalformed = await request("audit prepare unparsable", "POST", "/v1/social-observability/actions/audit_prepare", {
    raw_text: "This text contains no speaker-labelled conversation.",
  }, { billable: true });
  if (auditMalformed?.status !== 402) {
    assertRequestMetadata(auditMalformed);
    assertError(auditMalformed, 400, "VALIDATION_ERROR");
  }

  const tooManyLines = Array.from({ length: 251 }, (_, index) => `[12:${String(index % 60).padStart(2, "0")}] ${index % 2 ? "support_bot" : "Casey"}: message ${index + 1}`).join("\n");
  const auditTooMany = await request("audit prepare over 250 messages", "POST", "/v1/social-observability/actions/audit_prepare", {
    raw_text: tooManyLines,
  }, { timeoutMs: 180_000, billable: true });
  if (auditTooMany?.status !== 402) {
    assertRequestMetadata(auditTooMany);
    assertError(auditTooMany, 400, "VALIDATION_ERROR");
    check("audit message cap error names counts", /251/.test(auditTooMany.body?.error?.message ?? "")
      && /250/.test(auditTooMany.body?.error?.message ?? ""));
  }

  const rawAudit = [
    "[10:01] Casey: the export broke again",
    "[10:02] support_bot: Have you tried clearing your cache?",
    "[10:03] Casey: yes, twice already",
    "[10:04] support_bot: Please retry later.",
    "[10:05] Casey: that does not help",
    "[10:06] support_bot: Is there anything else?",
    "[10:07] Casey: no, i will do it manually",
    "[10:08] Jordan: mine is failing too",
  ].join("\n");
  const auditPrepare = await request("audit prepare valid", "POST", "/v1/social-observability/actions/audit_prepare", {
    raw_text: rawAudit,
  }, { timeoutMs: 180_000, billable: true });

  let auditFinal;
  if (auditPrepare?.status === 200) {
    assertRequestMetadata(auditPrepare);
    check("audit prepare exact schema", hasExactKeys(auditPrepare.body, ["run_id", "messages", "participants", "agent_guess"]));
    check("audit prepare run id", typeof auditPrepare.body.run_id === "string");
    equal("audit prepare parsed count", auditPrepare.body.messages, 8);
    check("audit prepare participant order", JSON.stringify(auditPrepare.body.participants) === JSON.stringify(["Casey", "support_bot", "Jordan"]));
    check("audit prepare guess type", auditPrepare.body.agent_guess === null || typeof auditPrepare.body.agent_guess === "string");

    const runId = auditPrepare.body.run_id;
    const auditWrong = await request("audit launch wrong participant", "POST", "/v1/social-observability/actions/audit_launch", {
      run_id: runId,
      agent_name: "support-bot-typo",
    });
    assertRequestMetadata(auditWrong);
    assertError(auditWrong, 400, "VALIDATION_ERROR");
    check("audit wrong participant detail", Array.isArray(auditWrong.body?.error?.details)
      && auditWrong.body.error.details.some((detail) => detail.field === "agent_name"));

    const auditLaunch = await request("audit launch valid", "POST", "/v1/social-observability/actions/audit_launch", {
      run_id: runId,
      agent_name: "support_bot",
    }, { billable: true });
    if (auditLaunch?.status === 200) {
      assertRequestMetadata(auditLaunch);
      check("audit launch exact schema", hasExactKeys(auditLaunch.body, ["run_id", "agent_name", "status"]));
      equal("audit launch run id", auditLaunch.body.run_id, runId);
      equal("audit launch agent", auditLaunch.body.agent_name, "support_bot");
      equal("audit launch initial status", auditLaunch.body.status, "queued");

      const auditRepeat = await request("audit launch repeat", "POST", "/v1/social-observability/actions/audit_launch", {
        run_id: runId,
        agent_name: "Casey",
      });
      assertRequestMetadata(auditRepeat);
      equal("audit repeat status code", auditRepeat.status, 200);
      check("audit repeat exact schema", hasExactKeys(auditRepeat.body, ["run_id", "agent_name", "status"]));
      equal("audit repeat preserves first agent", auditRepeat.body.agent_name, "support_bot");

      const auditStarted = Date.now();
      const stages = [];
      let completedSeenAt = null;
      for (;;) {
        const poll = await request("audit projection poll", "POST", "/v1/social-observability/projections/audit-run", { run_id: runId });
        assertRequestMetadata(poll);
        if (poll.status !== 200) throw new HttpError("audit projection", poll);
        const signature = {
          status: poll.body?.status,
          stage: poll.body?.stage,
          report: poll.body?.report !== null,
          read: poll.body?.read !== null,
          verdicts: poll.body?.verdicts !== null,
          replies: Array.isArray(poll.body?.replies) ? poll.body.replies.length : null,
        };
        if (!stages.some((item) => JSON.stringify(item) === JSON.stringify(signature))) stages.push(signature);
        const sectionsDone = poll.body?.report && poll.body?.read && poll.body?.verdicts !== null;
        if (sectionsDone && completedSeenAt === null) completedSeenAt = Date.now();
        if (sectionsDone && Date.now() - completedSeenAt >= Math.max(POLL_MS, 5000)) {
          auditFinal = poll.body;
          break;
        }
        if (Date.now() - auditStarted > AUDIT_TIMEOUT_MS) throw new Error("audit projection timed out");
        await sleep(POLL_MS);
      }
      jobTimings.audit = { elapsed_ms: Date.now() - auditStarted, states: stages };
      terminalPollTargets.push({ label: "audit terminal", method: "POST", path: "/v1/social-observability/projections/audit-run", body: { run_id: runId } });
      observe("audit lifecycle", jobTimings.audit);

      check("audit projection exact schema", hasExactKeys(
        auditFinal,
        ["run_id", "agent_name", "transcript", "report", "read", "verdicts", "replies"],
        ["status", "stage"],
      ));
      equal("audit projection run id", auditFinal.run_id, runId);
      equal("audit projection agent", auditFinal.agent_name, "support_bot");
      check("audit parsed transcript", hasExactKeys(auditFinal.transcript, ["messages", "source"])
        && auditFinal.transcript.messages.length === 8
        && auditFinal.transcript.messages.every((message) => hasExactKeys(
          message,
          ["id", "speaker", "text", "user_id", "channel", "timestamp", "reply_to"],
        )));
      assertReport("audit report", auditFinal.report);
      check("audit read exact schema", hasExactKeys(auditFinal.read, [], ["prompt_block", "portrait", "mental_state", "profiles"]));
      if (auditFinal.read.prompt_block !== undefined) check("audit read prompt_block", auditFinal.read.prompt_block === null || typeof auditFinal.read.prompt_block === "string");
      if (auditFinal.read.portrait !== undefined) check("audit read portrait", auditFinal.read.portrait === null
        || hasExactKeys(auditFinal.read.portrait, ["role", "personality", "register"]));
      if (auditFinal.read.mental_state !== undefined) check("audit read mental_state", auditFinal.read.mental_state === null
        || (Array.isArray(auditFinal.read.mental_state) && auditFinal.read.mental_state.every(
          (state) => hasExactKeys(state, ["name", "beliefs", "goals", "emotions"])
            && state.emotions.every((emotion) => hasExactKeys(emotion, ["type", "intensity"])),
        )));
      if (auditFinal.read.profiles !== undefined) check("audit read profiles", auditFinal.read.profiles === null
        || (Array.isArray(auditFinal.read.profiles) && auditFinal.read.profiles.every(
          (profile) => hasExactKeys(profile, ["name", "facts"]) && profile.facts.every((fact) => typeof fact === "string"),
        )));
      check("audit verdicts schema", Array.isArray(auditFinal.verdicts) && auditFinal.verdicts.every(
        (verdict) => hasExactKeys(verdict, ["index", "risk", "summary", "predicted_message"])
          && Number.isInteger(verdict.index)
          && typeof verdict.risk === "string",
      ));
      check("audit replies schema", Array.isArray(auditFinal.replies) && auditFinal.replies.every(
        (reply) => hasExactKeys(reply, ["index", "reply", "messages", "risk"])
          && Number.isInteger(reply.index)
          && Array.isArray(reply.messages),
      ));
    } else if (auditLaunch && auditLaunch.status !== 402) fail("audit launch valid status", `HTTP ${auditLaunch.status}`);
  } else if (auditPrepare && auditPrepare.status !== 402) fail("audit prepare valid status", `HTTP ${auditPrepare.status}`);

  const auditAbsent = await request("audit projection absent", "POST", "/v1/social-observability/projections/audit-run", {
    run_id: randomUUID(),
  });
  assertRequestMetadata(auditAbsent);
  assertError(auditAbsent, 400, "VALIDATION_ERROR");

  const populationAbsent = await request("population absent", "GET", `/v1/personas/repositories/Population/by-id/${randomUUID()}`);
  assertRequestMetadata(populationAbsent);
  equal("population absent status", populationAbsent.status, 200);
  equal("population absent body", populationAbsent.body, null);

  const generateEmpty = await request("generate empty prompt", "POST", "/v1/personas/actions/generate", {
    prompt: "",
    count: 1,
    grounding: "off",
  });
  assertRequestMetadata(generateEmpty);
  assertError(generateEmpty, 422, "validation_failed", "prompt");

  const generate = await request("generate population", "POST", "/v1/personas/actions/generate", {
    prompt: "Two fictional community librarians with varied ages and weekly reading hours",
    count: 2,
    grounding: "off",
  }, { billable: true });

  let population;
  if (generate?.status === 200) {
    assertRequestMetadata(generate);
    check("generate initial exact schema", hasExactKeys(generate.body, ["id", "status"]));
    equal("generate initial status", generate.body.status, "pending");
    population = await pollGet(
      "population",
      `/v1/personas/repositories/Population/by-id/${generate.body.id}`,
      (body) => ["succeeded", "failed"].includes(body.status),
      JOB_TIMEOUT_MS,
      (body) => assertPopulationResource(`population ${body.status}`, body),
    );
    equal("population terminal status", population.status, "succeeded");
    if (population.status === "succeeded") {
      terminalPollTargets.push({
        label: "population terminal",
        method: "GET",
        path: `/v1/personas/repositories/Population/by-id/${generate.body.id}`,
      });
      assertPopulationResource("population final", population);
      const result = population.result;
      check("population result exact schema", hasExactKeys(result, ["personas", "blueprint", "diversity", "marginals"]));
      equal("population count", result.personas.length, 2);
      result.personas.forEach((persona, index) => assertPersona(`population persona[${index}]`, persona));
      assertBlueprint("population", result.blueprint);
      const fieldNames = result.blueprint.fields.map((field) => field.name).sort();
      check("population persona keys match blueprint", result.personas.every(
        (persona) => JSON.stringify(Object.keys(persona.fields).sort()) === JSON.stringify(fieldNames),
      ));
      assertDiversity("population", result.diversity);
      assertMarginals("population", result.marginals);
    }
  } else if (generate && generate.status !== 402) fail("generate population status", `HTTP ${generate.status}`);

  const enhancementAbsent = await request("enhancement absent", "GET", `/v1/personas/repositories/Enhancement/by-id/${randomUUID()}`);
  assertRequestMetadata(enhancementAbsent);
  equal("enhancement absent status", enhancementAbsent.status, 200);
  equal("enhancement absent body", enhancementAbsent.body, null);

  const enhanceEmpty = await request("enhance empty persona", "POST", "/v1/personas/actions/enhance", {
    persona: "",
    grounding: "off",
  });
  assertRequestMetadata(enhanceEmpty);
  assertError(enhanceEmpty, 422, "validation_failed", "persona");

  const enhancementMarker = `contract-${randomUUID()}`;
  const seedFacts = `Iris Vale is exactly 47 years old, lives in Turku, repairs antique clocks, always carries a cobalt-blue notebook, and uses the private marker ${enhancementMarker}.`;
  const enhance = await request("enhance persona", "POST", "/v1/personas/actions/enhance", {
    persona: seedFacts,
    grounding: "off",
  }, { billable: true });
  if (enhance?.status === 200) {
    assertRequestMetadata(enhance);
    check("enhance initial exact schema", hasExactKeys(enhance.body, ["id", "status"]));
    check("enhance initial status", ["pending", "running", "succeeded"].includes(enhance.body.status));
    const enhancement = await pollGet(
      "enhancement",
      `/v1/personas/repositories/Enhancement/by-id/${enhance.body.id}`,
      (body) => ["succeeded", "failed"].includes(body.status),
      JOB_TIMEOUT_MS,
      (body) => assertEnhancementResource(`enhancement ${body.status}`, body),
    );
    equal("enhancement terminal status", enhancement.status, "succeeded");
    if (enhancement.status === "succeeded") {
      terminalPollTargets.push({
        label: "enhancement terminal",
        method: "GET",
        path: `/v1/personas/repositories/Enhancement/by-id/${enhance.body.id}`,
      });
      assertEnhancementResource("enhancement final", enhancement);
      equal("enhancement source echo", enhancement.source, seedFacts);
      equal("enhancement grounding echo", enhancement.grounding, "off");
      equal("enhancement success error", enhancement.error, null);
      assertPersona("enhanced persona", enhancement.persona, { allowEmptyFields: true });
      equal("enhancement fields are empty", Object.keys(enhancement.persona.fields).length, 0);
      const searchable = JSON.stringify(enhancement.persona).toLowerCase();
      check("enhancement preserves age", searchable.includes("47"));
      check("enhancement preserves city", searchable.includes("turku"));
      check("enhancement preserves occupation", searchable.includes("antique") && searchable.includes("clock"));
      check("enhancement preserves notebook fact", searchable.includes("cobalt") && searchable.includes("notebook"));
      check("enhancement preserves unique marker", searchable.includes(enhancementMarker));
    }
  } else if (enhance && enhance.status !== 402) fail("enhance persona status", `HTTP ${enhance.status}`);

  const evaluationAbsent = await request("evaluation absent", "GET", `/v1/personas/repositories/Evaluation/by-id/${randomUUID()}`);
  assertRequestMetadata(evaluationAbsent);
  equal("evaluation absent status", evaluationAbsent.status, 200);
  equal("evaluation absent body", evaluationAbsent.body, null);

  if (population?.status === "succeeded") {
    const validatePass = await request("validate generated population", "POST", "/v1/personas/actions/validate", {
      personas: population.result.personas,
      blueprint: population.result.blueprint,
    }, { billable: true });
    if (validatePass?.status === 200) {
      assertRequestMetadata(validatePass);
      check("validate pass initial exact schema", hasExactKeys(validatePass.body, ["id", "status"]));
      equal("validate pass initial status", validatePass.body.status, "pending");
      const evaluation = await pollGet(
        "evaluation pass",
        `/v1/personas/repositories/Evaluation/by-id/${validatePass.body.id}`,
        (body) => ["succeeded", "failed"].includes(body.status),
        JOB_TIMEOUT_MS,
        (body) => assertEvaluationResource(`evaluation pass ${body.status}`, body),
      );
      equal("evaluation pass job status", evaluation.status, "succeeded");
      equal("evaluation generated passed", evaluation.result?.passed, true);
      assertEvaluation("evaluation pass", evaluation);
      terminalPollTargets.push({
        label: "evaluation pass terminal",
        method: "GET",
        path: `/v1/personas/repositories/Evaluation/by-id/${validatePass.body.id}`,
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
  const validateFail = await request("validate constraint violation", "POST", "/v1/personas/actions/validate", {
    personas: [invalidPersona],
    blueprint: customBlueprint,
  }, { billable: true });
  if (validateFail?.status === 200) {
    assertRequestMetadata(validateFail);
    check("validate fail initial exact schema", hasExactKeys(validateFail.body, ["id", "status"]));
    equal("validate fail initial status", validateFail.body.status, "pending");
    const evaluation = await pollGet(
      "evaluation fail",
      `/v1/personas/repositories/Evaluation/by-id/${validateFail.body.id}`,
      (body) => ["succeeded", "failed"].includes(body.status),
      JOB_TIMEOUT_MS,
      (body) => assertEvaluationResource(`evaluation fail ${body.status}`, body),
    );
    equal("evaluation fail job status", evaluation.status, "succeeded");
    equal("evaluation constraint verdict", evaluation.result?.passed, false);
    assertEvaluation("evaluation fail", evaluation);
    const gates = evaluation.result?.scorecards?.[0]?.gates ?? [];
    const schemaGate = gates.find((gate) => gate.name === "schema");
    const constraintsGate = gates.find((gate) => gate.name === "constraints");
    equal("nonnumeric field fails schema gate", schemaGate?.passed, false);
    check("schema gate names nonnumeric field", /hours='unknown' is not numeric/.test(schemaGate?.detail ?? ""));
    equal("violated constraint fails aggregate gate", constraintsGate?.passed, false);
    check("constraint gate names violation", /age_nonnegative/.test(constraintsGate?.detail ?? ""));
    terminalPollTargets.push({
      label: "evaluation fail terminal",
      method: "GET",
      path: `/v1/personas/repositories/Evaluation/by-id/${validateFail.body.id}`,
    });
  } else if (validateFail && validateFail.status !== 402) fail("validate constraint violation status", `HTTP ${validateFail.status}`);

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
  const validateNotApplicable = await request("validate non-applicable constraint", "POST", "/v1/personas/actions/validate", {
    personas: [notApplicablePersona],
    blueprint: notApplicableBlueprint,
  }, { billable: true });
  if (validateNotApplicable?.status === 200) {
    const evaluation = await pollGet(
      "evaluation not applicable",
      `/v1/personas/repositories/Evaluation/by-id/${validateNotApplicable.body.id}`,
      (body) => ["succeeded", "failed"].includes(body.status),
      JOB_TIMEOUT_MS,
      (body) => assertEvaluationResource(`evaluation not applicable ${body.status}`, body),
    );
    equal("non-applicable evaluation job status", evaluation.status, "succeeded");
    equal("non-applicable evaluation verdict", evaluation.result?.passed, false);
    assertEvaluation("evaluation not applicable", evaluation);
    const gates = evaluation.result?.scorecards?.[0]?.gates ?? [];
    const schemaGate = gates.find((gate) => gate.name === "schema");
    const constraintsGate = gates.find((gate) => gate.name === "constraints");
    equal("non-applicable probe schema fails", schemaGate?.passed, false);
    equal("non-applicable constraint aggregate passes", constraintsGate?.passed, true);
    check("non-applicable aggregate reports zero applicable", /0 applicable constraint/.test(constraintsGate?.detail ?? ""));
    terminalPollTargets.push({
      label: "evaluation not-applicable terminal",
      method: "GET",
      path: `/v1/personas/repositories/Evaluation/by-id/${validateNotApplicable.body.id}`,
    });
  } else if (validateNotApplicable && validateNotApplicable.status !== 402) {
    fail("validate non-applicable constraint status", `HTTP ${validateNotApplicable.status}`);
  }

  const validateEmpty = await request("validate empty personas", "POST", "/v1/personas/actions/validate", {
    personas: [],
  });
  assertRequestMetadata(validateEmpty);
  assertError(validateEmpty, 422, "validation_failed", "personas");

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
  const rateLimitHeaders = [...new Set(calls.flatMap((call) => Object.keys(call.headers).filter(
    (name) => name.startsWith("x-ratelimit") || name === "retry-after" || name.startsWith("ratelimit"),
  )))];
  observe("RATE_LIMIT_HEADERS", rateLimitHeaders);

  console.log(`SUMMARY pass=${passed} fail=${failed} skip=${skipped} calls=${calls.length} credit_depleted=${creditDepleted}`);
  observe("JOB_TIMINGS", jobTimings);
  if (creditDepleted) console.error("CREDITS DEPLETED");
  process.exitCode = failed === 0 ? 0 : 1;
}

function assertEvaluation(label, evaluation) {
  assertEvaluationResource(label, evaluation);
  const result = evaluation?.result;
  check(`${label} result schema`, hasExactKeys(
    result,
    ["passed", "gates", "scorecards", "diversity", "marginals", "notes"],
  ));
  check(`${label} passed boolean`, typeof result?.passed === "boolean");
  const gateSchema = (gate) => hasExactKeys(gate, ["name", "passed", "score", "detail"])
    && typeof gate.name === "string"
    && typeof gate.passed === "boolean"
    && (gate.score === null || typeof gate.score === "number")
    && typeof gate.detail === "string";
  check(`${label} batch gates`, Array.isArray(result?.gates) && result.gates.every(gateSchema));
  check(`${label} scorecards`, Array.isArray(result?.scorecards) && result.scorecards.every(
    (card) => hasExactKeys(card, ["persona_id", "gates", "soft_scores"])
      && typeof card.persona_id === "string"
      && Array.isArray(card.gates)
      && card.gates.every(gateSchema),
  ));
  if (result?.diversity !== null) assertDiversity(`${label} result`, result.diversity);
  assertMarginals(`${label} result`, result?.marginals);
  check(`${label} notes`, Array.isArray(result?.notes) && result.notes.every((note) => typeof note === "string"));
}

main().catch(async (error) => {
  fail("suite", error.stack ?? error.message);
  try {
    const usageEnd = await usageSummary("usage end after failure");
    observe("USAGE_END_AFTER_FAILURE", usageEnd);
  } catch {
    // Preserve the original failure.
  }
  console.log(`SUMMARY pass=${passed} fail=${failed} skip=${skipped} calls=${calls.length} credit_depleted=${creditDepleted}`);
  process.exitCode = 1;
});
