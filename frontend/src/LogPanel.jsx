import React, { useEffect, useRef, useState } from "react";
import { ChevronDown } from "./Icons.jsx";

const PAGE_SIZE = 200;
export default React.memo(function LogPanel({ logs = [], storage = {} }) {
  const [open, setOpen] = useState(false),
    [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const output = useRef(null);
  const visible = open ? logs.slice(0, visibleCount).join("\n") : "";
  const hasMore = visibleCount < logs.length;
  useEffect(() => {
    if (open) setVisibleCount(PAGE_SIZE);
  }, [open]);
  return (
    <details
      className="disclosure"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <span>详细日志</span>
        <ChevronDown size={16} aria-hidden="true" />
      </summary>
      {open && (
        <div className="disclosure-body">
          {!!storage.error && (
            <p role="alert" className="field-error">
              {storage.error}
            </p>
          )}
          {!!storage.dropped && (
            <p className="field-error">
              磁盘日志有 {storage.dropped}{" "}
              条未能写入（队列满或磁盘异常），不影响选课状态。
            </p>
          )}
          <pre
            className="log-output"
            ref={output}
            tabIndex={0}
            aria-label="运行日志"
            onScroll={(e) => {
              const element = e.currentTarget;
              const nearBottom =
                element.scrollTop + element.clientHeight >=
                element.scrollHeight - 24;
              if (nearBottom && hasMore)
                setVisibleCount((count) =>
                  Math.min(count + PAGE_SIZE, logs.length),
                );
            }}
          >
            {visible || "暂无记录"}
          </pre>
        </div>
      )}
    </details>
  );
});
