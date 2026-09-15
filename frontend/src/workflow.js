import { accountKey, courseGroups, isActive } from "./state.js";

const strategyKeys = ["refresh_interval", "random_deviation"];
const advancedKeys = ["iaaa_client_timeout", "elective_client_timeout",
  "elective_client_pool_size", "elective_client_max_life", "login_loop_interval"];
const values = (config, keys) => keys.map((key) => config?.client?.[key]);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const courses = (config) => courseGroups(config?.courses || []).map((group) =>
  [group.key, group.courses.map((c) => [c.id, c.name, c.school, c.class_no])]);
const rules = (config) => [
  (config?.mutexes || []).map((r) => [...r.courses].sort()).sort(),
  (config?.delays || []).map((r) => [r.course, r.threshold]).sort(),
];

export function runtimeChanges(previous, next, passwordChanged = false) {
  if (!previous) return [];
  const changed = [];
  if (accountKey(previous.user) !== accountKey(next.user) || passwordChanged) changed.push("账号信息");
  if (!same(values(previous, strategyKeys), values(next, strategyKeys))) changed.push("运行策略");
  if (!same(values(previous, advancedKeys), values(next, advancedKeys))) changed.push("高级设置");
  if (!same(courses(previous), courses(next))) changed.push("课程、身份 / 页码或组内优先级");
  if (!same(rules(previous), rules(next))) changed.push("互斥或延迟规则");
  return changed;
}

export function restartBlockReason(config, status, hasPassword = true) {
  if (!String(config?.user?.student_id || "").trim()) return "请先填写学号，保存后再重启；当前任务保持运行。";
  if (!config?.courses?.length) return "请先添加目标课程，保存后再重启；当前任务保持运行。";
  if (!hasPassword) return "更换账号后请先输入密码，保存后再重启；当前任务保持运行。";
  if (status?.snapshot?.unconfirmed_count || status?.snapshot?.courses?.some((c) => c.status === "unconfirmed"))
    return "有选课结果待核对，未自动重启。请先在学校已选列表核对，再手动停止和开始。";
  return "";
}

/** Only an explicit confirmation calls this. A terminal state is published by
 * the native supervisor after the old process has exited, not on its request. */
export async function restartWorkflow(call, config, {
  generation, signal, onState = () => {}, hasPassword = true,
  timeoutMs = 12000, now = () => Date.now(),
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
} = {}) {
  const deadline = now() + timeoutMs;
  const check = () => {
    if (signal?.aborted) throw new Error("界面已更新，自动重启已取消；请确认运行状态后手动开始。");
    if (now() >= deadline) throw new Error("停止等待超时，未启动新任务。请确认旧任务已停止后再开始。");
  };
  const read = async () => {
    check();
    const status = await call("poll");
    check();
    if (!status.ok) throw new Error(status.error || "无法确认运行状态，未自动重启。");
    onState(status);
    if (status.generation !== generation) throw new Error("运行任务已发生变化，未自动重启；请重新确认。");
    return status;
  };
  let status = await read();
  if (!["starting", "running"].includes(status.state))
    throw new Error("原任务已结束或正在停止，未自动重启；需要继续时请手动开始。");
  const blocked = restartBlockReason(config, status, hasPassword);
  if (blocked) throw new Error(blocked);
  const stopped = await call("stop");
  if (!stopped.ok) throw new Error(stopped.error || "无法停止旧任务，未启动新任务。");
  while (true) {
    status = await read();
    if (!isActive(status.state)) break;
    await sleep(200);
  }
  const uncertain = restartBlockReason(config, status, hasPassword);
  if (uncertain) throw new Error(uncertain);
  if (status.state !== "stopped" || status.logs?.some((line) => line.includes("引擎已强制停止")))
    throw new Error("旧任务未正常停止，未自动重启。请检查运行记录，并在学校已选列表核对结果。");
  check();
  // The password was saved to the native bridge's memory, never persisted in JS storage.
  return call("start", structuredClone(config), "", false);
}
