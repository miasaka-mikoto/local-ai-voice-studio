import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import App from "./App";
import { StudioProvider } from "./StudioContext";

describe("application smoke", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("local-ai-voice-studio.data-mode", "mock");
    window.location.hash = "/projects";
  });

  it("restores the mock project dashboard without a backend", async () => {
    render(<StudioProvider><App /></StudioProvider>);
    expect(await screen.findByRole("heading", { name: "今天要推进哪个项目？" }, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText("雨夜电车 · 第 01 话")).toBeInTheDocument();
    expect(screen.getAllByText(/本地 MOCK/).length).toBeGreaterThan(0);
    expect(screen.getByText("7860 模型实验台独立")).toBeInTheDocument();
    expect(screen.queryByText("7860 保持运行")).not.toBeInTheDocument();
  });

  it("describes model configuration without claiming a live external service", async () => {
    render(<StudioProvider><App /></StudioProvider>);
    await screen.findByRole("heading", { name: "今天要推进哪个项目？" }, { timeout: 5000 });
    screen.getByRole("button", { name: "系统与模型" }).click();
    expect(await screen.findByRole("heading", { name: "系统、模型与诊断" })).toBeInTheDocument();
    expect(screen.getByText("模型执行由用户配置")).toBeInTheDocument();
    expect(screen.queryByText("当前禁止真实模型加载")).not.toBeInTheDocument();
  });

  it("shows the project lesson handoff without pretending Mock mode saves a course", async () => {
    render(<StudioProvider><App /></StudioProvider>);
    await screen.findByRole("heading", { name: "今天要推进哪个项目？" }, { timeout: 5000 });
    screen.getByRole("button", { name: /雨夜电车 · 第 01 话/ }).click();
    (await screen.findByRole("tab", { name: "日语课程" })).click();
    expect(await screen.findByRole("heading", { name: "项目台词转日语课程" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建并保存课程" })).toBeDisabled();
    expect(screen.getByText(/当前是浏览器 Mock/)).toBeInTheDocument();
  });
});
