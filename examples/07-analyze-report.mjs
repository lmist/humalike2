#!/usr/bin/env node
/**
 * Phase 6 — Social Observability: a synchronous report with no identifier.
 *
 * `analyze` returns the report itself and nothing else: no `id` key, no
 * `Location`, no `x-report-id`. That is a tested production behavior, not an
 * oversight to work around (spec/08 open question 1), so this example checks
 * the absence and then shows the aggregate invariants: all six interaction
 * types present with zero counts included, per-user distributions consistent
 * with `interactions`, and every evidence id originating in the input.
 *
 *   HUMALIKE_API_URL=http://127.0.0.1:8191 HUMALIKE_API_KEY=ak_... \
 *     node examples/07-analyze-report.mjs
 */

import { randomUUID } from 'node:crypto';
import { HumalikeClient, HumalikeApiError } from '../clients/typescript/client.mjs';

const INTERACTION_TYPES = [
  'transactional', 'bonding', 'venting', 'banter', 'friction', 'hostile',
];

const hum = new HumalikeClient();

const transcript = {
  source: 'example-07',
  messages: [
    { id: 'm1', speaker: 'Lin', text: 'This is the third time the export has failed.', user_id: 'u-lin' },
    { id: 'm2', speaker: 'Grace', text: 'Please try again with a smaller range.', user_id: 'u-grace' },
    { id: 'm3', speaker: 'Lin', text: 'I already did that twice.', user_id: 'u-lin' },
    { id: 'm4', speaker: 'Grace', text: 'Escalating it now — sorry for the runaround.', user_id: 'u-grace' },
    { id: 'm5', speaker: 'Lin', text: 'Thanks, that helps.', user_id: 'u-lin' },
  ],
};
const inputIds = new Set(transcript.messages.map((m) => m.id));

const report = await hum.analyze({ agent_name: 'Grace', transcript, focus: 'frustration' });
console.log(`analyze       x-request-id=${hum.lastRequestId}`);

if ('id' in report) throw new Error('analyze must not expose a report id');
console.log(`report keys   ${Object.keys(report).join(', ')}`);
console.log(`health_score  ${report.health_score}`);
console.log(`summary       ${JSON.stringify(report.summary)}`);

if (report.interaction_totals.length !== 6) {
  throw new Error('interaction_totals must list exactly the six types, zero counts included');
}
const totals = Object.fromEntries(report.interaction_totals.map((t) => [t.type, t.count]));
for (const type of INTERACTION_TYPES) {
  if (!(type in totals)) throw new Error(`interaction_totals is missing ${type}`);
}
const observed = report.interactions.reduce((acc, i) => ({ ...acc, [i.type]: (acc[i.type] ?? 0) + 1 }), {});
for (const type of INTERACTION_TYPES) {
  if ((observed[type] ?? 0) !== totals[type]) {
    throw new Error(`interaction_totals[${type}] disagrees with interactions`);
  }
}
console.log(`totals        ${report.interaction_totals.map((t) => `${t.type}:${t.count}`).join(' ')}`);

for (const interaction of report.interactions) {
  for (const id of interaction.message_ids) {
    if (!inputIds.has(id)) throw new Error(`evidence id ${id} did not originate in the input`);
  }
  console.log(`  ${interaction.type.padEnd(13)} ${JSON.stringify(interaction.topic)} ids=${interaction.message_ids.join(',')}`);
}

for (const user of report.per_user) {
  const participates = report.interactions.filter(
    (i) => i.participants.some((p) => p.name === user.name)).length;
  if (user.interaction_count !== participates) {
    throw new Error(`${user.name}: interaction_count ${user.interaction_count} != ${participates}`);
  }
  if (user.distribution.length !== 6) throw new Error('per_user distribution must list all six types');
  if (user.frustration < 0 || user.frustration > 1) throw new Error('frustration must lie in [0,1]');
  console.log(`  ${user.name.padEnd(8)} reception=${user.reception} frustration=${user.frustration} trend=${user.trend} user_id=${user.user_id ?? 'null'}`);
}

for (const finding of report.findings) {
  console.log(`  finding     [${finding.severity}] ${JSON.stringify(finding.issue)} component=${finding.suggested_component ?? '-'}`);
  for (const id of finding.evidence) {
    if (!inputIds.has(id)) throw new Error(`finding evidence ${id} did not originate in the input`);
  }
}

// A valid but unknown report id is a 200 with JSON null; only a malformed id
// is a 400 with exactly {error:{code:"VALIDATION_ERROR",message:"invalid id"}}.
const missing = await hum.reportById(randomUUID());
console.log(`Report/by-id  unknown uuid -> ${JSON.stringify(missing)}`);
if (missing !== null) throw new Error('an unknown report id must return JSON null');

try {
  await hum.reportById('not-a-uuid');
  throw new Error('a malformed report id must return 400');
} catch (error) {
  if (!(error instanceof HumalikeApiError) || error.status !== 400) throw error;
  if ('details' in error.body.error) throw new Error('the invalid-id body carries no details key');
  console.log(`Report/by-id  malformed -> ${error.status} ${JSON.stringify(error.body)}`);
}

console.log('07-analyze-report OK');
