import React, {
  useEffect,
  useLayoutEffect,
  useId,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";
import {
  BookOpen,
  Plus,
  Play,
  Square,
  ArrowUp,
  ArrowDown,
  ArrowRight,
  X,
  HelpCircle,
  ChevronDown,
  Check,
  CheckCheck,
  Circle,
  Activity,
  Trash2,
  Pencil,
  Download,
  Upload,
  Eye,
  EyeOff,
  Layers,
  ShieldCheck,
  Save,
  LoaderCircle,
  Link2,
} from "lucide-react";
import { call } from "./bridge.js";
import LogPanel from "./LogPanel.jsx";
import { CourseStatus } from "./RuntimeDetails.jsx";
import {
  runtimeChanges,
  restartBlockReason,
  restartWorkflow,
} from "./workflow.js";
import {
  courseIssue,
  courseStatusCounts,
  runStates,
  isActive,
  moveCourse,
  courseGroups,
  courseGroupKey,
  courseGroupLabel,
  upsertCourse,
  removeCourse,
  mergeSavedDraft,
  mergeRuntime,
  overviewCourses,
  issueTarget,
  reorderCourse,
  frequencyRisk,
  createId,
  courseCategory,
  categoryLabels,
} from "./state.js";
import "./styles.css";

const uid = createId;
function formatRuntimeDuration(seconds = 0) {
  const value = Math.max(0, Math.floor(seconds));
  const days = Math.floor(value / 86400);
  const hours = Math.floor(value / 3600) % 24;
  const minutes = Math.floor(value / 60) % 60;
  return `${days ? days + " 天 " : ""}${hours} 小时 ${minutes} 分`;
}
function LabelWithHelp({
  children,
  help,
  htmlFor,
  iconOnly = false,
  helpLabel,
}) {
  const [mode, setMode] = useState("closed"),
    [position, setPosition] = useState({}),
    id = useId(),
    ref = useRef(null),
    button = useRef(null),
    popover = useRef(null);
  const open = mode !== "closed",
    helpId = htmlFor ? `${htmlFor}-help` : `${id}-help`;
  const accessibleHelpLabel =
    helpLabel || (typeof children === "string" ? children : "帮助");
  useLayoutEffect(() => {
    if (!open || !help || !button.current) return;
    const reposition = () => {
      const box = button.current.getBoundingClientRect(),
        width = Math.min(310, window.innerWidth - 24),
        height = popover.current?.offsetHeight || 140;
      setPosition({
        position: "fixed",
        inset: "auto",
        margin: 0,
        width,
        maxWidth: "calc(100vw - 24px)",
        maxHeight: "calc(100vh - 24px)",
        overflowY: "auto",
        left: Math.max(12, Math.min(box.left, window.innerWidth - width - 12)),
        top:
          box.bottom + height + 8 < window.innerHeight
            ? box.bottom + 8
            : Math.max(12, box.top - height - 8),
      });
    };
    popover.current?.showPopover?.();
    reposition();
    const outside = (e) => {
      if (!ref.current?.contains(e.target)) setMode("closed");
    };
    const key = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        setMode("closed");
        button.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key, true);
    window.addEventListener("resize", reposition);
    document.addEventListener("scroll", reposition, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key, true);
      window.removeEventListener("resize", reposition);
      document.removeEventListener("scroll", reposition, true);
    };
  }, [open]);
  return (
    <span
      className="label-help"
      ref={ref}
      onMouseEnter={() => setMode((m) => (m === "closed" ? "hover" : m))}
      onMouseLeave={() => setMode((m) => (m === "hover" ? "closed" : m))}
    >
      {htmlFor ? (
        <label className={iconOnly ? "sr-only" : undefined} htmlFor={htmlFor}>
          {children}
        </label>
      ) : (
        <span className={iconOnly ? "sr-only" : undefined}>{children}</span>
      )}
      {help && (
        <>
          <span className="sr-only" id={helpId}>
            {help}
          </span>
          <button
            ref={button}
            type="button"
            className="help-trigger"
            aria-label={`${accessibleHelpLabel}：帮助`}
            aria-describedby={helpId}
            aria-expanded={open}
            aria-controls={`${id}-popover`}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setMode((m) => (m === "pinned" ? "closed" : "pinned"));
            }}
          >
            <HelpCircle size={14} />
          </button>
          {open && (
            <span
              ref={popover}
              popover="manual"
              style={position}
              className="help-popover"
              aria-hidden="true"
              id={`${id}-popover`}
            >
              <strong>{iconOnly ? accessibleHelpLabel : children}</strong>
              <span>{help}</span>
            </span>
          )}
        </>
      )}
    </span>
  );
}
function Field({ label, help, error, children, id }) {
  const associate = (nodes) =>
    React.Children.map(nodes, (child) => {
      if (!React.isValidElement(child)) return child;
      const props =
        child.props.id === id
          ? {
              "aria-describedby":
                [help && `${id}-help`, error && `${id}-error`]
                  .filter(Boolean)
                  .join(" ") || undefined,
              "aria-invalid": !!error,
            }
          : {};
      if (child.props.children)
        props.children = associate(child.props.children);
      return React.cloneElement(child, props);
    });
  return (
    <div className={`field ${error ? "invalid" : ""}`}>
      <LabelWithHelp htmlFor={id} help={help}>
        {label}
      </LabelWithHelp>
      {associate(children)}
      {error && (
        <span id={`${id}-error`} className="field-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
function IconButton({ label, children, ...props }) {
  return (
    <button
      type="button"
      className="icon-button"
      title={label}
      aria-label={label}
      {...props}
    >
      {children}
    </button>
  );
}
function Modal({
  title,
  children,
  onClose,
  onDirty,
  drawer = false,
  className = "",
}) {
  const ref = useRef(),
    titleId = useId();
  useEffect(() => {
    const dialog = ref.current,
      previous = document.activeElement;
    dialog.showModal();
    return () => {
      dialog.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onChangeCapture={onDirty}
      className={`modal ${drawer ? "drawer" : ""} ${className}`.trim()}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      <div className="modal-head">
        <h2 id={titleId}>{title}</h2>
        <IconButton label="关闭" onClick={onClose}>
          <X size={18} />
        </IconButton>
      </div>
      {children}
    </dialog>
  );
}
function Disclosure({
  title,
  help,
  children,
  open: forced,
  collapsible = true,
}) {
  const ref = useRef(null);
  useEffect(() => {
    if (forced && ref.current) ref.current.open = true;
  }, [forced]);
  if (!collapsible) {
    return (
      <section className="disclosure disclosure-static">
        <div className="disclosure-heading" role="heading" aria-level="2">
          <LabelWithHelp help={help}>{title}</LabelWithHelp>
        </div>
        <div className="disclosure-body">{children}</div>
      </section>
    );
  }
  return (
    <details ref={ref} className="disclosure">
      <summary>
        <LabelWithHelp help={help}>{title}</LabelWithHelp>
        <ChevronDown size={16} />
      </summary>
      <div className="disclosure-body">{children}</div>
    </details>
  );
}

function App() {
  const [config, setConfig] = useState(null),
    [fields, setFields] = useState([]),
    [password, setPassword] = useState(""),
    [showPassword, setShowPassword] = useState(false);
  const [dirty, setDirty] = useState(false),
    [notice, setNotice] = useState(""),
    [error, setError] = useState(""),
    [errors, setErrors] = useState({}),
    [busy, setBusy] = useState(false),
    [preview, setPreview] = useState(false),
    [liveDevelopment, setLiveDevelopment] = useState(false),
    [runtimeReady, setRuntimeReady] = useState(false);
  const [runtime, setRuntime] = useState({
    state: "idle",
    snapshot: { courses: [] },
    logs: [],
  });
  const [editor, setEditor] = useState(null),
    [editorError, setEditorError] = useState(""),
    [deleteTarget, setDeleteTarget] = useState(null),
    [mutexEditor, setMutexEditor] = useState(null),
    [infoModal, setInfoModal] = useState(null),
    [confirmClear, setConfirmClear] = useState(false);
  const [ruleError, setRuleError] = useState(""),
    [dragId, setDragId] = useState(null);
  const [importPreview, setImportPreview] = useState(null),
    [pollError, setPollError] = useState(""),
    [editorDirty, setEditorDirty] = useState(false);
  const configRef = useRef(config);
  configRef.current = config;
  // Keep the last committed draft alongside this stable ref through Fast Refresh.
  // No browser storage or extra copy of the password is needed.
  const draftGeneration = useRef(0),
    busyRef = useRef(false),
    runtimeEpoch = useRef(0),
    runtimeMutating = useRef(false);
  const dirtyQueue = useRef(Promise.resolve());
  const editorDirtyRef = useRef(editorDirty);
  editorDirtyRef.current = editorDirty;
  const closeDirty = dirty || editorDirty;
  const active = isActive(runtime.state),
    snapshots = runtime.snapshot?.courses || [],
    statusMap = Object.fromEntries(snapshots.map((c) => [c.id, c]));
  const markDirty = () => {
    draftGeneration.current += 1;
    setDirty(true);
    setNotice("");
    setError("");
    setErrors({});
  };
  const publishDirty = (value) => {
    dirtyQueue.current = dirtyQueue.current
      .then(() => call("set_dirty", value))
      .catch(() => {});
  };
  const update = (fn) => {
    const next = typeof fn === "function" ? fn(configRef.current) : fn;
    configRef.current = next;
    setConfig(next);
    markDirty();
    setErrors({});
  };
  const scrollSection = (section) => {
    document
      .getElementById(section)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const changeClient = (key, value) =>
    update((c) => ({ ...c, client: { ...c.client, [key]: value } }));
  const changeUser = (key, value) => {
    if (configRef.current.user[key] !== value) {
      setPassword("");
      setShowPassword(false);
    }
    update((c) => ({ ...c, user: { ...c.user, [key]: value } }));
  };
  const beginMutation = (runtimeChange = false) => {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(true);
    if (runtimeChange) {
      runtimeEpoch.current += 1;
      runtimeMutating.current = true;
    }
    return true;
  };
  const endMutation = (runtimeChange = false) => {
    if (runtimeChange) {
      runtimeEpoch.current += 1;
      runtimeMutating.current = false;
    }
    busyRef.current = false;
    setBusy(false);
  };
  const closeEditor = () => {
    setEditor(null);
    setEditorDirty(false);
  };
  const closeMutex = () => {
    setMutexEditor(null);
    setEditorDirty(false);
  };

  useEffect(() => {
    let live = true;
    call("bootstrap")
      .then((result) => {
        if (!live) return;
        if (!result.ok) throw new Error(result.error);
        // React Fast Refresh reruns effects. Keep the current in-memory draft
        // and password; bootstrap must not overwrite edits during hot updates.
        if (!configRef.current) setConfig(result.config);
        configRef.savedConfig ??= structuredClone(result.config);
        configRef.incrementalLogs = !!result.capabilities?.incremental_logs;
        setFields(result.fields);
        setPreview(!!result.preview);
        setLiveDevelopment(!!result.development && !!result.live);
        if (result.runtime?.ok && !runtimeMutating.current) {
          setRuntime(result.runtime);
          runtimeEpoch.logCursor = 0;
          runtimeEpoch.logGeneration = null;
          setRuntimeReady(true);
        }
      })
      .catch((e) => setError(e.message));
    return () => {
      live = false;
      busyRef.restartController?.abort();
    };
  }, []);
  useEffect(() => {
    if (!config) return;
    let canceled = false,
      timer;
    const poll = async () => {
      const epoch = runtimeEpoch.current;
      try {
        if (!runtimeMutating.current) {
          const result = await call(
            "poll",
            ...(configRef.incrementalLogs
              ? [
                  runtimeEpoch.logCursor || 0,
                  runtimeEpoch.logGeneration ?? null,
                ]
              : []),
          );
          if (
            !canceled &&
            !runtimeMutating.current &&
            epoch === runtimeEpoch.current
          ) {
            if (result.ok) {
              setRuntime((previous) => mergeRuntime(previous, result));
              runtimeEpoch.logCursor = result.log_cursor;
              runtimeEpoch.logGeneration = result.generation;
              setRuntimeReady(true);
              setPollError("");
            } else setPollError(result.error || "暂时无法获取运行状态");
          }
        }
      } catch {
        if (!canceled) setPollError("暂时无法获取运行状态，正在重新连接");
      }
      if (!canceled) timer = setTimeout(poll, document.hidden ? 5000 : 1000);
    };
    poll();
    return () => {
      canceled = true;
      clearTimeout(timer);
    };
  }, [!!config]);
  useEffect(() => {
    if (config) publishDirty(closeDirty);
  }, [closeDirty, !!config]);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 3500);
    return () => clearTimeout(t);
  }, [notice]);
  useEffect(() => {
    const handler = (e) => {
      if (e.defaultPrevented) return;
      const modalOpen = !!document.querySelector("dialog[open]");
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (!modalOpen) save();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  });

  function locate(issues) {
    const next = Object.fromEntries(
      (issues || []).map((i) => [i.field_path, i.message]),
    );
    setErrors(next);
    const first = issues?.[0];
    if (!first) return;
    const target = issueTarget(first.field_path, configRef.current);
    scrollSection(target.page);
    if (target.kind === "course") {
      editCourse(configRef.current.courses[target.index]);
      setEditorError(first.message);
    } else if (target.kind === "mutex") {
      setMutexEditor(structuredClone(configRef.current.mutexes[target.index]));
      setEditorDirty(false);
      setRuleError(first.message);
    }
    setTimeout(() => {
      const el = document.getElementById(target.focus);
      el?.closest("details")?.setAttribute("open", "");
      el?.focus();
      el?.scrollIntoView({
        block: "center",
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
      });
    }, 100);
  }
  async function save(start = false) {
    if (!configRef.current) return false;
    if (start && (!runtimeReady || pollError)) return false;
    const risk = frequencyRisk(configRef.current.client);
    if (risk.level === "blocked") {
      locate([
        {
          field_path: risk.field || "client.refresh_interval",
          message: risk.message,
        },
      ]);
      return false;
    }
    if (!beginMutation(start)) return false;
    const submitted = structuredClone(configRef.current),
      generation = draftGeneration.current;
    const previous = configRef.savedConfig,
      changed = runtimeChanges(previous, submitted, !!configRef.passwordEdited),
      hasRestartPassword =
        !!password || previous?.user?.student_id === submitted.user?.student_id;
    setError("");
    setErrors({});
    try {
      const result = await call(
        start ? "start" : "save",
        submitted,
        password,
        false,
      );
      if (!result.ok && !result.committed) {
        if (generation === draftGeneration.current) locate(result.issues);
        if (!result.issues?.length || generation !== draftGeneration.current)
          setError(
            result.error || "提交的配置校验未通过，请保存当前修改后重试",
          );
        return false;
      }
      const saved = result.config || submitted,
        merged = mergeSavedDraft(
          configRef.current,
          saved,
          generation,
          draftGeneration.current,
        );
      configRef.savedConfig = structuredClone(saved);
      configRef.passwordEdited = false;
      configRef.current = merged.config;
      setConfig(merged.config);
      setDirty(merged.dirty);
      publishDirty(merged.dirty || editorDirtyRef.current);
      if (!result.ok) {
        setError(result.error || "配置已保存，但启动未完成，请重试");
        return false;
      }
      setNotice(merged.dirty ? "" : start ? "正在启动" : "已保存");
      if (start) {
        scrollSection("overview");
        setRuntime({
          state: "starting",
          snapshot: {
            courses: submitted.courses.map((c) => ({
              ...c,
              status: "unknown",
            })),
          },
          logs: [],
        });
      } else if (changed.length) {
        const current = await call("poll");
        if (current.ok && ["starting", "running"].includes(current.state)) {
          setInfoModal({
            kind: "restart",
            config: structuredClone(saved),
            generation: current.generation,
            changed,
            hasPassword: hasRestartPassword,
            blocked: restartBlockReason(saved, current, hasRestartPassword),
          });
        }
      }
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    } finally {
      endMutation(start);
    }
  }
  async function stop() {
    if (!beginMutation(true)) return;
    setRuntime((r) => ({ ...r, state: "stopping" }));
    try {
      const result = await call("stop");
      if (!result.ok) setError(result.error);
    } catch (e) {
      setError(e.message);
    } finally {
      endMutation(true);
    }
  }
  function deferRestart() {
    setInfoModal(null);
    setNotice("配置已保存，当前任务不变；下次运行生效");
  }
  async function confirmRestart() {
    const pending = infoModal;
    if (pending?.kind !== "restart" || pending.blocked || !beginMutation(true))
      return;
    const controller = new AbortController();
    busyRef.restartController = controller;
    setInfoModal(null);
    scrollSection("overview");
    setError("");
    setNotice("正在停止旧任务，停止完成后应用新配置");
    try {
      const result = await restartWorkflow(call, pending.config, {
        generation: pending.generation,
        signal: controller.signal,
        hasPassword: pending.hasPassword,
        onState: (status) => setRuntime(status),
      });
      if (!result.ok && !result.committed) {
        locate(result.issues);
        throw new Error(
          result.error ||
            "旧任务已停止，新配置未能启动；请检查配置后手动开始。",
        );
      }
      const merged = mergeSavedDraft(
        configRef.current,
        result.config,
        -1,
        draftGeneration.current,
      );
      configRef.current = merged.config;
      configRef.savedConfig = structuredClone(result.config);
      setConfig(merged.config);
      if (!result.ok)
        throw new Error(
          result.error || "旧任务已停止，新任务启动失败；请检查运行记录。",
        );
      setRuntime({ state: "starting", snapshot: { courses: [] }, logs: [] });
      setNotice("已应用保存的配置，正在重新启动选课");
    } catch (e) {
      setNotice("");
      setError(e.message);
    } finally {
      if (busyRef.restartController === controller)
        delete busyRef.restartController;
      endMutation(true);
    }
  }
  function editCourse(course, group = {}) {
    const delay = configRef.current.delays.find((d) => d.course === course?.id);
    setEditor({
      ...course,
      id: course?.id ?? uid(),
      name: course?.name ?? "",
      school: course?.school ?? "",
      class_no: course?.class_no ?? "",
      page: course?.page ?? group.page ?? 1,
      identity: course?.identity ?? group.identity ?? "bzx",
      category: course
        ? courseCategory(configRef.current, course)
        : group.identity === "bfx"
          ? "minor"
          : "major",
      threshold: delay?.threshold ?? "",
      isNew: !course,
    });
    setEditorDirty(false);
    setEditorError("");
  }
  function applyCourse() {
    const issue = courseIssue(configRef.current, editor);
    if (issue) {
      setEditorError(issue);
      return;
    }
    if (
      editor.threshold !== "" &&
      (!Number.isSafeInteger(Number(editor.threshold)) ||
        Number(editor.threshold) <= 0)
    ) {
      setEditorError("延迟名额阈值须为正整数");
      return;
    }
    const course = {
      id: editor.id,
      name: editor.name.trim(),
      school: editor.school.trim(),
      class_no: Number(editor.class_no),
      page: Number(editor.page),
      identity: editor.identity,
    };
    update((c) => ({
      ...c,
      courses: upsertCourse(c, course).courses,
      course_categories: {
        ...c.course_categories,
        [course.id]: editor.category,
      },
      delays: [
        ...c.delays.filter((d) => d.course !== course.id),
        ...(editor.threshold !== ""
          ? [
              {
                id: c.delays.find((d) => d.course === course.id)?.id || uid(),
                course: course.id,
                threshold: Number(editor.threshold),
              },
            ]
          : []),
      ],
    }));
    closeEditor();
  }
  function applyMutex() {
    const courses = [...new Set(mutexEditor.courses)];
    if (courses.length < 2) {
      setRuleError("请选择至少两门课程");
      return;
    }
    if (
      courses.some((id) => !configRef.current.courses.some((c) => c.id === id))
    ) {
      setRuleError("请移除已不存在的课程");
      return;
    }
    update((c) => ({
      ...c,
      mutexes: [
        ...c.mutexes.filter((m) => m.id !== mutexEditor.id),
        { ...mutexEditor, courses },
      ],
    }));
    closeMutex();
    setRuleError("");
  }
  async function fileAction(method) {
    if (!beginMutation()) return;
    try {
      const result = await call(
        method,
        ...(method === "export_config" ? [configRef.current] : []),
      );
      if (result.canceled) return;
      if (!result.ok) {
        locate(result.issues);
        if (!result.issues?.length) setError(result.error);
        return;
      }
      if (method === "import_config") {
        setImportPreview(result);
      } else setNotice("已导出，不包含密码");
    } catch (e) {
      setError(e.message);
    } finally {
      endMutation();
    }
  }
  async function clearData() {
    if (active || !beginMutation(true)) return;
    try {
      const result = await call("clear_data");
      if (!result.ok) throw new Error(result.error);
      draftGeneration.current += 1;
      configRef.current = result.config;
      configRef.savedConfig = structuredClone(result.config);
      configRef.passwordEdited = false;
      setConfig(result.config);
      setPassword("");
      setShowPassword(false);
      setDirty(false);
      setEditorDirty(false);
      setErrors({});
      setError("");
      setPollError("");
      setRuntime({ state: "idle", snapshot: { courses: [] }, logs: [] });
      setConfirmClear(false);
      setNotice(
        result.cache_pending_exit
          ? "配置与日志已清除，界面缓存将在退出后清理"
          : "本地数据已清除",
      );
    } catch (e) {
      setError(e.message);
      setConfirmClear(false);
    } finally {
      endMutation(true);
    }
  }
  const { selected, waiting, abnormal } = courseStatusCounts(snapshots);
  const currentCourses = config ? overviewCourses(config, runtime) : [];
  const rateRisk = config ? frequencyRisk(config.client) : null;
  const courseErrors = Object.entries(errors).filter(
    ([path]) => !path.startsWith("user.") && !path.startsWith("client."),
  );
  const draftStatuses = Object.fromEntries(
    snapshots
      .filter((s) =>
        config?.courses.some(
          (c) =>
            c.id === s.id &&
            c.name === s.name &&
            c.school === s.school &&
            c.class_no === s.class_no &&
            (c.page ?? 1) === (s.page ?? 1) &&
            (c.identity ?? "bzx") === (s.identity ?? "bzx"),
        ),
      )
      .map((c) => [c.id, c]),
  );

  if (!config)
    return (
      <div className="boot">
        <span className="brand-mark">
          <BookOpen />
        </span>
        <h1>PKU Course Helper</h1>
        {error ? (
          <p role="alert">{error}</p>
        ) : (
          <LoaderCircle className="spin" size={20} />
        )}
      </div>
    );
  return (
    <div className="app-shell">
      <div className="workspace">
        <header className="topbar">
          <div
            className="brand"
            aria-label="PKU Course Helper"
            title="PKU Course Helper"
          >
            <span className="brand-mark">
              <BookOpen size={22} />
            </span>
            <div>
              <strong>北大选课助手</strong>
              <span className="brand-subtitle">PKU COURSE HELPER</span>
            </div>
          </div>
          <div className="topbar-right">
            {preview && (
              <span className="preview-label">离线预览 · 模拟数据</span>
            )}
            {liveDevelopment && (
              <span className="preview-label">开发模式 · 真实选课</span>
            )}
            <span className={`connection ${active ? "live" : ""}`}>
              <span />
              {!runtimeReady
                ? "正在连接"
                : runStates[runtime.state] || "未运行"}
            </span>
          </div>
        </header>
        <main className="main-scroll">
          <div className="page">
            <section className="quick-guide" aria-labelledby="guide-title">
              <div className="guide-intro">
                <span className="eyebrow">补退选 · 一页准备，从容等待</span>
                <h1 id="guide-title">把想上的课，安排好。</h1>
                <p>
                  填写账号与目标课程，助手会按规则查询名额、尝试选课。最终结果以学校系统为准。
                </p>
              </div>
              <ol className="guide-steps">
                <li>
                  <span>01</span>
                  <div>
                    <strong>填写账号</strong>
                    <p>使用统一认证学号与密码；密码仅保存在本次会话。</p>
                  </div>
                </li>
                <li>
                  <span>02</span>
                  <div>
                    <strong>添加课程</strong>
                    <p>
                      核对全名、开课单位、班号与页码。主修和选修共用主修入口。
                    </p>
                  </div>
                </li>
                <li>
                  <span>03</span>
                  <div>
                    <strong>开始并关注结果</strong>
                    <p>建议保留默认查询间隔；运行时保持电脑唤醒、网络畅通。</p>
                  </div>
                </li>
              </ol>
            </section>
            {(error || pollError) && (
              <div className="error-banner" role="alert">
                <span>{error || pollError}</span>
                {error && (
                  <IconButton label="关闭错误" onClick={() => setError("")}>
                    <X size={16} />
                  </IconButton>
                )}
              </div>
            )}

            <section
              id="overview"
              className="workspace-section runtime-section"
            >
              <div className="section-title">
                <div>
                  <span className="eyebrow">LIVE STATUS</span>
                  <h2>运行情况</h2>
                </div>
                <button
                  className={`button primary ${active ? "stop" : ""}`}
                  disabled={
                    busy ||
                    runtime.state === "stopping" ||
                    !runtimeReady ||
                    (!active && !!pollError)
                  }
                  onClick={() => (active ? stop() : save(true))}
                >
                  {busy || runtime.state === "stopping" ? (
                    <LoaderCircle size={17} className="spin" />
                  ) : active ? (
                    <Square size={15} />
                  ) : (
                    <Play size={16} />
                  )}{" "}
                  {active
                    ? runtime.state === "stopping"
                      ? "正在停止"
                      : "停止运行"
                    : dirty
                      ? "保存并开始"
                      : "开始运行"}
                </button>
              </div>

              <section className="run-summary">
                <div className={`run-symbol ${active ? "active" : ""}`}>
                  <Activity size={24} />
                </div>
                <div className="run-description">
                  <h2>
                    {active
                      ? "正在关注你的目标课程"
                      : runtime.state === "completed"
                        ? "本次运行已结束"
                        : runtime.state === "failed"
                          ? "本次运行未完成"
                          : runtime.state === "stopped"
                            ? "已停止运行"
                            : "准备开始选课"}
                  </h2>
                  <span>
                    {snapshots.length
                      ? `${snapshots.length} 门课程 · ${runStates[runtime.state]}`
                      : `${config.courses.length} 门目标课程`}
                  </span>
                </div>
                <div className="summary-details">
                  <div className="summary-detail">
                    <span>已选中</span>
                    <strong>{selected}</strong>
                  </div>
                  <div className="summary-detail">
                    <span>等待中</span>
                    <strong>{waiting}</strong>
                  </div>
                  <div className="summary-detail summary-detail-runtime">
                    <span>已运行</span>
                    <strong>
                      {formatRuntimeDuration(
                        runtime.snapshot?.uptime_seconds || 0,
                      )}
                    </strong>
                  </div>
                  <div className="summary-detail">
                    <span title="当前需处理或正在恢复的课程数；历史请求异常次数记在日志中">
                      异常
                    </span>
                    <strong>{abnormal}</strong>
                  </div>
                </div>
              </section>
              <section className="section-block">
                <div className="section-heading">
                  <h2>
                    {!active && snapshots.length ? "上次运行结果" : "课程进展"}
                  </h2>
                  <button
                    className="text-button"
                    onClick={() => scrollSection("courses")}
                  >
                    管理课程 <ArrowRight size={15} />
                  </button>
                </div>
                {currentCourses.length ? (
                  <CourseTable
                    categories={config.course_categories}
                    courses={currentCourses}
                    statuses={statusMap}
                    overview
                  />
                ) : (
                  <Empty
                    onAdd={() => {
                      editCourse();
                    }}
                  />
                )}
              </section>
              <div className="overview-log">
                <LogPanel
                  logs={runtime.logs}
                  storage={runtime.log_storage}
                  total={runtime.log_total}
                />
              </div>
            </section>
            <section id="courses" className="workspace-section">
              <div className="section-title">
                <div>
                  <span className="eyebrow">YOUR COURSES</span>
                  <h2>
                    目标课程{" "}
                    <span className="count-label">{config.courses.length}</span>
                  </h2>
                  <p>同一入口、同一页内按优先级选课，可拖动或使用箭头调整。</p>
                </div>
                <button className="button primary" onClick={() => editCourse()}>
                  <Plus size={17} />
                  添加课程
                </button>
              </div>

              {!!courseErrors.length && (
                <div
                  id="course-errors"
                  tabIndex={-1}
                  className="field-error"
                  role="alert"
                >
                  {courseErrors.map(([field_path, message]) => (
                    <div key={field_path}>
                      <button
                        type="button"
                        className="text-button danger"
                        onClick={() => locate([{ field_path, message }])}
                      >
                        {message}
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {config.courses.length ? (
                <CourseTable
                  categories={config.course_categories}
                  courses={config.courses}
                  statuses={draftStatuses}
                  allCourses={config.courses}
                  onEdit={editCourse}
                  onAdd={(group) => editCourse(undefined, group)}
                  onDelete={setDeleteTarget}
                  onMove={(id, offset) =>
                    update((c) => moveCourse(c, id, offset))
                  }
                  draggable
                  onDrag={setDragId}
                  onDrop={(id) => {
                    if (!dragId || dragId === id) return;
                    const current = configRef.current;
                    const from = current.courses.find((c) => c.id === dragId),
                      to = current.courses.find((c) => c.id === id);
                    if (
                      !from ||
                      !to ||
                      courseGroupKey(from) !== courseGroupKey(to)
                    ) {
                      setNotice(
                        "只能在同一身份、同一页内调整优先级；更换分组请编辑课程",
                      );
                    } else update((c) => reorderCourse(c, dragId, id));
                    setDragId(null);
                  }}
                />
              ) : (
                <Empty onAdd={() => editCourse()} />
              )}
              <section className="rules-section">
                <div className="section-heading">
                  <h2>
                    <Layers size={18} />
                    课程互斥规则
                    <LabelWithHelp
                      help="同组中有一门课确认选中后，其余课程不再继续查询。（学校选课规则不允许的组合自动享有互斥）"
                      iconOnly
                      helpLabel="互斥课程组"
                    >
                      互斥课程组
                    </LabelWithHelp>
                  </h2>
                  <button
                    className="text-button"
                    disabled={config.courses.length < 2}
                    onClick={() => {
                      setMutexEditor({ id: uid(), courses: [] });
                      setEditorDirty(false);
                      setRuleError("");
                    }}
                  >
                    <Plus size={15} />
                    添加互斥组
                  </button>
                </div>
                {config.mutexes.length ? (
                  <div className="rule-list">
                    {config.mutexes.map((m, i) => (
                      <div className="rule-row" key={m.id}>
                        <span className="rule-icon">
                          <Link2 size={18} />
                        </span>
                        <div>
                          <strong>互斥组 {i + 1}</strong>
                          <span>
                            {m.courses
                              .map((id) => {
                                const course = config.courses.find(
                                  (c) => c.id === id,
                                );
                                return course
                                  ? `${course.name}（${courseGroupLabel(course)}）`
                                  : "已不存在的课程";
                              })
                              .join(" / ")}
                          </span>
                        </div>
                        <IconButton
                          label="编辑互斥组"
                          onClick={() => {
                            setMutexEditor(structuredClone(m));
                            setEditorDirty(false);
                            setRuleError("");
                          }}
                        >
                          <Pencil size={15} />
                        </IconButton>
                        <IconButton
                          label="删除互斥组"
                          onClick={() =>
                            update((c) => ({
                              ...c,
                              mutexes: c.mutexes.filter((x) => x.id !== m.id),
                            }))
                          }
                        >
                          <Trash2 size={15} />
                        </IconButton>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="quiet-empty">未设置互斥组</p>
                )}
                {config.delays
                  .filter((d) => !config.courses.some((c) => c.id === d.course))
                  .map((d) => (
                    <div className="rule-row" key={d.id}>
                      <span className="field-error">
                        延迟规则引用的课程已不存在
                      </span>
                      <button
                        className="text-button danger"
                        onClick={() =>
                          update((c) => ({
                            ...c,
                            delays: c.delays.filter((x) => x.id !== d.id),
                          }))
                        }
                      >
                        移除此规则
                      </button>
                    </div>
                  ))}
              </section>
            </section>
            <section id="settings" className="workspace-section">
              <div className="section-title">
                <div>
                  <span className="eyebrow">PREFERENCES</span>
                  <h2>账号与运行设置</h2>
                </div>
                <span className="section-note">设置完成后，保存即可</span>
              </div>
              <div className="settings-content">
                <section className="settings-section">
                  <div className="settings-section-title">
                    <h2>账号</h2>
                    <ShieldCheck size={18} />
                  </div>
                  <div className="form-grid">
                    <Field
                      label="学号"
                      id="user.student_id"
                      error={errors["user.student_id"]}
                    >
                      <input
                        id="user.student_id"
                        autoComplete="off"
                        value={config.user.student_id}
                        onChange={(e) =>
                          changeUser("student_id", e.target.value)
                        }
                      />
                    </Field>
                    <Field
                      label="密码"
                      id="user.password"
                      error={errors["user.password"]}
                    >
                      <div className="password-input">
                        <input
                          id="user.password"
                          type={showPassword ? "text" : "password"}
                          autoComplete="off"
                          placeholder="输入密码"
                          value={password}
                          onChange={(e) => {
                            setPassword(e.target.value);
                            configRef.passwordEdited = true;
                            markDirty();
                          }}
                        />
                        <IconButton
                          label={showPassword ? "隐藏密码" : "显示密码"}
                          onClick={() => setShowPassword(!showPassword)}
                        >
                          {showPassword ? (
                            <EyeOff size={17} />
                          ) : (
                            <Eye size={17} />
                          )}
                        </IconButton>
                      </div>
                    </Field>
                    {fields
                      .filter((f) => f.level === "basic")
                      .map((f) => (
                        <ConfigField
                          key={f.key}
                          field={f}
                          value={config.client[f.key]}
                          onChange={(v) => changeClient(f.key, v)}
                          error={errors["client." + f.key]}
                        />
                      ))}
                  </div>
                </section>
                <Disclosure title="运行策略" collapsible={false}>
                  <div className="form-grid">
                    {fields
                      .filter((f) => f.level === "strategy")
                      .map((f) => (
                        <ConfigField
                          key={f.key}
                          field={f}
                          value={config.client[f.key]}
                          onChange={(v) => changeClient(f.key, v)}
                          error={
                            errors["client." + f.key] ||
                            ("client." + f.key === rateRisk.field &&
                            rateRisk.level === "blocked"
                              ? rateRisk.message
                              : undefined)
                          }
                        />
                      ))}
                  </div>
                  <div
                    className={`rate-feedback ${rateRisk.level}`}
                    aria-live="polite"
                  >
                    <span>全局等待范围</span>
                    <span className="numeric">
                      {rateRisk.minimum == null
                        ? "—"
                        : `${Number(rateRisk.minimum.toFixed(2))}～${Number(rateRisk.maximum.toFixed(2))} 秒`}
                    </span>
                    {rateRisk.level === "warning" && (
                      <p role="status">{rateRisk.message}</p>
                    )}
                    {rateRisk.level !== "none" && (
                      <button
                        className="text-button"
                        onClick={() =>
                          update((c) => ({
                            ...c,
                            client: {
                              ...c.client,
                              refresh_interval: 6,
                              random_deviation: 0.2,
                            },
                          }))
                        }
                      >
                        恢复默认
                      </button>
                    )}
                  </div>
                </Disclosure>
                <Disclosure
                  title="高级设置"
                  help="网络超时、会话和本地数据管理。没有特殊需要时保留默认值。"
                  open={fields.some(
                    (f) => f.level === "advanced" && errors["client." + f.key],
                  )}
                >
                  <div className="form-grid">
                    {fields
                      .filter(
                        (f) =>
                          f.level === "advanced" &&
                          !["page_pool_size", "print_mutex_rules"].includes(
                            f.key,
                          ),
                      )
                      .map((f) => (
                        <ConfigField
                          key={f.key}
                          field={f}
                          value={config.client[f.key]}
                          onChange={(v) => changeClient(f.key, v)}
                          error={errors["client." + f.key]}
                        />
                      ))}
                  </div>
                  <div className="data-tools">
                    <LabelWithHelp help="可从旧版 INI 导入；导出当前草稿，不包含密码。配置、日志与缓存均位于软件目录。">
                      本地数据
                    </LabelWithHelp>
                    <div>
                      <button
                        className="button"
                        disabled={busy}
                        onClick={() => fileAction("import_config")}
                      >
                        <Upload size={15} />
                        导入 INI
                      </button>
                      <button
                        className="button"
                        disabled={busy}
                        onClick={() => fileAction("export_config")}
                      >
                        <Download size={15} />
                        导出 INI
                      </button>
                      <button
                        className="text-button danger"
                        disabled={active || busy}
                        onClick={() => setConfirmClear(true)}
                      >
                        清除本地数据
                      </button>
                    </div>
                  </div>
                </Disclosure>
              </div>
            </section>
            <p className="project-credit">
              基于 Aerisun、Hovennnnn 与 zhongxinghong
              的开源项目修改，感谢学长学姐的积累与分享。非北京大学官方软件。
            </p>
          </div>
        </main>
        <footer className="savebar">
          <span className={dirty ? "unsaved" : ""}>
            {notice ? (
              <>
                <Check size={15} />
                {notice}
              </>
            ) : dirty ? (
              <>
                <span className="dirty-dot" />
                尚未保存{active ? " · 保存后可选择重启应用" : ""}
              </>
            ) : (
              <>
                <CheckCheck size={15} />
                配置已保存
              </>
            )}
          </span>
          <div>
            <kbd>Ctrl</kbd>
            <kbd>S</kbd>
            <button
              className={`button ${dirty ? "primary save-button-attention" : ""}`}
              disabled={busy || !dirty}
              onClick={() => save()}
            >
              <Save size={15} />
              保存配置
            </button>
          </div>
        </footer>
      </div>
      {editor && (
        <Modal
          drawer
          title={editor.isNew ? "添加目标课程" : "编辑课程"}
          onClose={closeEditor}
          onDirty={() => setEditorDirty(true)}
        >
          <div className="modal-body">
            <div className="form-grid">
              <Field
                id="edit-identity"
                label="课程类别"
                help="主修与选修使用学校主修入口；辅修使用辅修入口。"
              >
                <select
                  id="edit-identity"
                  value={editor.category}
                  onChange={(e) =>
                    setEditor({
                      ...editor,
                      category: e.target.value,
                      identity: e.target.value === "minor" ? "bfx" : "bzx",
                    })
                  }
                >
                  <option value="major">主修</option>
                  <option value="elective">选修</option>
                  <option value="minor">辅修</option>
                </select>
              </Field>
              <Field
                id="edit-page"
                label="所在页码"
                help="这门课在补退选课程列表中的第几页。"
              >
                <input
                  id="edit-page"
                  type="number"
                  min="1"
                  max="999"
                  step="1"
                  value={editor.page}
                  onChange={(e) =>
                    setEditor({ ...editor, page: e.target.value })
                  }
                />
              </Field>
            </div>
            <Field
              id="edit-name"
              label="课程名称"
              help="必须与补退选计划中的课程名称保持完全一致！！！"
            >
              <input
                id="edit-name"
                autoFocus
                value={editor.name}
                onChange={(e) => setEditor({ ...editor, name: e.target.value })}
              />
            </Field>
            <div className="form-grid">
              <Field id="edit-school" label="开课单位">
                <input
                  id="edit-school"
                  value={editor.school}
                  onChange={(e) =>
                    setEditor({ ...editor, school: e.target.value })
                  }
                />
              </Field>
              <Field id="edit-class" label="班号">
                <input
                  id="edit-class"
                  type="number"
                  min="0"
                  step="1"
                  value={editor.class_no}
                  onChange={(e) =>
                    setEditor({ ...editor, class_no: e.target.value })
                  }
                />
              </Field>
            </div>
            <Disclosure
              title="延迟选课"
              help="仅当剩余名额不多于阈值时尝试选课，留空表示不限制。"
            >
              <Field
                id="edit-threshold"
                label="剩余名额阈值"
                help="填写正整数。例如 3 表示余量不多于 3 时才提交。"
              >
                <input
                  id="edit-threshold"
                  type="number"
                  min="1"
                  step="1"
                  placeholder="不限制"
                  value={editor.threshold}
                  onChange={(e) =>
                    setEditor({ ...editor, threshold: e.target.value })
                  }
                />
              </Field>
            </Disclosure>
            {editorError && (
              <div className="field-error" role="alert">
                {editorError}
              </div>
            )}
          </div>
          <div className="modal-footer">
            <button className="button" onClick={closeEditor}>
              取消
            </button>
            <button className="button primary" onClick={applyCourse}>
              {editor.isNew ? "添加课程" : "应用修改"}
              <ArrowRight size={16} />
            </button>
          </div>
        </Modal>
      )}
      {deleteTarget && (
        <Modal
          title="删除课程"
          onClose={() => setDeleteTarget(null)}
          className="save-warning-modal delete-confirm-modal"
        >
          <div className="modal-body">
            <p>删除「{deleteTarget.name}」？</p>
            {(config.mutexes.some((m) => m.courses.includes(deleteTarget.id)) ||
              config.delays.some((d) => d.course === deleteTarget.id)) && (
              <p className="muted">关联的延迟规则与失效互斥组也会一并移除。</p>
            )}
          </div>
          <div className="modal-footer">
            <button className="button" onClick={() => setDeleteTarget(null)}>
              取消
            </button>
            <button
              className="button primary"
              onClick={() => {
                update((c) => removeCourse(c, deleteTarget.id));
                setDeleteTarget(null);
              }}
            >
              删除课程
            </button>
          </div>
        </Modal>
      )}
      {mutexEditor && (
        <Modal
          title="设置互斥组"
          onClose={closeMutex}
          onDirty={() => setEditorDirty(true)}
        >
          <div className="modal-body">
            <LabelWithHelp help="选择至少两门课程，其中一门确认选中后，其余课程不再继续尝试。">
              选择课程
            </LabelWithHelp>
            <div className="course-checklist" id="mutex-list" tabIndex={-1}>
              {config.courses.map((c) => (
                <label key={c.id}>
                  <input
                    type="checkbox"
                    checked={mutexEditor.courses.includes(c.id)}
                    onChange={(e) =>
                      setMutexEditor({
                        ...mutexEditor,
                        courses: e.target.checked
                          ? [...mutexEditor.courses, c.id]
                          : mutexEditor.courses.filter((x) => x !== c.id),
                      })
                    }
                  />
                  <div>
                    <strong>{c.name}</strong>
                    <span>
                      {courseGroupLabel(c)} · {c.school} · {c.class_no} 班
                    </span>
                  </div>
                </label>
              ))}
              {[
                ...new Set(
                  mutexEditor.courses.filter(
                    (id) => !config.courses.some((c) => c.id === id),
                  ),
                ),
              ].map((id) => (
                <label key={id}>
                  <input
                    type="checkbox"
                    checked
                    onChange={() =>
                      setMutexEditor({
                        ...mutexEditor,
                        courses: mutexEditor.courses.filter((x) => x !== id),
                      })
                    }
                  />
                  <span>已不存在的课程（取消勾选以移除）</span>
                </label>
              ))}
            </div>
            {ruleError && (
              <p className="field-error" role="alert">
                {ruleError}
              </p>
            )}
          </div>
          <div className="modal-footer">
            <button className="button" onClick={closeMutex}>
              取消
            </button>
            <button className="button primary" onClick={applyMutex}>
              应用规则
            </button>
          </div>
        </Modal>
      )}
      {importPreview && (
        <Modal title="导入配置" onClose={() => setImportPreview(null)}>
          <div className="modal-body">
            <p>
              将当前草稿替换为 {importPreview.config.courses.length} 门课程、
              {importPreview.config.mutexes.length} 个互斥组。
            </p>
            <LabelWithHelp help="当前文件不会被覆盖，保存后才会应用导入配置。兼容扩展字段会随配置保留。">
              导入为草稿
            </LabelWithHelp>
          </div>
          <div className="modal-footer">
            <button className="button" onClick={() => setImportPreview(null)}>
              取消
            </button>
            <button
              className="button primary"
              onClick={() => {
                update({
                  ...importPreview.config,
                  revision: configRef.current.revision,
                });
                setPassword(importPreview.password || "");
                configRef.passwordEdited = !!importPreview.password;
                setShowPassword(false);
                setImportPreview(null);
              }}
            >
              导入为草稿
            </button>
          </div>
        </Modal>
      )}
      {infoModal?.kind === "restart" && (
        <Modal
          title="运行配置已保存，是否重启选课？"
          onClose={deferRestart}
          className="save-warning-modal restart-confirm-modal"
        >
          <div className="modal-body">
            <p>修改的配置需要重启选课才能生效</p>
            {infoModal.blocked && (
              <p className="field-error" role="alert">
                {infoModal.blocked}
              </p>
            )}
          </div>
          <div className="modal-footer">
            <button className="button" onClick={deferRestart}>
              下次运行生效
            </button>
            <button
              className="button primary"
              disabled={busy || !!infoModal.blocked}
              onClick={confirmRestart}
            >
              重启并应用
            </button>
          </div>
        </Modal>
      )}
      {confirmClear && (
        <Modal
          title="清除本地数据"
          onClose={() => {
            if (!busyRef.current) setConfirmClear(false);
          }}
        >
          <div className="modal-body">
            <p>
              将删除软件目录中的账号配置、已记住的密码、备份和日志。操作无法撤销。
            </p>
          </div>
          <div className="modal-footer">
            <button
              className="button"
              disabled={busy}
              onClick={() => setConfirmClear(false)}
            >
              取消
            </button>
            <button
              className="button primary"
              disabled={busy || active}
              onClick={clearData}
            >
              {busy ? "正在清除" : "清除数据"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function ConfigField({ field: f, value, onChange, error }) {
  const help =
    f.key === "refresh_interval"
      ? "页面级共享的标准查询间隔，默认 6 秒，长时间运行最短不得少于 4 秒。任何间隔都不能保证不被限流。"
      : f.help;
  return (
    <Field id={"client." + f.key} label={f.label} help={help} error={error}>
      {f.type === "bool" ? (
        <input
          id={"client." + f.key}
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
        />
      ) : (
        <div className="unit-input">
          <input
            id={"client." + f.key}
            type="number"
            min={f.min}
            max={f.max}
            step={f.type === "int" ? 1 : 0.1}
            value={value}
            onChange={(e) =>
              onChange(e.target.value === "" ? "" : Number(e.target.value))
            }
          />
          {/interval|timeout|max_life/.test(f.key) && <span>秒</span>}
        </div>
      )}
    </Field>
  );
}
function Empty({ onAdd }) {
  return (
    <div className="empty-state">
      <div className="empty-graphic">
        <BookOpen size={30} />
        <span>
          <Plus size={12} />
        </span>
      </div>
      <h3>还没有目标课程</h3>
      <button className="text-button" onClick={onAdd}>
        添加第一门课程 <ArrowRight size={15} />
      </button>
    </div>
  );
}
function CourseTable({ courses, allCourses = courses, onAdd, ...props }) {
  const groups = courseGroups(courses, allCourses);
  if (!groups.length) return <div className="quiet-empty">没有匹配的课程</div>;
  return (
    <div className="course-groups">
      {groups.map((group) => (
        <section className="course-group" key={group.key}>
          <div className="course-group-heading">
            <div>
              <h3>{group.label}</h3>
            </div>
            {onAdd && (
              <button className="text-button" onClick={() => onAdd(group)}>
                <Plus size={15} />
                在本页添加
              </button>
            )}
          </div>
          <CourseGroupTable
            {...props}
            courses={group.courses}
            allCourses={group.allCourses}
            label={group.label}
          />
        </section>
      ))}
    </div>
  );
}
function CourseGroupTable({
  courses,
  label,
  statuses,
  categories,
  overview,
  allCourses = courses,
  onEdit,
  onDelete,
  onMove,
  draggable,
  onDrag,
  onDrop,
}) {
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">{label}，优先级只在本组内生效</caption>
        <thead>
          <tr>
            <th className="rank-col">组内优先级</th>
            <th>课程名称</th>
            <th>班号</th>
            <th>开课单位</th>
            {overview && <th>剩余名额</th>}
            <th>状态</th>
            {!overview && (
              <th className="actions-col">
                <span className="sr-only">操作</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {courses.map((c) => (
            <tr
              key={c.id}
              draggable={draggable}
              onDragStart={() => onDrag?.(c.id)}
              onDragEnd={() => onDrag?.(null)}
              onDragOver={(e) => {
                if (draggable) e.preventDefault();
              }}
              onDrop={(e) => {
                e.preventDefault();
                if (draggable) onDrop?.(c.id);
              }}
            >
              <td className="rank-col">
                {allCourses.findIndex((x) => x.id === c.id) + 1}
              </td>
              <td className="course-name">
                <strong>{c.name}</strong>
                <span className="category-tag">
                  {
                    categoryLabels[
                      courseCategory({ course_categories: categories }, c)
                    ]
                  }
                </span>
              </td>
              <td className="class-col">{Number(c.class_no)}</td>
              <td className="school-col">{c.school}</td>
              {overview && (
                <td>
                  {Number.isFinite(c.remaining) ? c.remaining : "—"}
                  {Number.isFinite(c.observed_at) && (
                    <time
                      className="quota-time"
                      dateTime={new Date(c.observed_at * 1000).toISOString()}
                    >
                      {new Date(c.observed_at * 1000).toLocaleTimeString(
                        "zh-CN",
                        { hour12: false },
                      )}
                    </time>
                  )}
                </td>
              )}
              <td>
                <CourseStatus
                  course={{
                    ...c,
                    category: courseCategory(
                      { course_categories: categories },
                      c,
                    ),
                  }}
                  status={statuses[c.id]?.status || c.status || "unknown"}
                  reason={statuses[c.id]?.reason || c.reason}
                />
              </td>
              {!overview && (
                <td>
                  <div className="row-actions">
                    <IconButton
                      label={`上移 ${c.name}`}
                      disabled={allCourses[0]?.id === c.id}
                      onClick={() => onMove(c.id, -1)}
                    >
                      <ArrowUp size={14} />
                    </IconButton>
                    <IconButton
                      label={`下移 ${c.name}`}
                      disabled={allCourses.at(-1)?.id === c.id}
                      onClick={() => onMove(c.id, 1)}
                    >
                      <ArrowDown size={14} />
                    </IconButton>
                    <IconButton
                      label={`编辑 ${c.name}`}
                      onClick={() => onEdit(c)}
                    >
                      <Pencil size={14} />
                    </IconButton>
                    <IconButton
                      label={`删除 ${c.name}`}
                      onClick={() => onDelete(c)}
                    >
                      <Trash2 size={14} />
                    </IconButton>
                  </div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {!courses.length && <div className="quiet-empty">没有匹配的课程</div>}
    </div>
  );
}

const root =
  import.meta.hot?.data.root ?? createRoot(document.getElementById("root"));
if (import.meta.hot) import.meta.hot.data.root = root;
root.render(<App />);
