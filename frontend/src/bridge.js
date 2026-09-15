const preview =
  import.meta.env.DEV &&
  new URLSearchParams(location.search).get("preview") === "1";
let mock;
let mockLogs = [];
let bridgeReadyPromise = null;

function waitForBridgeMethod(method) {
  if (typeof window.pywebview?.api?.[method] === "function") {
    return Promise.resolve();
  }
  if (bridgeReadyPromise) return bridgeReadyPromise;

  bridgeReadyPromise = new Promise((resolve, reject) => {
    let settled = false;
    let poll;
    let timeout;
    const cleanup = () => {
      window.removeEventListener("pywebviewready", check);
      clearInterval(poll);
      clearTimeout(timeout);
    };
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      cleanup();
      callback(value);
    };
    const check = () => {
      if (typeof window.pywebview?.api?.[method] === "function") {
        finish(resolve);
      }
    };

    window.addEventListener("pywebviewready", check);
    poll = setInterval(check, 50);
    timeout = setTimeout(
      () => finish(reject, new Error("请从桌面程序打开工作台")),
      10000,
    );
    check();
  }).finally(() => {
    bridgeReadyPromise = null;
  });

  return bridgeReadyPromise;
}

const fields = [
  [
    "supply_cancel_page",
    "选课计划页码",
    "目标课程位于补退选计划的第几页，从 1 开始。",
    1,
    "int",
    "basic",
    1,
    999,
  ],
  [
    "refresh_interval",
    "全局查询间隔",
    "所有页面共享的查询节奏。波动后的最短等待不得少于 3 秒；任何间隔都不能保证不被限流或限制账号。",
    6,
    "float",
    "strategy",
    3,
    3600,
  ],
  [
    "random_deviation",
    "随机偏移",
    "等待时间在间隔 ×（1 ± 偏移）内随机变化，0 表示固定间隔。",
    0.2,
    "float",
    "strategy",
    0,
    0.9,
  ],
  [
    "iaaa_client_timeout",
    "登录请求超时",
    "等待统一认证响应的最长秒数。",
    30,
    "float",
    "advanced",
    1,
    600,
  ],
  [
    "elective_client_timeout",
    "选课请求超时",
    "等待选课服务响应的最长秒数。",
    60,
    "float",
    "advanced",
    1,
    600,
  ],
  [
    "elective_client_pool_size",
    "全局会话上限",
    "主修、辅修和所有页面自动复用全部会话，默认 4、最多 5。",
    4,
    "int",
    "advanced",
    1,
    5,
  ],
  [
    "page_pool_size",
    "每页会话额度",
    "每页从全局池分配的会话额度，默认 1，不超过全局上限。页面较多时共享已有会话，不额外建立连接。",
    1,
    "int",
    "compatibility",
    1,
    5,
  ],
  [
    "elective_client_max_life",
    "会话有效期",
    "会话刷新的最长秒数，-1 为不限。",
    600,
    "int",
    "advanced",
    -1,
    86400,
  ],
  [
    "login_loop_interval",
    "登录重试间隔",
    "登录线程每轮结束后的等待秒数。",
    2,
    "float",
    "advanced",
    0.1,
    600,
  ],
].map(([key, label, help, defaultValue, type, level, min, max]) => ({
  key,
  label,
  help,
  default: defaultValue,
  type,
  level,
  min,
  max,
}));
function previewConfig() {
  return {
    schema_version: 1,
    revision: 0,
    user: { student_id: "" },
    client: Object.fromEntries(fields.map((f) => [f.key, f.default])),
    monitor: { host: "127.0.0.1", port: 7074 },
    course_categories: { art: "elective" },
    courses: [
      { id: "db", name: "数据库概论", class_no: 1, school: "信息科学技术学院" },
      {
        id: "graph",
        identity: "bfx",
        page: 2,
        name: "集合论与图论",
        class_no: 3,
        school: "信息科学技术学院",
      },
      {
        id: "prob",
        name: "概率统计（A）",
        class_no: 1,
        school: "数学科学学院",
      },
      {
        id: "art",
        name: "艺术史导论",
        class_no: 2,
        school: "艺术学院",
        page: 2,
      },
    ],
    mutexes: [],
    delays: [],
  };
}
export async function call(method, ...args) {
  if (preview) {
    mock ??= previewConfig();
    if (method === "bootstrap")
      return {
        ok: true,
        config: mock,
        fields: fields.filter(
          (f) => f.key !== "supply_cancel_page" && f.level !== "compatibility",
        ),
        remembered: false,
        preview: true,
      };
    if (method === "poll")
      return {
        ok: true,
        state:
          new URLSearchParams(location.search).get("scenario") === "errors"
            ? "failed"
            : "idle",
        snapshot: {
          courses:
            new URLSearchParams(location.search).get("scenario") === "errors"
              ? mock.courses.map((c, i) => ({
                  ...c,
                  status: [
                    "failed",
                    "identity_unavailable",
                    "unmatched",
                    "waiting",
                  ][i % 4],
                  reason: [
                    "密码不正确，请重新输入统一认证密码后开始。",
                    "未识别到辅修选课入口。若该课属于普通选修，请修改课程类别；若网页可进入辅修，请检查入口识别兼容性。",
                    "主修 / 选修入口第 1 页未找到匹配课程。请核对课程全名、班号、开课单位和所在页码。",
                    "等待名额",
                  ][i % 4],
                  remaining: i === 3 ? 0 : null,
                }))
              : [],
        },
        logs: mockLogs,
      };
    if (method === "save") {
      mock = { ...structuredClone(args[0]), revision: mock.revision + 1 };
      return { ok: true, config: mock };
    }
    if (method === "set_dirty") return { ok: true };
    if (method === "open_external_link") {
      window.open(args[0], "_blank", "noopener,noreferrer");
      return { ok: true };
    }
    return { ok: false, error: "界面预览不会执行选课或操作本地文件" };
  }
  await waitForBridgeMethod(method);
  if (!window.pywebview?.api?.[method]) throw new Error("桌面连接尚未就绪");
  return window.pywebview.api[method](...args);
}
