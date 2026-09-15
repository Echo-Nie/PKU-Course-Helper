import { test } from "node:test";
import assert from "node:assert/strict";
import * as state from "./state.js";
test('elective is display metadata and shares the major route and duplicate check', () => {
  const major = {id:'a',name:'数学',school:'数院',identity:'bzx',page:1,class_no:0};
  const c = { courses:[major], course_categories:{a:'elective'}, delays:[],mutexes:[] };
  assert.equal(state.courseCategory(c,major),'elective');
  assert.equal(state.courseGroupKey(major),'bzx:1');
  assert.equal(state.courseCategory(c,{...major,identity:'bfx'}),'minor');
  assert.match(state.courseIssue(c,{...major,id:'b'}),/已存在/);
  assert.deepEqual(state.removeCourse(c,'a').course_categories,{});
});
test('status labels distinguish authentication, course matching and identity entry', () => {
  assert.equal(state.courseStatusLabel('failed','账号或密码不正确'),'账号或密码错误');
  assert.equal(state.courseStatusLabel('failed','密码不正确'),'密码错误');
  assert.equal(state.courseStatusLabel('failed','账号不存在'),'账号错误');
  assert.equal(state.courseStatusLabel('unmatched','',{category:'elective'}),'选修未找到课程');
  assert.equal(state.courseStatusLabel('unmatched','',{identity:'bfx'}),'辅修未找到课程');
  assert.equal(state.courseStatusLabel('identity_unavailable','',{identity:'bfx'}),'辅修入口不可用');
});
test('sleep notice never claims protection without worker confirmation or after stop', () => {
  assert.match(state.sleepProtectionNotice('running', {active:true}).text, /已启用/);
  assert.match(state.sleepProtectionNotice('running').text, /尚未确认/);
  assert.equal(state.sleepProtectionNotice('running', {active:false,error:'denied'}).warning, true);
  assert.equal(state.sleepProtectionNotice('running', {supported:false}).warning, true);
  assert.equal(state.sleepProtectionNotice('stopped', {active:true}), null);
  assert.equal(state.sleepProtectionNotice('failed', {active:true}), null);
});
test('lid protection needs both verified plan and live execution request', () => {
  assert.equal(state.sleepProtectionNotice('running', {active:true}).warning, true);
  assert.equal(state.sleepProtectionNotice('running', {active:true,lid_protected:true}).warning, false);
  assert.equal(state.sleepProtectionNotice('running', {active:true,lid_protected:true,plan_error:'策略已变更'}).warning, true);
  assert.match(state.sleepProtectionNotice('running', {lid_protected:true}).text, /尚未确认/);
});
test("overview counts current course problems instead of adding historical request errors", () => {
  const rows = ['elected', 'waiting', 'unmatched', 'unconfirmed', 'failed', 'identity_unavailable', 'retrying', 'ignored']
    .map(status => ({ status }));
  assert.deepEqual(state.courseStatusCounts(rows), {selected: 1, waiting: 1, abnormal: 5});
  rows[6].status = 'waiting';
  assert.equal(state.courseStatusCounts(rows).abnormal, 4);
  assert.deepEqual(state.courseStatusCounts(), {selected: 0, waiting: 0, abnormal: 0});
});
test("incremental logs retain object identity on idle polls and cap history", () => {
  const old = { generation: 3, logs: Array.from({length: 2000}, (_, i) => `log ${i}`) };
  const idle = state.mergeRuntime(old, {generation:3,log_cursor:2000,logs:[]});
  assert.equal(idle.logs, old.logs);
  const updated = state.mergeRuntime(idle, {generation:3,log_cursor:2001,logs:['new']});
  assert.equal(updated.logs.length, 2000);
  assert.equal(updated.logs.at(-1), 'new');
  const reset = state.mergeRuntime(updated, {generation:4,log_cursor:2002,logs_reset:true,logs:['fresh']});
  assert.deepEqual(reset.logs, ['fresh']);
  assert.equal(state.mergeRuntime(reset, {generation:4,logs:['fresh']}).logs, reset.logs);
  assert.equal(state.formatUptime(250 * 3600), '10 天 10:00:00');
  assert.equal(state.courseStates.unmatched[0], '不匹配');
});
import {
  removeCourse,
  moveCourse,
  courseIssue,
  isActive,
  accountKey,
  mergeSavedDraft,
  overviewCourses,
  issueTarget,
  reorderCourse,
} from "./state.js";
const config = {
  courses: [
    { id: "a", name: "数据库", school: "信息科学", class_no: 1 },
    { id: "b", name: "图论", school: "数学", class_no: 2 },
  ],
  mutexes: [{ id: "m", courses: ["a", "b"] }],
  delays: [{ id: "d", course: "a", threshold: 3 }],
};
test("deleting referenced course removes dangling rules", () => {
  const next = removeCourse(config, "a");
  assert.equal(next.courses.length, 1);
  assert.deepEqual(next.mutexes, []);
  assert.deepEqual(next.delays, []);
  assert.equal(config.courses.length, 2);
});
test("priority moves preserve identity and bounds", () => {
  assert.equal(moveCourse(config, "a", 1).courses[0].id, "b");
  assert.equal(moveCourse(config, "a", -1), config);
});
test("class 01 is duplicate class 1", () =>
  assert.ok(
    courseIssue(config, {
      id: "c",
      name: "数据库",
      school: "信息科学",
      class_no: "01",
    }),
  ));
