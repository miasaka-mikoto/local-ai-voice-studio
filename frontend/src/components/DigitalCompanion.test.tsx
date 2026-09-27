import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { companionStateFromConversation, DigitalCompanion } from "./DigitalCompanion";

describe("DigitalCompanion", () => {
  afterEach(cleanup);
  it("renders the original CSS companion while keeping local scene art", () => {
    const { container } = render(
      <DigitalCompanion
        state="listening"
        subtitle="ゆっくり話してね。"
        emotion="专注"
        sceneTitle="车站买票"
        sceneImageUrl="/assets/scenes/station.webp"
      />,
    );

    expect(screen.getByLabelText("数字伙伴陪聊舞台")).toHaveAttribute("data-companion-state", "listening");
    expect(screen.getByText("正在听")).toBeInTheDocument();
    expect(screen.getByAltText("车站买票场景插画")).toHaveAttribute("src", "/assets/scenes/station.webp");
    expect(screen.getByRole("img", { name: "星环助手：正在聆听" })).toHaveAttribute("data-avatar-state", "listening");
    expect(container.querySelector(".studio-avatar img")).not.toBeInTheDocument();
    expect(container.querySelector(".companion-portrait__fallback")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "星环助手 · 本机互动伙伴" })).toBeInTheDocument();
    expect(screen.getByText("原创轻量形象")).toBeInTheDocument();
    expect(screen.getByText("VRM 需用户自备授权")).toBeInTheDocument();
    expect(screen.getByText("VRM 连接位")).toBeInTheDocument();
    expect(screen.getByText("Live2D 外部连接位")).toBeInTheDocument();
  });

  it("sends a scene suggestion back to the conversation composer", () => {
    const onSuggestion = vi.fn();
    render(
      <DigitalCompanion
        state="idle"
        subtitle="こんにちは。"
        emotion="放松"
        sceneTitle="咖啡店点单"
        sceneImageUrl="/assets/scenes/cafe.webp"
        suggestions={["おすすめは何ですか？"]}
        onSuggestion={onSuggestion}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "おすすめは何ですか？" }));
    expect(onSuggestion).toHaveBeenCalledWith("おすすめは何ですか？");
  });

  it("maps recorder and teacher phases to the five visual states", () => {
    expect(companionStateFromConversation({ phase: "idle", recorderStatus: "recording", hasError: false })).toBe("listening");
    expect(companionStateFromConversation({ phase: "uploading", recorderStatus: "recorded", hasError: false })).toBe("thinking");
    expect(companionStateFromConversation({ phase: "thinking", recorderStatus: "recorded", hasError: false })).toBe("thinking");
    expect(companionStateFromConversation({ phase: "playing", recorderStatus: "idle", hasError: false })).toBe("speaking");
    expect(companionStateFromConversation({ phase: "idle", recorderStatus: "idle", hasError: true })).toBe("error");
    expect(companionStateFromConversation({ phase: "idle", recorderStatus: "idle", hasError: false })).toBe("idle");
  });

  it("switches to the local VRM connector without loading a model before authorization", () => {
    const { container } = render(
      <DigitalCompanion
        state="idle"
        subtitle="こんにちは。"
        emotion="放松"
        sceneTitle="咖啡店点单"
        sceneImageUrl="/assets/scenes/cafe.webp"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /VRM 连接位/ }));
    expect(container.querySelector(".companion-portrait")).toHaveClass("companion-portrait--vrm");
    expect(screen.getByRole("checkbox", { name: "我有使用、扮演、再分发所需授权" })).not.toBeChecked();
    expect(screen.getByLabelText("选择本机 .vrm")).toBeDisabled();
    expect(screen.getByText("用户自备 VRM · 本机互动伙伴")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "星环助手：待机陪伴" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Live2D 外部连接位/ })).toBeDisabled();
  });
});
