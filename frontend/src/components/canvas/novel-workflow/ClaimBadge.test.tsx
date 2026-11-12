import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ClaimBadge } from "./ClaimBadge";

it("distinguishes missing classification from an explicit unresolved claim and exposes the actual reason", () => {
  const { rerender } = render(<ClaimBadge value={{}} />);
  expect(screen.getByText("信息性质未标注")).toBeInTheDocument();
  rerender(<ClaimBadge value={{ claim_type: "unverified", source_kind: "narrative", uncertainty_reason: "当前片段尚未说明是梦境还是现实" }} />);
  expect(screen.getByText("信息性质待判定")).toHaveAttribute("title", "当前片段尚未说明是梦境还是现实");
  expect(screen.queryByText("信息性质未标注")).not.toBeInTheDocument();
});
