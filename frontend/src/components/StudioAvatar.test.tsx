import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { StudioAvatar } from "./StudioAvatar";

describe("StudioAvatar", () => {
  afterEach(cleanup);

  it.each([
    ["idle", "待机陪伴"],
    ["listening", "正在聆听"],
    ["thinking", "正在整理回应"],
    ["speaking", "正在说话"],
    ["error", "等待重试"],
  ] as const)("renders the %s state without external assets", (state, label) => {
    const { container } = render(<StudioAvatar state={state} />);
    expect(screen.getByRole("img", { name: `星环助手：${label}` })).toHaveAttribute("data-avatar-state", state);
    expect(container.querySelector("img, canvas, video")).not.toBeInTheDocument();
  });

  it("can render as a compact fallback for a user-supplied VRM", () => {
    render(<StudioAvatar state="idle" compact />);
    expect(screen.getByRole("img", { name: /星环助手/ })).toHaveClass("studio-avatar--compact");
  });
});
