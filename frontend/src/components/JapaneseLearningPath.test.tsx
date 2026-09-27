import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JapaneseLearningPath } from "./JapaneseLearningPath";

describe("JapaneseLearningPath", () => {
  afterEach(cleanup);

  it("shows the four-stage N5-N1 curve without inventing an overall score", () => {
    render(
      <JapaneseLearningPath
        path={null}
        progress={null}
        selectedStageId="daily_independence"
        onStageChange={() => undefined}
        onScenarioSelect={() => undefined}
        connectionMode="mock"
      />,
    );

    expect(screen.getByRole("heading", { name: "日语提升路径" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /N5.*生存基础/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /N4.*独立生活/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /N2–N1.*复杂现实沟通/ })).toBeInTheDocument();
    expect(screen.getAllByText(/总分/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("—")).toHaveLength(3);
  });

  it("routes stage and scenario recommendations back to the conversation", () => {
    const onStageChange = vi.fn();
    const onScenarioSelect = vi.fn();
    render(
      <JapaneseLearningPath
        path={null}
        progress={null}
        selectedStageId="foundation"
        onStageChange={onStageChange}
        onScenarioSelect={onScenarioSelect}
        connectionMode="mock"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /N3.*社会与职场/ }));
    fireEvent.click(screen.getByRole("button", { name: /下一场：车站买票/ }));
    expect(onStageChange).toHaveBeenCalledWith("social_work");
    expect(onScenarioSelect).toHaveBeenCalledWith("station-ticket");
  });
});
