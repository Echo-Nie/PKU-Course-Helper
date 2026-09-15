import test from "node:test";
import assert from "node:assert/strict";
import { runtimeChanges, restartBlockReason, restartWorkflow } from "./workflow.js";

const config = () => ({ user: { student_id: "offline" }, client: {
  refresh_interval: 6, random_deviation: 0.2, elective_client_pool_size: 4,
}, courses: [
  { id: "a", name: "课程 A", school: "院", class_no: 1, identity: "bzx", page: 1 },
  { id: "b", name: "课程 B", school: "院", class_no: 1, identity: "bzx", page: 1 },
  { id: "c", name: "课程 C", school: "院", class_no: 1, identity: "bfx", page: 2 },
], mutexes: [{ id: "m", courses: ["a", "b"] }], delays: [] });
const state = (name, extras = {}) => ({ ok: true, state: name, generation: 3,
  snapshot: { courses: [] }, logs: [], ...extras });
function bridge(states, overrides = {}) {
  const calls = [];
  return { calls, call: async (method, ...args) => {
    calls.push([method, ...args]);
    if (overrides[method]) return overrides[method](...args);
    return method === "poll" ? states.shift() : { ok: true, config: args[0] };
  } };
}
const options = { generation: 3, sleep: async () => {} };

test("restart detection includes actual execution fields but ignores metadata and cross-group ordering", () => {
  const before = config(), after = structuredClone(before);
  after.revision = 99;
  after.monitor = { port: 9090 };
  after.client.page_pool_size = 5;
  after.mutexes[0].id = "new-label-id";
  after.mutexes[0].courses.reverse();
  after.courses = [after.courses[2], after.courses[0], after.courses[1]];
  assert.deepEqual(runtimeChanges(before, after), []);
  after.client.refresh_interval = 7;
  after.client.elective_client_pool_size = 3;
  after.courses[1].page = 4;
  after.delays.push({ course: "a", threshold: 2 });
  assert.equal(runtimeChanges(before, after, true).length, 5);
});
test("within-group priority and account changes trigger restart prompt", () => {
  const before = config(), after = config();
  [after.courses[0], after.courses[1]] = [after.courses[1], after.courses[0]];
  assert.equal(runtimeChanges(before, after).length, 1);
  assert.deepEqual(runtimeChanges(before, config()), []);
  after.user.student_id = "different";
  assert.equal(runtimeChanges(before, after).length, 2);
});
test("restart waits for confirmed stop then starts exactly once with the saved configuration", async () => {
  const fake = bridge([state("running"), state("stopping"), state("stopping"), state("stopped")]);
  const saved = config();
  const result = await restartWorkflow(fake.call, saved, options);
  assert.equal(result.ok, true);
  assert.deepEqual(fake.calls.map(([m]) => m), ["poll", "stop", "poll", "poll", "poll", "start"]);
  assert.deepEqual(fake.calls.at(-1).slice(1), [saved, "", false]);
});
test("canceling a pending confirmation has no side effects: only explicit invocation runs workflow", () => {
  const fake = bridge([]);
  runtimeChanges(config(), { ...config(), client: {} });
  assert.deepEqual(fake.calls, []);
});
test("finished, stopping, replaced or uncertain task is never automatically restarted", async () => {
  for (const status of [state("completed"), state("stopping"), state("running", { generation: 4 }),
    state("running", { snapshot: { courses: [{ status: "unconfirmed" }] } })]) {
    const fake = bridge([status]);
    await assert.rejects(restartWorkflow(fake.call, config(), options));
    assert.deepEqual(fake.calls.map(([m]) => m), ["poll"]);
  }
});
test("new-account missing password and incomplete drafts do not stop a working task", async () => {
  for (const [saved, hasPassword] of [[{ ...config(), courses: [] }, true],
    [{ ...config(), user: {} }, true], [config(), false]]) {
    const fake = bridge([state("running")]);
    assert.ok(restartBlockReason(saved, state("running"), hasPassword));
    await assert.rejects(restartWorkflow(fake.call, saved, { ...options, hasPassword }));
    assert.deepEqual(fake.calls.map(([m]) => m), ["poll"]);
  }
});
test("failure to stop, uncertain final writes, forced exit and poll failure never start another task", async () => {
  for (const final of [state("failed"), state("stopped", { logs: ["12:00 引擎已强制停止；请核对"] }),
    state("stopped", { snapshot: { unconfirmed_count: 1 } }), { ok: false },
    state("stopped", { generation: 4 })]) {
    const fake = bridge([state("running"), final]);
    await assert.rejects(restartWorkflow(fake.call, config(), options));
    assert.equal(fake.calls.filter(([m]) => m === "start").length, 0);
  }
  const fake = bridge([state("running")], { stop: () => ({ ok: false }) });
  await assert.rejects(restartWorkflow(fake.call, config(), options));
  assert.equal(fake.calls.at(-1)[0], "stop");
});
test("bounded waiting and hot reload cancellation both prevent late starts", async () => {
  let time = 0;
  const fake = bridge([state("running"), state("stopping"), state("stopping")]);
  await assert.rejects(restartWorkflow(fake.call, config(), { ...options,
    now: () => time, timeoutMs: 5, sleep: async () => { time += 10; } }), /超时/);
  assert.equal(fake.calls.filter(([m]) => m === "start").length, 0);
  const controller = new AbortController();
  const aborting = bridge([state("running"), state("stopping")]);
  await assert.rejects(restartWorkflow(aborting.call, config(), { ...options,
    signal: controller.signal, sleep: async () => controller.abort() }), /已取消/);
  assert.equal(aborting.calls.filter(([m]) => m === "start").length, 0);
});
test("start failure is returned without retrying or hiding committed revision", async () => {
  const failure = { ok: false, committed: true, config: { ...config(), revision: 4 }, error: "模拟启动失败" };
  const fake = bridge([state("running"), state("stopped")], { start: () => failure });
  assert.deepEqual(await restartWorkflow(fake.call, config(), options), failure);
  assert.equal(fake.calls.filter(([m]) => m === "start").length, 1);
});
