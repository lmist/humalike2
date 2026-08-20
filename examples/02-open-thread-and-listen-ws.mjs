#!/usr/bin/env node
/**
 * Phase 2 — thread creation, the 30-second grant, and the WSS frame sequence.
 *
 * Opens a thread, checks the grant shape, attaches a socket, drives one reply,
 * and asserts the exact N+3 sequence: attached, typing true, one message per
 * scheduled entry in position order, typing false — and nothing else.
 *
 * Uses the global `WebSocket` in Node 22+; falls back to the `ws` package from
 * tests/realtime/node_modules when running on an older interpreter.
 *
 *   HUMALIKE_API_URL=http://127.0.0.1:8191 HUMALIKE_API_KEY=ak_... \
 *     node examples/02-open-thread-and-listen-ws.mjs
 */

import { HumalikeClient, grantUrl } from '../clients/typescript/client.mjs';

async function resolveWebSocket() {
  if (typeof WebSocket === 'function') return WebSocket;
  const mod = await import('../tests/realtime/node_modules/ws/index.js');
  return mod.default ?? mod.WebSocket;
}

const hum = new HumalikeClient();
const WS = await resolveWebSocket();

const opened = await hum.openThread({});
const url = grantUrl(opened); // throws unless exactly one token=<payload>.<43-char sig>
const ttlSeconds = (Date.parse(opened.realtime.expires_at) - Date.parse(opened.thread.updated_at)) / 1000;
console.log(`open_thread   thread=${opened.thread.id}`);
console.log(`channel       ${opened.channel}`);
console.log(`grant         host=${url.host} ttl≈${ttlSeconds.toFixed(1)}s`);

if (opened.channel !== `turn-taking-thread/${opened.thread.id}`) {
  throw new Error(`channel must be turn-taking-thread/{id}, got ${opened.channel}`);
}

const frames = [];
const socket = new WS(opened.realtime.connect_url);
const attached = new Promise((resolve, reject) => {
  socket.onerror = (event) => reject(new Error(`socket error: ${event.message ?? event}`));
  socket.onmessage = (event) => {
    const frame = JSON.parse(typeof event.data === 'string' ? event.data : event.data.toString());
    frames.push(frame);
    if (frame.type === 'attached') resolve(frame);
  };
  // An expired or garbage grant completes the upgrade and then closes 4000.
  socket.onclose = (event) => {
    if (event.code === 4000) reject(new Error('grant rejected: close 4000'));
  };
});

const attachedFrame = await attached;
console.log(`attached      channel=${attachedFrame.channel} server_time=${attachedFrame.server_time}`);
if ('data' in attachedFrame || 'id' in attachedFrame) {
  throw new Error('attached must be the distinct three-field frame, not an event envelope');
}

const submitted = await hum.submitMessages({
  thread_id: opened.thread.id,
  messages: [{ sender: 'Ada', content: 'Are we still on for the 3pm sync?' }],
  skip_decide: true,
});
console.log(`submit        decision=${submitted.decision} turn_epoch=${submitted.turn_epoch}`);

const responded = await hum.respond({
  thread_id: opened.thread.id,
  content: 'Yes, 3pm works.\n\nI will send the agenda beforehand.',
  turn_epoch: submitted.turn_epoch,
  metadata: { example: '02' },
});
console.log(`respond       scheduled=${responded.scheduled.length} superseded=${responded.superseded}`);

const lastDeliverAt = Date.parse(responded.scheduled.at(-1).deliver_at);
await new Promise((resolve) => setTimeout(resolve, Math.max(0, lastDeliverAt - Date.now()) + 1_500));
socket.close();

const expected = responded.scheduled.length + 3;
console.log(`frames        ${frames.length} (expected ${expected}: attached + typing + ${responded.scheduled.length} messages + typing)`);
const types = frames.map((f) => f.type);
const wanted = ['attached', 'turn_taking.typing',
  ...responded.scheduled.map(() => 'turn_taking.message'), 'turn_taking.typing'];
if (JSON.stringify(types) !== JSON.stringify(wanted)) {
  throw new Error(`unexpected frame sequence: ${types.join(', ')}`);
}

const messages = frames.filter((f) => f.type === 'turn_taking.message');
messages.forEach((frame, index) => {
  const scheduled = responded.scheduled[index];
  if (frame.data.position !== index) throw new Error('positions must be zero-based and ordered');
  // The delivered message id is generated for delivery and differs from the
  // HTTP schedule id (spec/03 §WebSocket frames).
  if (frame.data.message_id === scheduled.id) throw new Error('WSS message_id must differ from the schedule id');
  if (JSON.stringify(frame.data.metadata) !== JSON.stringify({ example: '02' })) {
    throw new Error('every bubble echoes the full request metadata');
  }
  const lateness = Date.parse(frame.data.sent_at) - Date.parse(scheduled.deliver_at);
  console.log(`  position ${index}  lateness=${lateness}ms  message_id=${frame.data.message_id}`);
});

console.log('02-open-thread-and-listen-ws OK');
