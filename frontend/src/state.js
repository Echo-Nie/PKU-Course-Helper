export const courseStates = {
  unknown: ["尚未查询", "neutral"],
  waiting: ["等待名额", "amber"],
  pending: ["待处理", "neutral"],
  elected: ["已选中", "green"],
  ignored: ["已跳过", "neutral"],
  skipped: ["已跳过", "neutral"],
  unconfirmed: ["待核对", "amber"],
  failed: ["未完成", "red"],
  unmatched: ["不匹配", "red"],
  identity_unavailable: ["选课入口不可用", "red"],
  retrying: ["重试中", "amber"],
  waitlisted: ["候补", "amber"],
};
export const runStates = {
  idle: "未运行",
  starting: "正在准备",
  running: "运行中",
  stopping: "正在停止",
  stopped: "已停止",
  completed: "本次已结束",
  failed: "运行失败",
};
export const isActive = (state) =>
  ["starting", "running", "stopping"].includes(state);
export function sleepProtectionNotice(state, power) {
  if (!isActive(state)) return null;
  if (power?.error || power?.plan_error || power?.supported === false)
    return {
      warning: true,
      text:
        power?.plan_error ||
        power?.error ||
        "持续运行保护不可用，请保持开盖和电脑唤醒",
    };
  if (power?.active && power?.lid_protected)
    return {
      warning: false,
      text: "合盖持续运行保护已启用 · 接电 / 电池 · 无需操作鼠标键盘",
    };
  if (power?.active)
    return {
      warning: true,
      text: "防自动睡眠已启用，合盖保护尚未确认，请保持开盖",
    };
  return { warning: false, text: "持续运行保护状态尚未确认，请暂时保持开盖" };
}
export function courseStatusCounts(courses = []) {
  const counts = { selected: 0, waiting: 0, abnormal: 0 };
  for (const course of courses) {
    if (course.status === "elected") counts.selected++;
    if (course.status === "waiting") counts.waiting++;
    if (
      [
        "unmatched",
        "unconfirmed",
        "failed",
        "identity_unavailable",
        "retrying",
      ].includes(course.status)
    )
      counts.abnormal++;
  }
  return counts;
}
export const courseGroupKey = (course) =>
  `${course.identity ?? "bzx"}:${course.page ?? 1}`;
export const categoryLabels = {
  major: "主修",
  elective: "选修",
  minor: "辅修",
};
export const courseCategory = (config, course) =>
  course.identity === "bfx"
    ? "minor"
    : config.course_categories?.[course.id] === "elective"
      ? "elective"
      : "major";
export const courseGroupLabel = (course) =>
  `${course.identity === "bfx" ? "辅修" : "主修 / 选修"} · 第 ${course.page ?? 1} 页`;
