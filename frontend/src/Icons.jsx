import React from "react";

// Neutral task-tool symbols. No campus, crest, or institutional imagery.
function icon(children) {
  return function Icon({ size = 24, strokeWidth = 1.7, ...props }) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
        {...props}
      >
        {children}
      </svg>
    );
  };
}

export const TaskMark = icon(
  <>
    <rect
      x="3"
      y="3"
      width="7"
      height="7"
      rx="2"
      fill="currentColor"
      stroke="none"
    />
    <rect
      x="14"
      y="3"
      width="7"
      height="7"
      rx="2"
      fill="currentColor"
      stroke="none"
    />
    <rect
      x="3"
      y="14"
      width="7"
      height="7"
      rx="2"
      fill="currentColor"
      stroke="none"
    />
    <path d="m14 18 2.5 2.5L22 14" strokeWidth="2.5" />
  </>,
);
export const Plus = icon(
  <>
    <rect x="3" y="3" width="18" height="18" rx="6" />
    <path d="M7.5 12h9M12 7.5v9" />
  </>,
);
export const Play = icon(
  <path d="M8 4.5 20 12 8 19.5Z" fill="currentColor" stroke="none" />,
);
export const Square = icon(
  <rect
    x="5"
    y="5"
    width="14"
    height="14"
    rx="4"
    fill="currentColor"
    stroke="none"
  />,
);
export const ArrowUp = icon(
  <>
    <path d="m7 10 5-5 5 5M12 5v14M5 19h3m8 0h3" />
  </>,
);
export const ArrowDown = icon(
  <>
    <path d="m7 14 5 5 5-5M12 5v14M5 5h3m8 0h3" />
  </>,
);
export const ArrowRight = icon(<path d="M4 12h15m-5-6 6 6-6 6" />);
export const X = icon(<path d="m7 7 10 10M17 7 7 17" />);
export const HelpCircle = icon(
  <>
    <rect x="3" y="3" width="18" height="18" rx="7" />
    <path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4M12 16.5v.1" />
  </>,
);
export const ChevronDown = icon(<path d="m6 9 6 6 6-6" strokeWidth="2.2" />);
export const Check = icon(<path d="m4 12 5 5L20 6" strokeWidth="2.2" />);
export const CheckCheck = icon(
  <>
    <path d="m3 12 4 4L17 6m-5 10 3 3 7-8" />
  </>,
);
export const Circle = icon(<rect x="6" y="6" width="12" height="12" rx="6" />);
export const Activity = icon(
  <>
    <path d="M5 18v-5m7 5V6m7 12V9" strokeWidth="3" />
    <path d="M3 22h18" />
  </>,
);
export const Trash2 = icon(
  <>
    <path d="M4 7h16M9 3h6M6 7l1 14h10l1-14M10 11v6m4-6v6" />
  </>,
);
export const Pencil = icon(
  <>
    <path d="m5 15 10-10 4 4L9 19l-5 1ZM13 7l4 4M13 21h7" />
  </>,
);
export const Download = icon(
  <>
    <path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4" />
  </>,
);
export const Upload = icon(
  <>
    <path d="M12 15V3m-5 5 5-5 5 5M4 16v4h16v-4" />
  </>,
);
export const Eye = icon(
  <>
    <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
    <rect x="9" y="9" width="6" height="6" rx="3" />
  </>,
);
export const EyeOff = icon(
  <>
    <path d="m3 3 18 18M8 6.7A12 12 0 0 1 12 6c6.5 0 10 6 10 6a19 19 0 0 1-3.5 4M5.5 8.5A20 20 0 0 0 2 12s3.5 6 10 6a12 12 0 0 0 4-.7" />
  </>,
);
export const Layers = icon(
  <>
    <rect x="3" y="3" width="8" height="8" rx="2" />
    <rect x="13" y="13" width="8" height="8" rx="2" />
    <path d="M15 5h4v4M5 15v4h4" />
  </>,
);
export const ShieldCheck = icon(
  <>
    <path d="M4 6h16M4 12h9M4 18h6m10-9v-6m-6 9v-3M7 21v-6m7 4 2 2 5-6" />
  </>,
);
export const Save = icon(
  <>
    <path d="M4 4h16v16H4ZM8 4v6h8V4M8 20v-5h8v5" />
  </>,
);
export const LoaderCircle = icon(
  <>
    <path d="M12 3a9 9 0 1 1-9 9" strokeDasharray="30 8 8 8" />
  </>,
);
export const Link2 = icon(
  <>
    <path d="M10 8H7a4 4 0 0 0 0 8h3m4-8h3a4 4 0 0 1 0 8h-3M8 12h8" />
  </>,
);
