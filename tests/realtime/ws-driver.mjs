import {paths, post, requireKey} from "./client.mjs";

requireKey();

const threadId = process.env.HUMALIKE_TEST_THREAD_ID;
if (!threadId) throw new Error("HUMALIKE_TEST_THREAD_ID is required");

const events = [];
for (const type of ["typing_start", "typing_stop", "message_edited"]) {
  events.push(await post(paths.event, {
    thread_id: threadId,
    type,
    sender: "Live Test Human",
    client_ts: new Date().toISOString(),
  }));
}

const submitted = await post(paths.submit, {
  thread_id: threadId,
  messages: [{
    sender: "Live Test Human",
    content: "Please acknowledge the realtime transport test.",
  }],
  skip_decide: true,
});

const metadata = {
  test_run: process.env.HUMALIKE_TEST_RUN_ID,
  nested: {round_trip: true},
};
const responded = await post(paths.respond, {
  thread_id: threadId,
  turn_epoch: submitted.data?.turn_epoch,
  content: [
    "[BUBBLE-ONE] Realtime transport is attached and ready.",
    "[BUBBLE-TWO] Metadata must be echoed without modification.",
    "[BUBBLE-THREE] Positions must increase from zero in delivery order.",
    "[BUBBLE-FOUR] Arrival times must follow the scheduled delivery times.",
    "[BUBBLE-FIVE] Scheduled identifiers must be compared with delivered identifiers.",
  ].join("\n\n"),
  agent_name: "Live Test Agent",
  system_prompt: "Preserve all five bracketed labels and send each bracketed paragraph as its own separate chat bubble. Never merge the paragraphs.",
  pacing: {
    reading_delay_ms: 100,
    typing_wpm: 2000,
    max_typing_ms: 400,
  },
  metadata,
});

process.stdout.write(`${JSON.stringify({
  events: events.map(({status, data}) => ({status, data})),
  submitted: {status: submitted.status, data: submitted.data},
  responded: {status: responded.status, data: responded.data},
  metadata,
})}\n`);
