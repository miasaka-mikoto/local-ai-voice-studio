import { useEffect, useState } from "react";
import {
  avatarProviderCatalog,
  defaultAvatarProvider,
  resolveAvatarProvider,
  type AvatarProviderDescriptor,
} from "../lib/avatarProviders";
import { vrmEmotionFromLabel, type VrmMetaSummary } from "../lib/vrm";
import { StudioAvatar } from "./StudioAvatar";
import { VRMAvatar } from "./VRMAvatar";

export type CompanionState = "idle" | "listening" | "thinking" | "speaking" | "error";
export type CompanionConversationPhase = "idle" | "uploading" | "transcribing" | "thinking" | "playing" | "error";
export type CompanionRecorderStatus = "idle" | "requesting" | "recording" | "recorded" | "error";

export const companionStateFromConversation = ({
  phase,
  recorderStatus,
  hasError,
}: {
  phase: CompanionConversationPhase;
  recorderStatus: CompanionRecorderStatus;
  hasError: boolean;
}): CompanionState => {
  if (hasError || recorderStatus === "error" || phase === "error") return "error";
  if (recorderStatus === "requesting" || recorderStatus === "recording") return "listening";
  if (phase === "playing") return "speaking";
  if (phase === "uploading" || phase === "transcribing" || phase === "thinking") return "thinking";
  return "idle";
};

const stateLabels: Record<CompanionState, string> = {
  idle: "待机",
  listening: "正在听",
  thinking: "整理回应",
  speaking: "正在说",
  error: "需要重试",
};

export interface DigitalCompanionProps {
  state: CompanionState;
  subtitle: string;
  emotion: string;
  sceneTitle: string;
  sceneImageUrl: string;
  provider?: AvatarProviderDescriptor;
  suggestions?: readonly string[];
  onSuggestion?(suggestion: string): void;
}

export const DigitalCompanion = ({
  state,
  subtitle,
  emotion,
  sceneTitle,
  sceneImageUrl,
  provider = defaultAvatarProvider,
  suggestions = [],
  onSuggestion,
}: DigitalCompanionProps) => {
  const [sceneMissing, setSceneMissing] = useState(false);
  const [activeProviderId, setActiveProviderId] = useState(provider.id);
  const [vrmMeta, setVrmMeta] = useState<VrmMetaSummary | null>(null);

  useEffect(() => setSceneMissing(false), [sceneImageUrl]);
  useEffect(() => setActiveProviderId(provider.id), [provider.id]);

  const activeProvider = activeProviderId === provider.id ? provider : resolveAvatarProvider(activeProviderId);
  const companionTitle = activeProvider.kind === "vrm"
    ? `${vrmMeta?.modelName ?? "用户自备 VRM"} · 本机互动伙伴`
    : "星环助手 · 本机互动伙伴";
  const studioAvatar = <StudioAvatar state={state} compact={activeProvider.kind === "vrm"} />;

  return (
    <section className={`companion-stage companion-stage--${state}`} data-companion-state={state} aria-label="数字伙伴陪聊舞台">
      <div className="companion-stage__scene">
        {!sceneMissing ? <img src={sceneImageUrl} alt={`${sceneTitle}场景插画`} onError={() => setSceneMissing(true)} /> : null}
        <span className="companion-stage__wash" />
      </div>

      <div className="companion-stage__copy">
        <header>
          <div>
            <span className="companion-stage__eyebrow">DIGITAL COMPANION · {sceneTitle}</span>
            <h2>{companionTitle}</h2>
          </div>
          <span className="companion-state" aria-live="polite"><i />{stateLabels[state]}</span>
        </header>

        <div className="companion-subtitle" aria-live="polite" aria-atomic="true">
          <span>{emotion}</span>
          <p lang="ja">{subtitle}</p>
        </div>

        {suggestions.length && onSuggestion ? (
          <div className="companion-suggestions" aria-label="场景开场建议">
            {suggestions.map((suggestion) => (
              <button type="button" key={suggestion} onClick={() => onSuggestion(suggestion)}>{suggestion}</button>
            ))}
          </div>
        ) : null}

        <footer>
          <strong>{activeProvider.kind === "vrm" ? "用户本机模型" : "原创轻量形象"}</strong>
          <strong className="companion-license-badge">VRM 需用户自备授权</strong>
          <span>
            {activeProvider.kind === "vrm"
              ? vrmMeta
                ? `${vrmMeta.modelName} · ${vrmMeta.authors.join(", ")}；模型与声音授权仍需分别核验。`
                : "VRM 仅在当前浏览器会话读取，不上传、不写服务器。"
              : "默认形象仅由本项目 CSS 绘制，不含外部角色帧或模型；声音授权需单独核验。"}
          </span>
        </footer>
      </div>

      <div className={`companion-portrait companion-portrait--${activeProvider.kind}`} aria-label={`${activeProvider.label}：${activeProvider.description}`}>
        <span className="companion-portrait__halo" aria-hidden="true" />
        {activeProvider.kind === "vrm" ? (
          <VRMAvatar state={state} expression={vrmEmotionFromLabel(emotion) ?? undefined} fallback={studioAvatar} compact onMeta={setVrmMeta} />
        ) : activeProvider.kind === "css-avatar" ? studioAvatar : (
          <span className="companion-portrait__fallback" aria-hidden="true">L2D</span>
        )}
        <span className="companion-provider-badge">{activeProvider.label}</span>
      </div>

      <details className="companion-connectors">
        <summary>形象 Provider</summary>
        <ul>
          {avatarProviderCatalog.map((candidate) => (
            <li key={candidate.id}>
              <button
                type="button"
                className={activeProvider.id === candidate.id ? "is-active" : ""}
                disabled={candidate.availability !== "available"}
                onClick={() => {
                  setActiveProviderId(candidate.id);
                  if (candidate.kind !== "vrm") setVrmMeta(null);
                }}
                aria-pressed={activeProvider.id === candidate.id}
              >
                <span>{candidate.label}</span>
                <small>{candidate.availability === "available" ? candidate.kind === "vrm" ? "本机文件" : "当前可用" : "仅预留连接位"}</small>
              </button>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
};
