import type { SVGProps } from "react";

export type IconName =
  | "activity"
  | "alert"
  | "arrow"
  | "check"
  | "chevron"
  | "close"
  | "database"
  | "download"
  | "edit"
  | "external"
  | "file"
  | "grid"
  | "headphones"
  | "info"
  | "lock"
  | "menu"
  | "message"
  | "mic"
  | "more"
  | "pause"
  | "play"
  | "plus"
  | "refresh"
  | "retry"
  | "search"
  | "settings"
  | "spark"
  | "square"
  | "tasks"
  | "unlock"
  | "upload"
  | "users"
  | "waveform";

export interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number;
}

export const Icon = ({ name, size = 18, ...props }: IconProps) => {
  const paths = (() => {
    switch (name) {
      case "grid":
        return <><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>;
      case "waveform":
        return <><path d="M3 12h2l2-7 4 14 3-11 3 8 2-4h2"/><path d="M3 5v14M21 5v14"/></>;
      case "tasks":
        return <><path d="M9 6h11M9 12h11M9 18h11"/><path d="m3 6 1 1 2-2M3 12l1 1 2-2M3 18l1 1 2-2"/></>;
      case "users":
        return <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></>;
      case "message":
        return <><path d="M21 15a4 4 0 0 1-4 4H8l-5 3v-7a4 4 0 0 1-1-2.6V7a4 4 0 0 1 4-4h11a4 4 0 0 1 4 4z"/><path d="M7 8h10M7 12h7"/></>;
      case "activity":
        return <path d="M3 12h4l2-7 4 14 2-7h6"/>;
      case "settings":
        return <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06-2.83 2.83-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21h-4v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06-2.83-2.83.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3v-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06 2.83-2.83.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3h4v.09A1.65 1.65 0 0 0 15 4.6a1.65 1.65 0 0 0 1.82-.33l.06-.06 2.83 2.83-.06.06A1.65 1.65 0 0 0 19.4 9c.12.38.2.75.2 1h1.4v4h-1.4c0 .25-.08.62-.2 1z"/></>;
      case "plus":
        return <path d="M12 5v14M5 12h14"/>;
      case "upload":
        return <><path d="M12 16V4m0 0-5 5m5-5 5 5"/><path d="M4 15v5h16v-5"/></>;
      case "download":
        return <><path d="M12 4v12m0 0 5-5m-5 5-5-5"/><path d="M4 19h16"/></>;
      case "play":
        return <path d="m7 4 13 8-13 8z"/>;
      case "pause":
        return <><path d="M8 5v14M16 5v14"/></>;
      case "square":
        return <rect x="5" y="5" width="14" height="14" rx="2"/>;
      case "retry":
      case "refresh":
        return <><path d="M20 11a8 8 0 1 0-2.34 5.66"/><path d="M20 4v7h-7"/></>;
      case "close":
        return <path d="m6 6 12 12M18 6 6 18"/>;
      case "check":
        return <path d="m5 12 4 4L19 6"/>;
      case "alert":
        return <><path d="M10.3 3.7 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.7a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></>;
      case "info":
        return <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/></>;
      case "search":
        return <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>;
      case "lock":
        return <><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>;
      case "unlock":
        return <><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 7.5-2"/></>;
      case "chevron":
      case "arrow":
        return <path d="m9 18 6-6-6-6"/>;
      case "more":
        return <><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/></>;
      case "external":
        return <><path d="M14 3h7v7M21 3l-9 9"/><path d="M18 13v7H4V6h7"/></>;
      case "file":
        return <><path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h5M9 13h6M9 17h6"/></>;
      case "edit":
        return <><path d="m4 20 4.5-1 10-10-3.5-3.5-10 10z"/><path d="m13.5 6.5 3.5 3.5"/></>;
      case "mic":
        return <><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/></>;
      case "headphones":
        return <><path d="M4 14v-2a8 8 0 0 1 16 0v2"/><path d="M4 14h3v7H4zM17 14h3v7h-3z"/></>;
      case "spark":
        return <><path d="m12 3 1.4 4.1L17.5 8.5l-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4z"/><path d="m19 14 .8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8z"/></>;
      case "database":
        return <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></>;
      case "menu":
        return <path d="M4 7h16M4 12h16M4 17h16"/>;
      default:
        return null;
    }
  })();

  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {paths}
    </svg>
  );
};