test("class 00 can be added and is the same class as zero", () => {
  const course = { id: "zero", name: "数学", school: "数学学院", class_no: "00" };
  for (const class_no of ["00", "0", 0, "01", 1]) {
    assert.equal(courseIssue(config, { ...course, class_no }), "");
  }
  const saved = { ...course, class_no: 0 };
  assert.match(courseIssue({ courses: [saved] }, { ...course, id: "another" }), /已存在/);
  for (const class_no of ["", " ", null, undefined, -1, "-01", 1.5, "abc"]) {
    assert.notEqual(courseIssue(config, { ...course, class_no }), "");
  }
});
test("stopping remains active until child exit", () => {
  assert.ok(isActive("stopping"));
  assert.ok(!isActive("stopped"));
});
test("saving while editing keeps the newer draft and advances revision", () => {
  const newer = {
    ...config,
    user: { student_id: "123", identity: "bzx", dual_degree: false },
    revision: 1,
    courses: [...config.courses, { id: "new" }],
  };
  const saved = {
    ...newer,
    revision: 2,
    courses: config.courses,
    credential_ref: "cipher",
    remember_password: true,
  };
  const merged = mergeSavedDraft(newer, saved, 2, 3);
  assert.equal(merged.dirty, true);
  assert.equal(merged.config.revision, 2);
  assert.equal(merged.config.courses.length, 3);
});
test("account changes invalidate saved credential references", () => {
  const current = {
    ...config,
    user: { student_id: "new", identity: "bzx" },
    revision: 1,
  };
  const saved = {
    ...current,
    user: { student_id: "old", identity: "bzx" },
    revision: 2,
    credential_ref: "cipher",
    remember_password: true,
  };
  const result = mergeSavedDraft(current, saved, 1, 2);
  assert.equal(result.config.credential_ref, undefined);
  assert.equal(result.config.remember_password, false);
  assert.notEqual(accountKey(current.user), accountKey(saved.user));
});
test("completed overview keeps the run snapshot after draft edits", () => {
  const snapshot = {
    courses: [{ id: "a", name: "original", status: "elected" }],
  };
  assert.equal(
    overviewCourses(config, { state: "completed", snapshot })[0].name,
    "original",
  );
  assert.equal(
    overviewCourses(config, { state: "idle", snapshot: { courses: [] } }),
    config.courses,
  );
});
test("course and rule issues locate visible editors or their list", () => {
  assert.deepEqual(issueTarget("courses.0.name", config), {
    page: "courses",
    kind: "course",
    index: 0,
    focus: "edit-name",
  });
  assert.deepEqual(issueTarget("delays.0.threshold", config), {
    page: "courses",
    kind: "course",
    index: 0,
    focus: "edit-threshold",
  });
  assert.deepEqual(issueTarget("mutexes.0.courses", config), {
    page: "courses",
    kind: "mutex",
    index: 0,
    focus: "mutex-list",
  });
});
test("stale drag id cannot reorder or remove another course", () => {
  assert.equal(reorderCourse(config, "missing", "a"), config);
  assert.deepEqual(
    reorderCourse(config, "b", "a").courses.map((c) => c.id),
    ["b", "a"],
  );
});

