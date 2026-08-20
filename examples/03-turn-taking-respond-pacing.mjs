#!/usr/bin/env node
/**
 * Phase 3 — decisions, events, and the fully determined pacing math.
 *
 * Submits a batch, records a free event, responds twice (once at the current
 * epoch, once at a stale one), and recomputes every `deliver_at` locally:
 *
 *   typing_i  = min(max_typing_ms, max(500, words_i / typing_wpm * 60000))
 *   deliver_0 = created_at_0 + reading_delay_ms + typing_0
 *   deliver_i = deliver_{i-1} + 200 + typing_i
 *
 * The 500 ms floor and the 200 ms gap are mandatory, `max_typing_ms` caps
 * typing only, and the defaults are 0 / 150 / 8000. Serialized timestamps are
 * compared with the ±10 ms drift the suites allow.
 *
 *   HUMALIKE_API_URL=http://127.0.0.1:8191 HUMALIKE_API_KEY=ak_... \
 *     node examples/03-turn-taking-respond-pacing.mjs
 */

import { HumalikeClient } from '../clients/typescript/client.mjs';

const DRIFT_MS = 10;
const TYPING_FLOOR_MS = 500;
const INTER_BUBBLE_GAP_MS = 200;

function typingMs(words, typingWpm, maxTypingMs) {
  return Math.min(maxTypingMs, Math.max(TYPING_FLOOR_MS, (words / typingWpm) * 60_000));
}

function expectedDeliveries(scheduled, { reading_delay_ms = 0, typing_wpm = 150, max_typing_ms = 8000 } = {}) {
  const out = [];
  scheduled.forEach((entry, index) => {
    const words = entry.content.trim().split(/\s+/).filter(Boolean).length;
    const typing = typingMs(words, typing_wpm, max_typing_ms);
    out.push(index === 0
      ? Date.parse(scheduled[0].created_at) + reading_delay_ms + typing
      : out[index - 1] + INTER_BUBBLE_GAP_MS + typing);
  });
  return out;
}

const hum = new HumalikeClient();
const opened = await hum.openThread({});

const submitted = await hum.submitMessages({
  thread_id: opened.thread.id,
  messages: [
    { sender: 'Ada', content: 'Can you write up where we landed on the migration?' },
    { sender: 'Ada', content: 'Send it in a few short messages please.' },
  ],
  system_prompt: 'You are Grace, a teammate in this chat.',
});
console.log(`submit        decision=${submitted.decision} turn_epoch=${submitted.turn_epoch} tags=[${submitted.tags}]`);

// Events are free and never advance the epoch: {tags: []} exactly.
const event = await hum.recordEvent({
  thread_id: opened.thread.id, type: 'typing_start', sender: 'Ada' });
console.log(`record_event  ${JSON.stringify(event)}`);

const draft = [
  'We are keeping the existing schema for now.',
  'The backfill runs in three batches over the weekend.',
  'I will post the rollback steps in the runbook before Friday.',
].join('\n\n');

// Defaults branch: pacing omitted entirely.
const defaults = await hum.respond({
  thread_id: opened.thread.id, content: draft, turn_epoch: submitted.turn_epoch });
console.log(`respond       bubbles=${defaults.scheduled.length} superseded=${defaults.superseded}`);

const expected = expectedDeliveries(defaults.scheduled);
defaults.scheduled.forEach((entry, index) => {
  const actual = Date.parse(entry.deliver_at);
  const drift = actual - expected[index];
  console.log(`  position ${entry.position}  words=${entry.content.trim().split(/\s+/).length}  drift=${drift}ms  status=${entry.status}`);
  if (Math.abs(drift) > DRIFT_MS) {
    throw new Error(`deliver_at for position ${index} is ${drift}ms off the pacing formula`);
  }
  if (entry.updated_at !== entry.created_at) throw new Error('updated_at must equal created_at at scheduling time');
  if (entry.status !== 'scheduled') throw new Error(`status must be "scheduled", got ${entry.status}`);
  if (index > 0 && actual <= Date.parse(defaults.scheduled[index - 1].deliver_at)) {
    throw new Error('delivery times must strictly increase');
  }
});

// Explicit pacing branch: a low cap proves max_typing_ms caps typing only and
// the 200 ms gap is added outside the cap.
const capped = await hum.respond({
  thread_id: opened.thread.id,
  content: draft,
  turn_epoch: submitted.turn_epoch,
  pacing: { reading_delay_ms: 250, typing_wpm: 40, max_typing_ms: 900 },
});
const cappedExpected = expectedDeliveries(capped.scheduled, {
  reading_delay_ms: 250, typing_wpm: 40, max_typing_ms: 900 });
capped.scheduled.forEach((entry, index) => {
  const drift = Date.parse(entry.deliver_at) - cappedExpected[index];
  if (Math.abs(drift) > DRIFT_MS) {
    throw new Error(`capped pacing for position ${index} is ${drift}ms off the formula`);
  }
});
console.log(`capped pacing ${capped.scheduled.length} bubbles within ±${DRIFT_MS}ms of the formula`);

// A stale epoch is a normal 200 with an exact body, and is not billed.
const before = await hum.usageSummary();
const stale = await hum.respond({
  thread_id: opened.thread.id, content: 'too late', turn_epoch: submitted.turn_epoch - 1 });
const after = await hum.usageSummary();
console.log(`stale respond ${JSON.stringify(stale)}`);
if (JSON.stringify(stale) !== JSON.stringify({ scheduled: [], superseded: true })) {
  throw new Error('a stale epoch must return exactly {scheduled:[],superseded:true}');
}
if (after.total_credits !== before.total_credits) {
  throw new Error(`a superseded respond must not be billed (delta ${after.total_credits - before.total_credits})`);
}
console.log(`billing       superseded respond charged ${after.total_credits - before.total_credits} credits`);

console.log('03-turn-taking-respond-pacing OK');
