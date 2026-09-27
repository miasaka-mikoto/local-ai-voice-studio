export type AvatarProviderKind = "css-avatar" | "vrm" | "live2d-external";

export type AvatarProviderAvailability = "available" | "connector-required";

export interface AvatarProviderDescriptor {
  id: string;
  kind: AvatarProviderKind;
  label: string;
  availability: AvatarProviderAvailability;
  description: string;
}

export const avatarProviderCatalog: readonly AvatarProviderDescriptor[] = [
  {
    id: "studio-orbit",
    kind: "css-avatar",
    label: "星环助手",
    availability: "available",
    description: "原创 CSS 互动形象；不加载第三方角色素材。",
  },
  {
    id: "vrm-connector",
    kind: "vrm",
    label: "VRM 连接位",
    availability: "available",
    description: "懒加载 Three.js/three-vrm；仅渲染用户确认授权的本机 .vrm 文件，不上传。",
  },
  {
    id: "live2d-external-connector",
    kind: "live2d-external",
    label: "Live2D 外部连接位",
    availability: "connector-required",
    description: "仅预留外部渲染器连接位；当前不包含 Cubism runtime。",
  },
] as const;

export const defaultAvatarProvider = avatarProviderCatalog[0];

export const resolveAvatarProvider = (providerId?: string) =>
  avatarProviderCatalog.find((provider) => provider.id === providerId) ?? defaultAvatarProvider;
