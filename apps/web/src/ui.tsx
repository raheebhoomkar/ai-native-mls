/** Small shared pieces of the Editorial Luxury design: icons, marks, AI tag, confidence meter. */

import type { ReactNode } from "react";

const ICONS = {
  home: "M3 10.5 12 3l9 7.5M5 9.5V21h14V9.5M10 21v-6h4v6",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  table: "M3 5h18v14H3zM3 10h18M3 15h18M9 5v14",
  shield: "M12 3 4 6v6c0 4.5 3.4 8.2 8 9 4.6-.8 8-4.5 8-9V6l-8-3zm-3 9 2 2 4-4",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  users:
    "M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 18.5V20M13.5 8a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0zM20 20v-1.5a3.5 3.5 0 0 0-2.5-3.4M15.5 4.6a3.5 3.5 0 0 1 0 6.8",
  key: "M12 15a4 4 0 1 1-8 0 4 4 0 0 1 8 0zm-1.2-2.8 8.7-8.7M16 7l2.5 2.5m0-5 2 2",
  link: "M10 14a4.5 4.5 0 0 0 6.4 0l3.2-3.2a4.5 4.5 0 0 0-6.4-6.4L12 5.6M14 10a4.5 4.5 0 0 0-6.4 0l-3.2 3.2a4.5 4.5 0 0 0 6.4 6.4l1.2-1.2",
  file: "M14 3H6v18h12V7l-4-4zm0 0v4h4M9 12h6M9 16h6",
  bell: "M6 16v-5a6 6 0 1 1 12 0v5l1.5 2h-15L6 16zm4 4a2 2 0 0 0 4 0",
  user: "M16 8a4 4 0 1 1-8 0 4 4 0 0 1 8 0zM4 21a8 8 0 0 1 16 0",
  columns: "M3 9l9-5 9 5M5 9v9m4.5-9v9m5-9v9M19 9v9M3 21h18M4 18h16",
  menu: "M4 7h16M4 12h16M4 17h16",
  sparkle:
    "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zm7 12 .7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7L19 15z",
  bed: "M3 19V6m0 9h18v4m0-4v-3a3 3 0 0 0-3-3h-7v6m-3.5-3a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z",
  bath: "M4 12h16v3a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5v-3zm2 0V5.5A2.5 2.5 0 0 1 10.5 4M7 20l-1 1.5M17 20l1 1.5",
  area: "M4 4h16v16H4zm5 0v4m5-4v4M4 9h4m-4 5h4",
  calendar: "M4 6h16v15H4zm0 4h16M8 3v4m8-4v4",
  pin: "M12 21s7-6.2 7-11.5a7 7 0 0 0-14 0C5 14.8 12 21 12 21zm2.5-11.5a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4m-4-4h10",
  plus: "M12 5v14M5 12h14",
  upload: "M12 16V4M7 9l5-5 5 5M4 16v4h16v-4",
  image:
    "M3 5h18v14H3zm0 11 5-5 4 4 3-3 6 6m-4.5-8a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0z",
  map: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zm0 0v14m6-12v14",
  comment: "M4 5h16v11H9l-5 4V5z",
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={ICONS[name]} />
    </svg>
  );
}

/** The product mark: an arch in a frame. */
export function BrandMark() {
  return (
    <svg
      className="brand-mark"
      viewBox="0 0 40 40"
      fill="none"
      stroke="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="0.75" y="0.75" width="38.5" height="38.5" rx="2" />
      <path d="M12 31V19a8 8 0 0 1 16 0v12M8.5 31h23" strokeWidth="1.5" />
      <path d="M17 31v-6a3 3 0 0 1 6 0v6" />
    </svg>
  );
}

/** Wordmark: the mark, the name and a small line under it. */
export function Brand({ sub = "Listing service" }: { sub?: string }) {
  return (
    <>
      <BrandMark />
      <span>
        <span className="brand-name">AI-Native MLS</span>
        <span className="brand-sub">{sub}</span>
      </span>
    </>
  );
}

/** A colonnade drawn in thin lines; decoration on the sign-in page. */
export function Arches() {
  const arches = [0, 1, 2, 3, 4].map((i) => 20 + i * 100);
  return (
    <svg
      className="arches"
      viewBox="0 0 520 380"
      fill="none"
      stroke="currentColor"
      strokeWidth="1"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M0 108 260 24l260 84M0 108h520M10 128h500" />
      {arches.map((x) => (
        <path key={x} d={`M${x} 380V190a40 40 0 0 1 80 0v190`} />
      ))}
      <path d="M0 379h520" />
    </svg>
  );
}

/** Stand-in for a missing photo: a quiet line drawing, not a stock image. */
export function PlaceholderArt({ children }: { children?: ReactNode }) {
  return (
    <div className="placeholder-art" aria-hidden={children ? undefined : true}>
      <svg
        viewBox="0 0 80 64"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        aria-hidden="true"
        focusable="false"
      >
        <path d="M6 60h68M14 60V30L40 10l26 20v30M30 60V44a10 10 0 0 1 20 0v16" />
        <path d="M20 34h8v8h-8zM52 34h8v8h-8z" />
      </svg>
      {children}
    </div>
  );
}

/** Marks output that came from an AI model or AI-assisted pipeline. */
export function AiTag({ children = "AI" }: { children?: ReactNode }) {
  return (
    <span className="ai-tag">
      <Icon name="sparkle" />
      {children}
    </span>
  );
}

/** "82% confident" with a small meter; the meter is decoration, the words carry the value. */
export function Confidence({
  value,
  suffix = "confident",
}: {
  value: number;
  suffix?: string;
}) {
  const percent = Math.round(value * 100);
  return (
    <small className="confidence">
      <span className={value < 0.6 ? "meter low" : "meter"} aria-hidden="true">
        <span style={{ width: `${percent}%` }} />
      </span>
      {percent}% {suffix}
    </small>
  );
}

export function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0]!.toUpperCase())
      .join("") || "?"
  );
}
