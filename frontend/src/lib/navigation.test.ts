import { describe, expect, it } from "vitest";
import { parseRoute, pathFor } from "./navigation";

describe("hash navigation", () => {
  it("round-trips project workspaces", () => {
    const route = { page: "workspace" as const, projectId: "project with spaces" };
    expect(pathFor(route)).toBe("/projects/project with spaces");
    expect(parseRoute(`#${encodeURI(pathFor(route))}`)).toEqual({ page: "workspace", projectId: "project with spaces" });
  });

  it("falls back to projects for unknown paths", () => {
    expect(parseRoute("#/unknown")).toEqual({ page: "projects" });
  });
});
