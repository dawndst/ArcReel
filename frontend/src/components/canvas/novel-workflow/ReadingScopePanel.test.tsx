import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ReadingScopePanel } from "./ReadingScopePanel";

it("keeps scope adjustment separate from reading and saves selected chapters explicitly", () => {
  const save = vi.fn();
  render(<ReadingScopePanel scope={undefined} selected={["n1"]} disabled={false} save={save} />);
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText(/当前可用章节/));
  fireEvent.click(screen.getByRole("button", { name: "以所选章节设定可用范围" }));
  expect(save).toHaveBeenCalledOnce();
  expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
});
