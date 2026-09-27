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
  });
});
