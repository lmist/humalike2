#!/usr/bin/env node
/**
 * Phase 6 — full audit: prepare, launch, and poll the staged projection.
 *
 * The projection never exposes `status` or `stage`. Sections become non-null
 * monotonically (report ≤ read ≤ verdicts ≤ replies), `replies` starts as `[]`
 * rather than `null`, and completion is inferred from
 * `replies.length === verdicts.length` holding stable across two polls.
 * Launch is first-write-wins, and terminal polling is free.
 *
 *   HUMALIKE_API_URL=http://127.0.0.1:8191 HUMALIKE_API_KEY=ak_... \
 *     node examples/08-audit-lifecycle.mjs
 */

import { HumalikeClient } from '../clients/typescript/client.mjs';

const hum = new HumalikeClient();

// The parser accepts `[HH:MM] Name: text` and plain `Name: text`, including
// multi-word speakers; timestamps are parsed and discarded.
const rawText = [
  '[09:02] Lin: the export failed again overnight',
  '[09:03] Grace Hopper: can you send the job id?',
  '[09:04] Lin: same one as yesterday, nothing changed',
  '[09:06] Grace Hopper: I will rerun it with a smaller range',
  'Lin: that is what you said yesterday',
  'Grace Hopper: fair. escalating now.',
].join('\n');

const prepared = await hum.auditPrepare({ raw_text: rawText });
console.log(`audit_prepare run_id=${prepared.run_id} messages=${prepared.messages}`);
console.log(`participants  ${prepared.participants.join(' | ')} (first-appearance order)`);
console.log(`agent_guess   ${prepared.agent_guess ?? 'null'}`);
if (prepared.agent_guess !== null && !prepared.participants.includes(prepared.agent_guess)) {
  throw new Error('a non-null agent_guess must be one of the participants');
}

// Readable before launch: agent_name equals agent_guess, sections are null,
// replies is already [].
const beforeLaunch = await hum.auditRun({ run_id: prepared.run_id });
console.log(`pre-launch    agent_name=${beforeLaunch.agent_name} report=${beforeLaunch.report} read=${beforeLaunch.read} verdicts=${beforeLaunch.verdicts} replies=${JSON.stringify(beforeLaunch.replies)}`);
if ('status' in beforeLaunch || 'stage' in beforeLaunch) {
  throw new Error('the projection must not expose status or stage');
}
if (!Array.isArray(beforeLaunch.replies)) throw new Error('replies starts as [], never null');

const agentName = prepared.agent_guess ?? prepared.participants[0];
const launched = await hum.auditLaunch({ run_id: prepared.run_id, agent_name: agentName });
console.log(`audit_launch  ${JSON.stringify(launched)}`);

// First-write-wins: an immediate repeat naming someone else keeps the first
// agent and does not restart the work.
const other = prepared.participants.find((p) => p !== agentName);
if (other) {
  const relaunch = await hum.auditLaunch({ run_id: prepared.run_id, agent_name: other });
  console.log(`relaunch      ${JSON.stringify(relaunch)} (first agent retained)`);
  if (relaunch.agent_name !== agentName) throw new Error('launch must be first-write-wins');
}

const projection = await hum.waitForAudit(prepared.run_id, { intervalMs: 2_000 });
console.log(`sections      report=${projection.report ? 'set' : 'null'} read=${projection.read ? 'set' : 'null'} verdicts=${projection.verdicts?.length ?? 'null'} replies=${projection.replies.length}`);

const transcriptLength = projection.transcript.messages.length;
for (const verdict of projection.verdicts ?? []) {
  if (verdict.index < 0 || verdict.index >= transcriptLength) {
    throw new Error(`verdict index ${verdict.index} is not a transcript position`);
  }
  const turn = projection.transcript.messages[verdict.index];
  if (turn.speaker !== projection.agent_name) {
    throw new Error('verdict indexes must point at the selected agent\'s turns');
  }
  console.log(`  verdict ${verdict.index}  risk=${verdict.risk}  ${JSON.stringify(verdict.summary)}`);
}
for (const reply of projection.replies) {
  if (reply.messages.length < 1 || reply.messages.length > 3) {
    throw new Error('a rewritten reply is split into 1-3 bubbles');
  }
  console.log(`  reply   ${reply.index}  risk=${reply.risk}  bubbles=${reply.messages.length}`);
}

// Re-polling a completed run is free: zero calls and zero credits.
const usageBefore = await hum.usageSummary();
await hum.auditRun({ run_id: prepared.run_id });
const usageAfter = await hum.usageSummary();
const delta = usageAfter.total_credits - usageBefore.total_credits;
console.log(`terminal poll charged ${delta} credits (must be 0)`);
if (delta !== 0) throw new Error('terminal polling must be free');

console.log('08-audit-lifecycle OK');