export function courseStatusLabel(status, reason = "", course = {}) {
  const category =
    categoryLabels[course.category] ||
    (course.identity === "bfx" ? "辅修" : "主修 / 选修");
  if (status === "unmatched") return `${category}未找到课程`;
  if (status === "identity_unavailable")
    return `${course.identity === "bfx" ? "辅修" : "主修"}入口不可用`;
  if (status === "failed") {
    if (/账号或密码/.test(reason)) return "账号或密码错误";
    if (/账号不存在|学号不存在/.test(reason)) return "账号错误";
    if (/密码不正确|密码错误/.test(reason)) return "密码错误";
    if (/登录暂时受限/.test(reason)) return "登录受限";
    if (/限制访问|限制本次访问/.test(reason)) return "访问受限";
    if (/选课协议/.test(reason)) return "需同意选课协议";
  }
  return (courseStates[status] || courseStates.unknown)[0];
}
export function courseGroups(courses, allCourses = courses) {
  const groups = new Map();
  const members = new Map();
  for (const c of allCourses) {
    const key = courseGroupKey(c);
    if (!members.has(key)) members.set(key, []);
    members.get(key).push(c);
  }
  for (const course of courses) {
    const key = courseGroupKey(course);
    if (!groups.has(key)) {
      const identity = course.identity ?? "bzx",
        page = course.page ?? 1;
      groups.set(key, {
        key,
        identity,
        page,
        label: courseGroupLabel(course),
        courses: [],
        allCourses: members.get(key) || [],
      });
    }
    groups.get(key).courses.push(course);
  }
  return [...groups.values()].sort(
    (a, b) =>
      Number(a.identity === "bfx") - Number(b.identity === "bfx") ||
      a.page - b.page,
  );
}
export function upsertCourse(config, course) {
  const old = config.courses.find((c) => c.id === course.id);
  const courses =
    !old || courseGroupKey(old) !== courseGroupKey(course)
      ? [...config.courses.filter((c) => c.id !== course.id), course]
      : config.courses.map((c) => (c.id === course.id ? course : c));
  return { ...config, courses };
}
export function removeCourse(config, id) {
  return {
    ...config,
    courses: config.courses.filter((c) => c.id !== id),
    course_categories: Object.fromEntries(
      Object.entries(config.course_categories || {}).filter(
        ([key]) => key !== id,
      ),
    ),
    delays: config.delays.filter((d) => d.course !== id),
    mutexes: config.mutexes
      .map((m) => ({ ...m, courses: m.courses.filter((c) => c !== id) }))
      .filter((m) => m.courses.length > 1),
  };
}
export function moveCourse(config, id, offset) {
  const courses = [...config.courses],
    from = courses.findIndex((c) => c.id === id);
  if (from < 0 || !Number.isInteger(offset)) return config;
  const group = courses
    .map((c, i) =>
      courseGroupKey(c) === courseGroupKey(courses[from]) ? i : -1,
    )
    .filter((i) => i >= 0);
  const target = group.indexOf(from) + offset;
  if (target < 0 || target >= group.length || offset === 0) return config;
  const to = group[target];
  [courses[from], courses[to]] = [courses[to], courses[from]];
  return { ...config, courses };
}
export function courseIssue(config, course) {
  if (!["bzx", "bfx"].includes(course.identity ?? "bzx"))
    return "请选择主修或辅修身份";
  if (!course.name.trim()) return "请填写课程名称";
  if (!course.school.trim()) return "请填写开课单位";
  if (String(course.class_no ?? "").trim() === "") return "请填写班号";
  if (!Number.isInteger(Number(course.class_no)) || Number(course.class_no) < 0)
    return "班号须为非负整数（允许 00）";
  const page = Number(course.page ?? 1);
  if (!Number.isInteger(page) || page < 1 || page > 999)
    return "页码须为 1 至 999 的整数";
  if (
    config.courses.some(
      (c) =>
        c.id !== course.id &&
        (c.identity ?? "bzx") === (course.identity ?? "bzx") &&
        c.name.trim() === course.name.trim() &&
        c.school.trim() === course.school.trim() &&
        Number(c.class_no) === Number(course.class_no),
    )
  )
    return "同一身份下的相同课程和班号已存在";
  return "";
}

