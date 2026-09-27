import type { JobStatus, ProjectKind } from "../types";

export const projectKindLabel: Record<ProjectKind, string> = {
  video_dubbing: "视频 / 动画配音",
  game_voice: "游戏语音资产",
  voice_dataset: "角色与训练数据",
  japanese_learning: "日语口语训练",
};

export const projectKindShort: Record<ProjectKind, string> = {
  video_dubbing: "视频配音",
  game_voice: "游戏语音",
  voice_dataset: "声音数据",
  japanese_learning: "日语训练",
};

export const jobStatusLabel: Record<JobStatus, string> = {
  queued: "排队中",
  running: "运行中",
  paused: "已暂停",
  failed: "失败",
  completed: "已完成",
  stale: "已过期",
  cancelled: "已取消",
};

export const jobStatusTone = (status: JobStatus): "neutral" | "success" | "warning" | "danger" | "info" | "purple" => {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "running") return "info";
  if (status === "queued" || status === "paused") return "warning";
  if (status === "stale") return "purple";
  return "neutral";
};

export const relativeTime = (iso: string) => {
  const delta = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(delta)) return "未知";
  const minutes = Math.round(delta / 60000);
  if (Math.abs(minutes) < 1) return "刚刚";
  if (Math.abs(minutes) < 60) return `${Math.abs(minutes)} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return `${Math.abs(hours)} 小时前`;
  const days = Math.round(hours / 24);
  return `${Math.abs(days)} 天前`;
};

export const formatDuration = (milliseconds: number | null) => {
  if (milliseconds === null) return "—";
  const minutes = Math.floor(milliseconds / 60000);
  const seconds = (milliseconds % 60000) / 1000;
  return minutes ? `${minutes}:${seconds.toFixed(2).padStart(5, "0")}` : `${seconds.toFixed(2)}s`;
};

export const formatClock = (milliseconds: number | null) => {
  if (milliseconds === null) return "—";
  const totalSeconds = milliseconds / 1000;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${seconds.toFixed(2).padStart(5, "0")}`;
};

export const actionLabel = {
  pause: "暂停",
  resume: "恢复",
  retry: "重试",
  cancel: "取消",
  recompute: "重新计算",
} as const;
