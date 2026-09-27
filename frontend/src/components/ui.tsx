import type { ButtonHTMLAttributes, PropsWithChildren, ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export const Button = ({
  children,
  tone = "default",
  size = "md",
  icon,
  busy,
  className = "",
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: "default" | "primary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  icon?: IconName;
  busy?: boolean;
}) => (
  <button
    className={`button button--${tone} button--${size} ${className}`}
    disabled={disabled || busy}
    {...props}
  >
    {busy ? <span className="button__spinner" aria-hidden="true" /> : icon ? <Icon name={icon} size={size === "sm" ? 15 : 17} /> : null}
    <span>{children}</span>
  </button>
);

export const Badge = ({
  children,
  tone = "neutral",
  dot = false,
}: PropsWithChildren<{ tone?: "neutral" | "success" | "warning" | "danger" | "info" | "purple"; dot?: boolean }>) => (
  <span className={`badge badge--${tone}`}>
    {dot ? <span className="badge__dot" /> : null}
    {children}
  </span>
);

export const Panel = ({
  children,
  className = "",
  padded = true,
}: PropsWithChildren<{ className?: string; padded?: boolean }>) => (
  <section className={`panel ${padded ? "panel--padded" : ""} ${className}`}>{children}</section>
);

export const PageHeader = ({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) => (
  <header className="page-header">
    <div>
      {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
    {actions ? <div className="page-header__actions">{actions}</div> : null}
  </header>
);

export const Metric = ({
  label,
  value,
  detail,
  icon,
  accent = "teal",
}: {
  label: string;
  value: string | number;
  detail: string;
  icon: IconName;
  accent?: "teal" | "amber" | "purple" | "blue";
}) => (
  <Panel className="metric-card">
    <span className={`metric-card__icon metric-card__icon--${accent}`}><Icon name={icon} /></span>
    <div className="metric-card__value">{value}</div>
    <div className="metric-card__label">{label}</div>
    <div className="metric-card__detail">{detail}</div>
  </Panel>
);

export const EmptyState = ({ icon, title, description, action }: { icon: IconName; title: string; description: string; action?: ReactNode }) => (
  <div className="empty-state">
    <span className="empty-state__icon"><Icon name={icon} size={24} /></span>
    <h3>{title}</h3>
    <p>{description}</p>
    {action ? <div className="empty-state__action">{action}</div> : null}
  </div>
);

export const LoadingBlock = ({ rows = 4 }: { rows?: number }) => (
  <div className="loading-block" aria-label="正在加载" aria-busy="true">
    {Array.from({ length: rows }, (_, index) => <span key={index} style={{ width: `${92 - index * 9}%` }} />)}
  </div>
);

export const Modal = ({
  open,
  title,
  description,
  children,
  footer,
  onClose,
  width = "md",
}: PropsWithChildren<{
  open: boolean;
  title: string;
  description?: string;
  footer?: ReactNode;
  onClose(): void;
  width?: "sm" | "md" | "lg" | "xl";
}>) => {
  if (!open) return null;
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className={`modal modal--${width}`} role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <header className="modal__header">
          <div>
            <h2 id="modal-title">{title}</h2>
            {description ? <p>{description}</p> : null}
          </div>
          <button className="icon-button" type="button" aria-label="关闭" onClick={onClose}><Icon name="close" /></button>
        </header>
        <div className="modal__body">{children}</div>
        {footer ? <footer className="modal__footer">{footer}</footer> : null}
      </section>
    </div>
  );
};

export const Field = ({ label, hint, children, className = "" }: PropsWithChildren<{ label: string; hint?: string; className?: string }>) => (
  <label className={`field ${className}`}>
    <span className="field__label">{label}</span>
    {children}
    {hint ? <small>{hint}</small> : null}
  </label>
);

export const Segmented = <T extends string>({ value, options, onChange, label }: {
  value: T;
  options: { value: T; label: string }[];
  onChange(value: T): void;
  label: string;
}) => (
  <div className="segmented" role="group" aria-label={label}>
    {options.map((option) => (
      <button
        key={option.value}
        type="button"
        className={value === option.value ? "is-active" : ""}
        onClick={() => onChange(option.value)}
        aria-pressed={value === option.value}
      >
        {option.label}
      </button>
    ))}
  </div>
);