test("global jitter defaults mean 4.8–7.2 seconds and shorter settings warn", () => {
  assert.equal(typeof state.frequencyRisk, "function");
  assert.deepEqual(
    state.frequencyRisk({ refresh_interval: 6, random_deviation: 0.2 }),
    { level: "none", minimum: 6 * 0.8, maximum: 6 * 1.2, message: "" },
  );
  assert.equal(
    state.frequencyRisk({ refresh_interval: 5, random_deviation: 0.4 }).level,
    "warning",
  );
  assert.equal(
    state.frequencyRisk({ refresh_interval: 6, random_deviation: 0.6 }).level,
    "blocked",
  );
  assert.equal(
    state.frequencyRisk({ refresh_interval: "", random_deviation: 0.5 }).level,
    "blocked",
  );
});

test("group priorities and drag reorder never cross identity/page boundaries", () => {
  const mixed = { courses: [
    { id: "a", identity: "bzx", page: 1 },
    { id: "minor", identity: "bfx", page: 1 },
    { id: "b", identity: "bzx", page: 1 },
    { id: "page2", identity: "bzx", page: 2 },
    { id: "c", identity: "bzx", page: 1 },
  ] };
  assert.deepEqual(moveCourse(mixed, "a", 1).courses.map((c) => c.id), ["b", "minor", "a", "page2", "c"]);
  assert.equal(moveCourse(mixed, "minor", 1), mixed);
  assert.equal(moveCourse(mixed, "a", -1), mixed);
  assert.equal(reorderCourse(mixed, "a", "minor"), mixed);
  assert.equal(reorderCourse(mixed, "a", "page2"), mixed);
  assert.deepEqual(reorderCourse(mixed, "a", "c").courses.map((c) => c.id), ["b", "minor", "c", "page2", "a"]);
  const groups = state.courseGroups(mixed.courses);
  assert.deepEqual(groups.map((g) => g.key), ["bzx:1", "bzx:2", "bfx:1"]);
  assert.deepEqual(groups[0].courses.map((c) => c.id), ["a", "b", "c"]);
  const filtered = state.courseGroups([mixed.courses[2]], mixed.courses);
  assert.equal(filtered[0].allCourses.findIndex((c) => c.id === "b"), 1);
});

test("changing identity or page appends to destination group without disturbing other priorities", () => {
  const mixed = { courses: [
    { id: "a", identity: "bzx", page: 1 },
    { id: "b", identity: "bfx", page: 2 },
    { id: "c", identity: "bfx", page: 2 },
  ] };
  const moved = state.upsertCourse(mixed, { ...mixed.courses[0], identity: "bfx", page: 2 });
  assert.deepEqual(state.courseGroups(moved.courses)[0].courses.map((c) => c.id), ["b", "c", "a"]);
  assert.deepEqual(state.upsertCourse(mixed, { ...mixed.courses[1], name: "edited" }).courses.map((c) => c.id), ["a", "b", "c"]);
});

test("same name is permitted in different identities but not duplicate pages", () => {
  const first = { id: "one", name: "数学", school: "数院", class_no: 1, page: 1, identity: "bzx" };
  assert.equal(state.courseIssue({ courses: [first] }, { ...first, id: "two", identity: "bfx" }), "");
  assert.notEqual(state.courseIssue({ courses: [first] }, { ...first, id: "two", page: 2 }), "");
  assert.equal(state.issueTarget("courses.0.identity", { courses: [first] }).focus, "edit-identity");
});
test("course pages are positive integers and error focus follows page field", () => {
  const course = {
    id: "new",
    name: "new",
    school: "数学",
    class_no: 1,
    page: 0,
  };
  assert.match(courseIssue(config, course), /页码/);
  assert.equal(courseIssue(config, { ...course, page: 2 }), "");
  assert.match(courseIssue(config, { ...course, page: 1.5 }), /页码/);
  assert.equal(issueTarget("courses.0.page", config).focus, "edit-page");
});

test("risk warning never recommends speeding up a slower schedule", () => {
  assert.equal(
    state.frequencyRisk({ refresh_interval: 60, random_deviation: 0.6 }).level,
    "none",
  );
  assert.equal(
    state.frequencyRisk({ refresh_interval: 6, random_deviation: "" }).field,
    "client.random_deviation",
  );
  assert.equal(
    state.frequencyRisk({ refresh_interval: "", random_deviation: 0.5 }).field,
    "client.refresh_interval",
  );
});

test("course ids work in inline about:blank without secure-context randomUUID", () => {
  assert.equal(typeof state.createId,"function");
  const source={getRandomValues: bytes=>bytes.fill(0xab)};
  assert.equal(state.createId(source),"ab".repeat(16));
});
