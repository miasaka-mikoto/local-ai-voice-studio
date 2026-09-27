import type { CompanionState } from "./DigitalCompanion";

const stateLabels: Record<CompanionState, string> = {
  idle: "待机陪伴",
  listening: "正在聆听",
  thinking: "正在整理回应",
  speaking: "正在说话",
  error: "等待重试",
};

export interface StudioAvatarProps {
  state: CompanionState;
  compact?: boolean;
}

/** An original CSS-only character: no external image, model, or runtime asset. */
export const StudioAvatar = ({ state, compact = false }: StudioAvatarProps) => (
  <div
    className={`studio-avatar studio-avatar--${state}${compact ? " studio-avatar--compact" : ""}`}
    data-avatar-state={state}
    role="img"
    aria-label={`星环助手：${stateLabels[state]}`}
  >
    <span className="studio-avatar__orbit" aria-hidden="true" />
    <span className="studio-avatar__body" aria-hidden="true">
      <span className="studio-avatar__antenna" />
      <span className="studio-avatar__face">
        <i className="studio-avatar__eye" />
        <i className="studio-avatar__eye" />
        <i className="studio-avatar__mouth" />
      </span>
      <span className="studio-avatar__core" />
    </span>
    <span className="studio-avatar__spark studio-avatar__spark--one" aria-hidden="true" />
    <span className="studio-avatar__spark studio-avatar__spark--two" aria-hidden="true" />
  </div>
);