// NavigateToString/about:blank is not a secure context. getRandomValues is
// available there, whereas randomUUID is not. IDs are opaque 128-bit values.
export function createId(source = globalThis.crypto) {
  return Array.from(source.getRandomValues(new Uint8Array(16)), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

export const accountKey = (user) =>
  JSON.stringify([String(user?.student_id ?? "").trim()]);

export function mergeSavedDraft(
  current,
  saved,
  submittedGeneration,
  currentGeneration,
) {
  if (submittedGeneration === currentGeneration)
    return { config: saved, dirty: false };
  const config = { ...current, revision: saved.revision };
  if (accountKey(current.user) === accountKey(saved.user)) {
    config.credential_ref = saved.credential_ref;
    config.remember_password = saved.remember_password;
  } else {
    delete config.credential_ref;
    config.remember_password = false;
  }
  return { config, dirty: true };
}

export function overviewCourses(config, runtime) {
  return runtime.snapshot?.courses?.length
    ? runtime.snapshot.courses
    : config.courses;
}

export function mergeRuntime(previous, incoming) {
  // Older running native windows still send full snapshots. Negotiate cursor
  // support at bootstrap, and accept either protocol while the app is updated.
  let logs;
  if (Number.isInteger(incoming.log_cursor)) {
    logs =
      incoming.logs_reset || previous.generation !== incoming.generation
        ? (incoming.logs || []).slice(-2000)
        : incoming.logs?.length
          ? [...(previous.logs || []), ...incoming.logs].slice(-2000)
          : previous.logs || [];
  } else {
    const next = (incoming.logs || []).slice(-2000),
      old = previous.logs || [];
    logs =
      next.length === old.length && next.every((line, i) => line === old[i])
        ? old
        : next;
  }
  return { ...incoming, logs };
}

export function formatUptime(seconds = 0) {
  const value = Math.max(0, Math.floor(seconds));
  return `${Math.floor(value / 86400)} 天 ${String(Math.floor(value / 3600) % 24).padStart(2, "0")}:${String(Math.floor(value / 60) % 60).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

export function issueTarget(path, config) {
  if (path.startsWith("user.") || path.startsWith("client."))
    return { page: "settings", focus: path };
  const [kind, rawIndex, field] = path.split("."),
    index = Number(rawIndex);
  if (kind === "courses" && config.courses[index])
    return {
      page: "courses",
      kind: "course",
      index,
      focus:
        {
          name: "edit-name",
          school: "edit-school",
          class_no: "edit-class",
          page: "edit-page",
          identity: "edit-identity",
        }[field] || "edit-name",
    };
  if (kind === "delays" && config.delays[index]) {
    const courseIndex = config.courses.findIndex(
      (c) => c.id === config.delays[index].course,
    );
    if (courseIndex >= 0)
      return {
        page: "courses",
        kind: "course",
        index: courseIndex,
        focus: "edit-threshold",
      };
  }
  if (kind === "mutexes" && config.mutexes[index])
    return { page: "courses", kind: "mutex", index, focus: "mutex-list" };
  return { page: "courses", focus: "course-errors" };
}

export function frequencyRisk(client) {
  const interval = client.refresh_interval,
    deviation = client.random_deviation;
  if (
    typeof interval !== "number" ||
    typeof deviation !== "number" ||
    !Number.isFinite(interval) ||
    !Number.isFinite(deviation) ||
    interval <= 0 ||
    deviation < 0 ||
    deviation > 0.9
  )
    return {
      level: "blocked",
      field:
        typeof interval !== "number" ||
        !Number.isFinite(interval) ||
        interval <= 0
          ? "client.refresh_interval"
          : "client.random_deviation",
      minimum: null,
      maximum: null,
      message: "请输入有效间隔与 0～0.9 的波动系数",
    };
  const minimum = interval * (1 - deviation),
    maximum = interval * (1 + deviation);
  if (minimum < 3)
    return {
      level: "blocked",
      field: "client.refresh_interval",
      minimum,
      maximum,
      message:
        "请求过于频繁，可能触发限流或账号限制；请将波动后的最短间隔调至至少 3 秒",
    };
  if (interval < 6)
    return {
      level: "warning",
      minimum,
      maximum,
      message:
        "当前节奏比默认更激进，可能增加限流或账号限制风险，建议恢复 6 秒 / 0.2",
    };
  return { level: "none", minimum, maximum, message: "" };
}

export function reorderCourse(config, fromId, toId) {
  const from = config.courses.findIndex((c) => c.id === fromId),
    to = config.courses.findIndex((c) => c.id === toId);
  if (from < 0 || to < 0 || from === to) return config;
  const key = courseGroupKey(config.courses[from]);
  if (key !== courseGroupKey(config.courses[to])) return config;
  const group = config.courses.filter((c) => courseGroupKey(c) === key);
  const fromLocal = group.findIndex((c) => c.id === fromId),
    toLocal = group.findIndex((c) => c.id === toId);
  const [course] = group.splice(fromLocal, 1);
  group.splice(toLocal, 0, course);
  let index = 0;
  const courses = config.courses.map((c) =>
    courseGroupKey(c) === key ? group[index++] : c,
  );
  return { ...config, courses };
}
