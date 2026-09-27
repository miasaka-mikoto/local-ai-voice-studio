import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { VRMAvatar } from "./VRMAvatar";

describe("VRMAvatar", () => {
  afterEach(cleanup);
  it("keeps the static fallback and gates local file access on an explicit license acknowledgement", () => {
    render(<VRMAvatar state="idle" fallback={<span>static fallback</span>} />);

    expect(screen.getByText("static fallback")).toBeInTheDocument();
    const checkbox = screen.getByRole("checkbox", { name: "我有使用、扮演、再分发所需授权" });
    const fileInput = screen.getByLabelText("选择本机 .vrm");
    expect(checkbox).not.toBeChecked();
    expect(fileInput).toBeDisabled();

    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
    expect(fileInput).not.toBeDisabled();
    expect(screen.getByText("选择本机 .vrm")).toBeInTheDocument();
  });

  it("rejects a mismatched local extension before loading the lazy runtime", () => {
    render(<VRMAvatar state="idle" fallback={<span>static fallback</span>} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "我有使用、扮演、再分发所需授权" }));
    const fileInput = screen.getByLabelText("选择本机 .vrm");
    fireEvent.change(fileInput, { target: { files: [new File(["not a vrm"], "avatar.glb", { type: "model/gltf+json" })] } });
    expect(screen.getByRole("alert")).toHaveTextContent("请选择 .vrm 文件");
    expect(screen.getByText("static fallback")).toBeInTheDocument();
  });
});
