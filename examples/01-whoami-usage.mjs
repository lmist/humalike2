#!/usr/bin/env node
/**
 * Phase 1 — identity and usage.
 *
 * Confirms the key resolves to an owner and reads the usage projection, which
 * is the cheapest end-to-end check that authentication, owner injection, and
 * the billing ledger all work. Both routes are free.
 *
 *   HUMALIKE_API_URL=http://127.0.0.1:8191 HUMALIKE_API_KEY=ak_... \
 *     node examples/01-whoami-usage.mjs
 */

import { HumalikeClient } from '../clients/typescript/client.mjs';

const COMPONENTS = [
  'personas', 'social-learning', 'social-memory',
  'social-observability', 'theoryofmind', 'turn-taking',
];

const hum = new HumalikeClient();

const { user_id } = await hum.whoami();
console.log(`whoami        user_id=${user_id} x-request-id=${hum.lastRequestId}`);

const usage = await hum.usageSummary();
console.log(`usage-summary total_calls=${usage.total_calls} total_credits=${usage.total_credits}`);

// Exactly seven entries, oldest first, zero-filled over the last seven UTC days.
if (usage.daily_series.length !== 7) {
  throw new Error(`daily_series has ${usage.daily_series.length} entries, expected 7`);
}
console.log(`daily_series  ${usage.daily_series.map((d) => `${d.date}:${d.requests}`).join(' ')}`);

// Component slugs are fixed; anything else means the billing ledger is
// attributing charges to a component the suites will not recognise.
for (const row of usage.per_component) {
  if (!COMPONENTS.includes(row.component)) {
    throw new Error(`unknown component slug: ${row.component}`);
  }
  console.log(`  ${row.component.padEnd(21)} calls=${row.calls} credits=${row.credits}`);
}

console.log('01-whoami-usage OK');
