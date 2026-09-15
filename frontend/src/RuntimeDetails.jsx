import React, { useState } from "react";
import {
  courseStates,
  courseStatusLabel,
  formatUptime,
  isActive,
} from "./state.js";

export function CourseStatus({ status = "unknown", reason, course }) {
  const [, tone] = courseStates[status] || courseStates.unknown;
  const label = courseStatusLabel(status, reason, course);
  return (
    <span className="course-status-detail">
      <span className={`badge ${tone}`}>
        <span />
        {label}
      </span>
      {reason && reason !== label && reason !== "尚未查询" && (
        <span className="status-reason">{reason}</span>
      )}
    </span>
  );
}

export default function RuntimeDetails({ snapshot = {}, state }) {
  const [open, setOpen] = useState(false),
    [page, setPage] = useState(0);
  if (!snapshot.sessions) return null;
  const pages = snapshot.pages || [],
    problems = pages.filter((p) => p.failures > 0 && !p.done);
  const count = Math.max(1, Math.ceil(pages.length / 50)),
    index = Math.min(page, count - 1);
  const active = isActive(state);
  return (
    <details
      className="disclosure runtime-details"
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>
        会话与页面状态{" "}
        <span>
          {active && problems.length
            ? `${problems.length} 个页面正在恢复`
            : "查看调度明细"}
        </span>
      </summary>
      {open && (
        <div className="disclosure-body runtime-health">
          <p>
            已运行 {formatUptime(snapshot.uptime_seconds)} · 页面查询{" "}
            {snapshot.elective_loop || 0} 次
          </p>
          <div className="session-health">
            {snapshot.sessions.map((s) => (
              <span key={s.slot}>
                #{s.slot} {s.identity === "bfx" ? "辅修" : "主修"}
                {s.page ? ` / 第 ${s.page} 页` : ""}：
                {!active
                  ? "已停止"
                  : s.stalled
                    ? "无响应，正在安全停止"
                    : s.phase || "空闲"}
              </span>
            ))}
          </div>
          <ul className="page-health">
            {pages.slice(index * 50, (index + 1) * 50).map((p) => (
              <li key={`${p.identity}:${p.page}`}>
                {p.identity === "bfx" ? "辅修" : "主修"} · 第 {p.page} 页 · 查询{" "}
                {p.queries || 0} 次：
                {!active
                  ? "已停止"
                  : p.done
                    ? "已结束"
                    : p.busy
                      ? "处理中"
                      : p.failures
                        ? `约 ${Math.ceil(p.retry_in)} 秒后重试`
                        : "等待轮询"}
                {p.last_error && (
                  <span className="field-error">
                    ；{p.last_error}（连续 {p.failures} 次）
                  </span>
                )}
              </li>
            ))}
          </ul>
          {count > 1 && (
            <div className="log-pagination">
              <span>
                第 {index + 1} / {count} 页
              </span>
              <button
                className="button"
                disabled={index === 0}
                onClick={() => setPage(index - 1)}
              >
                上一页
              </button>
              <button
                className="button"
                disabled={index === count - 1}
                onClick={() => setPage(index + 1)}
              >
                下一页
              </button>
            </div>
          )}
        </div>
      )}
    </details>
  );
}
